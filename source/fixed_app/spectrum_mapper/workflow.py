from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from .engine import (
    apply_palette_overrides,
    apply_palette_overrides_parts,
    edge_topology,
    emit,
    face_neighbors_partial,
    make_report,
    recolor_level,
    recolor_level_parts,
    signed_volume,
    triangle_areas,
    write_3mf_atomic,
    write_guide,
    write_vertex_color_obj,
)
from .generated_surface_color import (
    attach_generated_surface_export_context,
    make_face_provenance_record,
    optimize_generated_hidden_colors,
    validate_face_provenance,
)
from .filament_materials import generic_filament_profile
from .models import (
    AppSettings,
    ExportResult,
    MeshLevel,
    PaletteSettings,
    PreparedGeometry,
    ProgressCallback,
)
from .mixer import black_output_ratio_preset
from .parts import plan_palette_groups, resolve_part_palette_settings


def _safe_part_filename(value: str, index: int) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value)).strip(" ._")
    if not cleaned:
        cleaned = f"part_{index + 1}"
    return f"{index + 1:02d}_{cleaned[:80]}"


def _extract_level_part(
    level: MeshLevel,
    part_id: int,
) -> tuple[MeshLevel, np.ndarray]:
    face_part_ids = np.asarray(level.face_part_ids)
    selected = np.flatnonzero(face_part_ids == int(part_id))
    if not len(selected):
        raise ValueError(f"空のパーツは出力できません: {part_id + 1}")
    source_faces = np.asarray(level.faces[selected], dtype=np.int32)
    used = np.unique(source_faces.reshape(-1))
    local_faces = np.searchsorted(used, source_faces).astype(np.int32)
    vertices = np.asarray(level.vertices_unit[used], dtype=np.float64).copy()
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    vertices[:, 0] -= (minimum[0] + maximum[0]) * 0.5
    vertices[:, 1] -= (minimum[1] + maximum[1]) * 0.5
    vertices[:, 2] -= minimum[2]
    colors = np.asarray(level.vertex_colors[used], dtype=np.float64)
    source_provenance = np.asarray(level.face_provenance)
    face_provenance = (
        source_provenance[selected].astype(np.uint8, copy=True)
        if source_provenance.shape == (len(level.faces),)
        else np.empty(0, dtype=np.uint8)
    )
    name = level.part_names[part_id]
    key = level.part_keys[part_id]
    return (
        MeshLevel(
            vertices_unit=vertices,
            faces=local_faces,
            vertex_colors=colors,
            areas_unit=triangle_areas(vertices, local_faces),
            neighbors=face_neighbors_partial(local_faces, len(vertices)),
            face_part_ids=np.zeros(len(local_faces), dtype=np.int16),
            face_provenance=face_provenance,
            part_names=(name,),
            part_keys=(key,),
        ),
        selected,
    )


def _extract_prepared_part(
    prepared: PreparedGeometry,
    part_id: int,
) -> tuple[PreparedGeometry, np.ndarray]:
    parent_provenance = validate_face_provenance(prepared)
    final, source_face_ids = _extract_level_part(prepared.final, part_id)
    preview, _preview_face_ids = _extract_level_part(prepared.preview, part_id)
    if not parent_provenance.valid:
        final.face_provenance = np.empty(0, dtype=np.uint8)
    topology = edge_topology(final.faces, len(final.vertices_unit))
    stats = (
        [dict(prepared.part_stats[part_id])]
        if part_id < len(prepared.part_stats)
        else []
    )
    part_provenance_record = make_face_provenance_record(
        final,
        status="fresh" if parent_provenance.valid else "unavailable",
        reason="ok" if parent_provenance.valid else parent_provenance.reason,
        includes_topology_edits=bool(
            parent_provenance.record.get("includes_topology_edits", False)
        ),
    )
    result = PreparedGeometry(
        source=prepared.source,
        final=final,
        preview=preview,
        clean_vertex_count=len(final.vertices_unit),
        clean_face_count=len(final.faces),
        removed_vertices=0,
        removed_faces=0,
        topology=topology,
        source_area_unit=float(final.areas_unit.sum()),
        source_volume_unit=signed_volume(final.vertices_unit, final.faces),
        simplified_area_unit=float(final.areas_unit.sum()),
        simplified_volume_unit=signed_volume(final.vertices_unit, final.faces),
        source_dimensions_unit=np.ptp(final.vertices_unit, axis=0),
        warnings=list(prepared.warnings),
        part_names=final.part_names,
        part_keys=final.part_keys,
        part_stats=stats,
        assembly={
            "individual_part_export": True,
            "source_part_index": int(part_id),
            "source_part_key": final.part_keys[0],
            "all_parts_watertight": bool(topology["watertight"]),
            "parent_assembly": dict(prepared.assembly or {}),
            "generated_surface_provenance": part_provenance_record,
        },
    )
    tree_store = getattr(prepared, "_hotfix_subtriangle_paint", None)
    if isinstance(tree_store, Mapping):
        local_trees: dict[int, object] = {}
        for face_id, tree in tree_store.items():
            try:
                source_face_id = int(face_id)
            except (TypeError, ValueError):
                continue
            position = int(np.searchsorted(source_face_ids, source_face_id))
            if (
                0 <= position < len(source_face_ids)
                and int(source_face_ids[position]) == source_face_id
            ):
                local_trees[position] = tree
        if local_trees:
            result._hotfix_subtriangle_paint = local_trees
    return result, source_face_ids


def optimize_generated_surface_export(
    prepared: PreparedGeometry,
    colors,
    height_mm: float,
    manual_overrides: np.ndarray | None,
):
    """Apply safe hidden-surface colour reduction and publish r8 context."""

    result = optimize_generated_hidden_colors(
        prepared,
        colors,
        height_mm,
        manual_overrides=manual_overrides,
    )
    attach_generated_surface_export_context(prepared, result)
    return result.colors


def _part_export_palette_with_global_output_policy(
    global_palette: PaletteSettings,
    local_palette: PaletteSettings,
) -> PaletteSettings:
    """Apply global output-only policy without replacing a part's own colours.

    Physical colours, display ratios, enabled states and filament product
    references remain local to the part.  An explicit local output-ratio list
    wins; otherwise the global black-output correction is inherited.  Surface
    shell output is enabled when either scope requests it.

    Return the original object when no value changes.  Besides avoiding an
    unnecessary copy, this keeps the legacy OFF/None export path identical.
    """

    output_ratios = local_palette.output_mix_ratios_b
    if output_ratios is None and global_palette.output_mix_ratios_b is not None:
        global_output = list(global_palette.output_mix_ratios_b)
        output_ratios = global_output
        # The GUI's weak-black correction is a semantic preset, not an
        # arbitrary replacement for every part's display recipe.  Recover its
        # selected F1-F4 slot and rebuild it against this part's own primary
        # and secondary ratios so non-black mixes remain local to the part.
        for slot_index in range(4):
            if global_output == black_output_ratio_preset(
                slot_index,
                global_palette.mix_ratios_b,
                global_palette.secondary_mix_ratios_b,
            ):
                output_ratios = black_output_ratio_preset(
                    slot_index,
                    local_palette.mix_ratios_b,
                    local_palette.secondary_mix_ratios_b,
                )
                break
    surface_shell_enabled = bool(
        local_palette.surface_shell_enabled
        or global_palette.surface_shell_enabled
    )
    if (
        output_ratios is local_palette.output_mix_ratios_b
        and surface_shell_enabled == bool(local_palette.surface_shell_enabled)
    ):
        return local_palette

    result = copy.deepcopy(local_palette)
    result.output_mix_ratios_b = (
        None if output_ratios is None else list(output_ratios)
    )
    result.surface_shell_enabled = surface_shell_enabled
    return result


def _write_individual_part_models(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    manual_overrides: np.ndarray | None,
    progress: ProgressCallback | None,
) -> tuple[Path, ...]:
    palettes = tuple(
        _part_export_palette_with_global_output_policy(
            settings.palette,
            local_palette,
        )
        for local_palette in resolve_part_palette_settings(
            settings, prepared.final
        )
    )
    base_output_dir = destination.with_suffix("").with_name(
        destination.stem + "_parts"
    )
    output_dir = base_output_dir
    suffix = 2
    while output_dir.exists():
        output_dir = base_output_dir.with_name(f"{base_output_dir.name}_{suffix}")
        suffix += 1
    staging_dir = output_dir.with_name(
        f".{output_dir.name}.{uuid.uuid4().hex}.tmp"
    )
    staging_dir.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    manifest_parts: list[dict[str, object]] = []
    part_count = len(prepared.final.part_keys)
    try:
        for part_id, (name, key, palette) in enumerate(
            zip(
                prepared.final.part_names,
                prepared.final.part_keys,
                palettes,
                strict=True,
            )
        ):
            emit(
                progress,
                "part_3mf",
                0.66 + 0.16 * part_id / max(part_count, 1),
                f"パーツ別3MF {part_id + 1}/{part_count}: {name}",
            )
            part_prepared, source_face_ids = _extract_prepared_part(
                prepared, part_id
            )
            part_colors = recolor_level(
                part_prepared.final,
                settings.geometry.height_mm,
                settings.tone,
                palette,
            )
            part_manual_overrides = None
            if manual_overrides is not None:
                part_manual_overrides = np.asarray(manual_overrides)[source_face_ids]
                part_colors = apply_palette_overrides(
                    part_prepared.final,
                    settings.geometry.height_mm,
                    palette,
                    part_colors,
                    part_manual_overrides,
                )
            part_colors = optimize_generated_surface_export(
                part_prepared,
                part_colors,
                settings.geometry.height_mm,
                part_manual_overrides,
            )
            part_path = staging_dir / (
                _safe_part_filename(name, part_id) + "_FullSpectrum.3mf"
            )
            validation = write_3mf_atomic(
                part_path,
                part_prepared,
                part_colors,
                settings.geometry.height_mm,
                palette,
                {},
                False,
            )
            paths.append(part_path)
            manifest_parts.append(
                {
                    "index": int(part_id),
                    "name": name,
                    "key": key,
                    "file": part_path.name,
                    "faces": int(len(part_prepared.final.faces)),
                    "watertight": bool(part_prepared.topology["watertight"]),
                    "sha256": validation.get("sha256"),
                    "physical_filaments": list(palette.physical_hex),
                    "material": palette.material,
                    "physical_filament_refs": AppSettings(
                        palette=palette
                    ).to_dict()["palette"]["physical_filament_refs"],
                }
            )
        manifest = {
            "schema": "tripo-spectrum-mapper.part-exports.v1",
            "source_assembly": str(destination.name),
            "layer_height_mm": 0.08,
            "initial_layer_height_mm": 0.2,
            "support_fixed": False,
            "parts": manifest_parts,
        }
        (staging_dir / "パーツ別3MF_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8-sig",
        )
        staging_dir.replace(output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return tuple(output_dir / path.name for path in paths)


def _write_individual_only_guide(
    path: Path,
    destination: Path,
    prepared: PreparedGeometry,
    settings: AppSettings,
    part_model_paths: tuple[Path, ...],
) -> None:
    palettes = tuple(
        _part_export_palette_with_global_output_policy(settings.palette, palette)
        for palette in resolve_part_palette_settings(settings, prepared.final)
    )
    rows = "\n".join(
        f"- {model_path.name}: {palette.material} / "
        f"{generic_filament_profile(palette.material)}"
        for model_path, palette in zip(part_model_paths, palettes, strict=True)
    )
    text = f"""ChromaMatter パーツ別3MFの読み込み方
============================================

指定した出力名: {destination.name}

パーツごとに素材が異なるため、複数素材を混在させた統合3MFは作成していません。
次の各ファイルは、同一素材4本だけを使用する独立した印刷ジョブです。

{rows}

1. 使用するパーツ3MFをSnapmaker Orcaで「Open as project / プロジェクトとして開く」で開きます。
2. 3MF内のGenericプロファイルは仮設定です。同じ素材の実スプール用プロファイルへF1～F4を差し替えます。
3. 1つの印刷ジョブにPLA／ABS／PETGを混在させないでください。
4. 通常層0.08 mmを確認し、サポートはモデルごとに設定します。
5. ABSは登録色・実測・色域が少ないため、実機比較チャートで確認し、Snapmaker U1ではTop Coverを使用してください。

ABS／PETGの色予測はβ機能です。実フィラメントの銘柄・ロット・光沢・不透明度で結果が変わります。
"""
    path.write_text(text, encoding="utf-8-sig")


def export_bundle(
    prepared: PreparedGeometry,
    settings: AppSettings,
    destination: Path,
    reference_path: Path | None = None,
    include_vertex_obj: bool = True,
    progress: ProgressCallback | None = None,
    manual_overrides: np.ndarray | None = None,
    force_common_palette: bool = False,
    individual_only: bool = False,
) -> ExportResult:
    """Create the 3MF and all human-readable sidecars for one conversion."""

    destination = Path(destination).with_suffix(".3mf")
    if individual_only and destination.exists():
        raise ValueError(
            "パーツ別のみ出力では既存の統合3MFと同じ名前を使用できません。"
            "古い統合3MFを誤って印刷しないよう、別の出力名を選んでください。"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    stem = destination.with_suffix("")
    preview_path = stem.with_name(stem.name + "_preview.png")
    report_path = stem.with_name(stem.name + "_validation.json")
    guide_path = stem.with_name(stem.name + "_使い方.txt")
    fallback_obj_path = (
        stem.with_name(stem.name + "_vertexcolor.obj") if include_vertex_obj else None
    )

    grouping = plan_palette_groups(settings, prepared.final)
    resolved_materials = {
        palette.material
        for palette in resolve_part_palette_settings(settings, prepared.final)
    }
    if len(resolved_materials) > 1 and force_common_palette:
        raise ValueError(
            "異素材のパーツ設定を全体共通素材へ強制統合できません。"
            "各パーツを素材別の独立3MFとして出力してください。"
        )
    if force_common_palette and individual_only:
        raise ValueError("全体共通3MFとパーツ別のみ出力は同時に指定できません")
    if individual_only and not grouping.requires_separate_jobs:
        raise ValueError("パーツ別のみ出力は複数の基本4色構成がある場合に使用します")
    if grouping.requires_separate_jobs and not (force_common_palette or individual_only):
        if len(resolved_materials) > 1:
            raise ValueError(
                "PLA/ABS/PETGを1つの3MF印刷ジョブへ混在できません。"
                "全体共通素材で出力するか、パーツ別3MFを使用してください。"
            )
        raise ValueError(
            "パーツごとの物理4色が異なるため、U1の1回印刷用3MFにはできません。"
            "全体共通4色で出力するか、パーツ設定を揃えてください。"
        )
    if grouping.one_job or individual_only:
        effective_part_palettes = settings.part_palettes
        print_palette = (
            settings.palette
            if individual_only
            else resolve_part_palette_settings(settings, prepared.final)[0]
        )
    else:
        effective_part_palettes = {}
        print_palette = settings.palette

    emit(progress, "color", 0.04, "最終メッシュへ色を割り当てています")
    final_colors = recolor_level_parts(
        prepared.final,
        settings.geometry.height_mm,
        settings.tone,
        settings.palette,
        effective_part_palettes,
    )
    if manual_overrides is not None:
        final_colors = apply_palette_overrides_parts(
            prepared.final,
            settings.geometry.height_mm,
            settings.palette,
            effective_part_palettes,
            final_colors,
            manual_overrides,
        )
    final_colors = optimize_generated_surface_export(
        prepared,
        final_colors,
        settings.geometry.height_mm,
        manual_overrides,
    )
    if individual_only:
        validation: dict[str, object] = {
            "valid": True,
            "combined_model_written": False,
            "individual_only": True,
            "materials": sorted(resolved_materials),
        }
    else:
        emit(progress, "3mf", 0.16, "Snapmaker Orca用3MFを書き出しています")
        validation = write_3mf_atomic(
            destination,
            prepared,
            final_colors,
            settings.geometry.height_mm,
            print_palette,
            settings.part_palettes,
            bool(grouping.requires_separate_jobs and force_common_palette),
        )

    part_model_paths: tuple[Path, ...] = ()
    if (
        (individual_only or bool(settings.geometry.export_individual_parts))
        and len(prepared.final.part_keys) > 1
    ):
        part_model_paths = _write_individual_part_models(
            prepared,
            settings,
            destination,
            manual_overrides,
            progress,
        )
        validation["individual_part_models"] = [
            str(path) for path in part_model_paths
        ]

    if fallback_obj_path is not None:
        emit(progress, "obj", 0.76, "予備の頂点カラーOBJを書き出しています")
        write_vertex_color_obj(
            fallback_obj_path,
            prepared,
            final_colors,
            settings.geometry.height_mm,
        )

    emit(progress, "report", 0.86, "検証レポートを作成しています")
    report = make_report(
        prepared,
        final_colors,
        settings.geometry.height_mm,
        settings.tone,
        print_palette,
        validation,
    )
    self_intersection_warning = {
        "parts": int(
            validation.get("self_intersection_warning_parts", 0) or 0
        ),
        "policy": str(
            validation.get(
                "self_intersection_warning_policy", "strict_zero"
            )
        ),
        "policies": list(
            validation.get("self_intersection_warning_policies", []) or []
        ),
        "faces": int(
            validation.get("self_intersection_warning_faces", 0) or 0
        ),
        "area_mm2": float(
            validation.get("self_intersection_warning_area", 0.0) or 0.0
        ),
        "maximum_area_fraction": float(
            validation.get(
                "self_intersection_warning_max_area_fraction", 0.0
            )
            or 0.0
        ),
        "orca_preview_required": bool(
            validation.get("self_intersection_warning_parts", 0)
        ),
    }
    report["self_intersection_warning"] = self_intersection_warning
    report["reference_image"] = str(reference_path) if reference_path else None
    report["parts"] = {
        "count": len(prepared.final.part_keys),
        "required_palette_groups": len(grouping.groups),
        "one_print_job_compatible": grouping.one_job,
        "forced_common_palette_for_print": bool(
            grouping.requires_separate_jobs and force_common_palette
        ),
        "part_metrics": final_colors.part_metrics,
        "individual_model_paths": [str(path) for path in part_model_paths],
        "individual_only": bool(individual_only),
    }
    report["assembly"] = dict(prepared.assembly or {})
    report["print_profile"] = {
        "id": "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)",
        "layer_height_mm": 0.08,
        "initial_layer_height_mm": 0.2,
        "support_fixed": False,
        "filament_material": None if individual_only else print_palette.material,
        "individual_part_materials": sorted(resolved_materials),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig"
    )
    if individual_only:
        _write_individual_only_guide(
            guide_path,
            destination,
            prepared,
            settings,
            part_model_paths,
        )
    else:
        write_guide(
            guide_path,
            destination,
            settings.geometry.height_mm,
            print_palette,
        )
        if self_intersection_warning["orca_preview_required"]:
            with guide_path.open("a", encoding="utf-8") as guide:
                guide.write(
                    "\n\n【微小自己交差の確認】\n"
                    "----------------------\n"
                    "閉立体・面向き・正体積・縮退面の必須検証は合格しています。\n"
                    f"検証上限内の自己交差: "
                    f"{self_intersection_warning['parts']}パーツ / "
                    f"{self_intersection_warning['faces']}面 / "
                    f"合計面積 {self_intersection_warning['area_mm2']:.6g} mm²\n"
                    f"判定: {self_intersection_warning['policy']}\n"
                    "Snapmaker Orcaで必ずプロジェクトとして開き、"
                    "スライスプレビューに欠落・異常な面・意図しない内部線が"
                    "ないことを確認してから印刷してください。\n"
                )
    if grouping.requires_separate_jobs and force_common_palette:
        with guide_path.open("a", encoding="utf-8") as guide:
            guide.write(
                "\nパーツ別基本色について\n"
                "----------------------\n"
                f"元の調整には {len(grouping.groups)} 種類の基本4色構成があります。\n"
                "U1の物理4スロット制約に合わせ、この印刷用3MFの色割当は"
                "全体共通4色へ統合しました。\n"
                "パーツ別構成そのものは Metadata/tripo_part_palettes.json "
                "へ保持しています。\n"
            )
    if part_model_paths:
        with guide_path.open("a", encoding="utf-8") as guide:
            guide.write(
                "\nパーツ別3MF\n"
                "-----------\n"
                f"{part_model_paths[0].parent.name} フォルダーへ "
                f"{len(part_model_paths)} ファイルを保存しました。\n"
                "各ファイルはそのパーツ用の基本4色を持つ独立した印刷ジョブです。\n"
            )

    emit(progress, "preview", 0.91, "比較プレビューを書き出しています")
    try:
        from PIL import Image, ImageDraw

        from .renderer import render_three_column_comparison

        if final_colors.manual_override_faces:
            # Paint edits belong to the final topology. Rendering that same
            # topology keeps the saved comparison image faithful to the 3MF.
            preview_level = prepared.final
            preview_colors = final_colors
        else:
            preview_level = prepared.preview
            preview_colors = recolor_level_parts(
                prepared.preview,
                settings.geometry.height_mm,
                settings.tone,
                settings.palette,
                effective_part_palettes,
            )
        reference: Path | Image.Image
        if reference_path:
            reference = reference_path
        else:
            reference = Image.new("RGB", (720, 900), (9, 10, 13))
            ImageDraw.Draw(reference).text(
                (reference.width // 2, reference.height // 2),
                "参照画像なし",
                fill=(220, 224, 232),
                anchor="mm",
            )
        image = render_three_column_comparison(
            reference,
            preview_level,
            preview_colors,
            panel_size=(480, 600),
        )
        image.save(preview_path)
    except Exception as exc:
        # The printable 3MF remains useful even on machines where OpenGL preview
        # creation is unavailable. Record this visibly instead of hiding it.
        report["preview_warning"] = str(exc)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig"
        )
        preview_path = Path("")

    emit(progress, "done", 1.0, "出力が完了しました")
    return ExportResult(
        model_path=None if individual_only else destination,
        preview_path=preview_path,
        report_path=report_path,
        guide_path=guide_path,
        fallback_obj_path=fallback_obj_path,
        validation=validation,
        part_model_paths=part_model_paths,
        individual_only=bool(individual_only),
    )
