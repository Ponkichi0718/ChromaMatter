from __future__ import annotations

import json
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from typing import Mapping, Sequence
from unittest import mock

import numpy as np

from spectrum_mapper import color_depth_3mf_input as input_module
from spectrum_mapper.color_depth_3mf_input import (
    ColorDepth3MFInputError,
    import_color_depth_3mf,
)


CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PRODUCTION_NS = (
    "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
)
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"

PHYSICAL = ("#080808", "#F5F3EE", "#D92B32", "#B8753D")
STATE_COLORS = PHYSICAL + ("#555555", "#6D2228")
STATE_PAIRS = {4: (1, 2), 5: (1, 3)}

TETRA_VERTICES = np.asarray(
    [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)
TETRA_FACES = np.asarray(
    [
        [0, 2, 1],
        [0, 1, 3],
        [1, 2, 3],
        [0, 3, 2],
    ],
    dtype=np.int32,
)
TETRA_LABELS = (0, 1, 4, 5)


def _content_types() -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="{CONTENT_TYPES_NS}">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="json" ContentType="application/json"/>
</Types>
'''.encode("utf-8")


def _relationships(target: str) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
 <Relationship Target="{target}" Id="rel-1" Type="{MODEL_REL}"/>
</Relationships>
'''.encode("utf-8")


def _palette_metadata() -> bytes:
    document = {
        "schema": "tripo-spectrum-mapper.palette.v1",
        "physical_slot_order": list(PHYSICAL),
        "palette_state_count": len(STATE_COLORS),
        "states": [
            {
                "state": index + 1,
                "name": f"state-{index + 1}",
                "display_rgb": color,
            }
            for index, color in enumerate(STATE_COLORS)
        ],
        # Ordering is semantic: row zero describes palette-state label 4
        # (human-facing state 5), row one describes label 5/state 6.
        "print_mix_specs": [
            {
                "physical_a": 1,
                "physical_b": 2,
                "ratio_b_percent": 33,
            },
            {
                "physical_a": 1,
                "physical_b": 3,
                "ratio_b_percent": 33,
            },
        ],
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def _basematerials_xml(resource_id: int = 2) -> str:
    rows = "\n".join(
        f'   <base name="state-{index + 1}" displaycolor="{color}"/>'
        for index, color in enumerate(STATE_COLORS)
    )
    return f'''  <basematerials id="{resource_id}">
{rows}
  </basematerials>'''


def _mesh_xml(
    vertices: np.ndarray = TETRA_VERTICES,
    faces: np.ndarray = TETRA_FACES,
    labels: Sequence[int] = TETRA_LABELS,
    *,
    material_id: int = 2,
    omit_pid: bool = False,
    split_corner_label: bool = False,
) -> str:
    vertex_xml = "\n".join(
        f'     <vertex x="{x:.17g}" y="{y:.17g}" z="{z:.17g}"/>'
        for x, y, z in np.asarray(vertices, dtype=np.float64)
    )
    triangles: list[str] = []
    for index, ((a, b, c), label) in enumerate(
        zip(np.asarray(faces, dtype=np.int64), labels, strict=True)
    ):
        pid = "" if omit_pid else f' pid="{material_id}"'
        extra = ""
        if split_corner_label and index == 0:
            extra = f' p2="{(int(label) + 1) % len(STATE_COLORS)}" p3="{label}"'
        triangles.append(
            f'     <triangle v1="{a}" v2="{b}" v3="{c}"'
            f'{pid} p1="{label}"{extra}/>'
        )
    return f'''   <mesh>
    <vertices>
{vertex_xml}
    </vertices>
    <triangles>
{chr(10).join(triangles)}
    </triangles>
   </mesh>'''


def _child_model(
    *,
    unit: str = "centimeter",
    vertices: np.ndarray = TETRA_VERTICES,
    faces: np.ndarray = TETRA_FACES,
    labels: Sequence[int] = TETRA_LABELS,
    omit_pid: bool = False,
    split_corner_label: bool = False,
) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="{unit}" xmlns="{CORE_NS}">
 <resources>
{_basematerials_xml()}
  <object id="7" name="one printable tetrahedron" type="model">
{_mesh_xml(vertices, faces, labels, omit_pid=omit_pid, split_corner_label=split_corner_label)}
  </object>
 </resources>
</model>
'''.encode("utf-8")


def _main_model(
    *,
    # Positive-determinant quarter turn plus translation.  This intentionally
    # does not commute with the build translation, so the success test proves
    # that component-before-build composition is implemented correctly.
    component_transform: str = "0 1 0 -1 0 0 0 0 1 1 2 3",
    build_transform: str = "1 0 0 0 1 0 0 0 1 10 20 30",
    second_component: bool = False,
    second_build_item: bool = False,
) -> bytes:
    components = [
        (
            '    <component p:path="/3D/Objects/part.model" '
            f'objectid="7" transform="{component_transform}"/>'
        )
    ]
    if second_component:
        components.append(
            '    <component p:path="/3D/Objects/part.model" objectid="7" '
            'transform="1 0 0 0 1 0 0 0 1 4 0 0"/>'
        )
    build_items = [
        f'  <item objectid="1" transform="{build_transform}" printable="1"/>'
    ]
    if second_build_item:
        build_items.append(
            '  <item objectid="1" '
            'transform="1 0 0 0 1 0 0 0 1 20 0 0" printable="1"/>'
        )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="centimeter" xmlns="{CORE_NS}" xmlns:p="{PRODUCTION_NS}" requiredextensions="p">
 <resources>
  <object id="1" name="print root" type="model">
   <components>
{chr(10).join(components)}
   </components>
  </object>
 </resources>
 <build>
{chr(10).join(build_items)}
 </build>
</model>
'''.encode("utf-8")


def _valid_members(
    *,
    main_model: bytes | None = None,
    child_model: bytes | None = None,
    palette: bytes | None = None,
) -> dict[str, bytes]:
    return {
        "[Content_Types].xml": _content_types(),
        "_rels/.rels": _relationships("/3D/3dmodel.model"),
        "3D/3dmodel.model": main_model or _main_model(),
        "3D/_rels/3dmodel.model.rels": _relationships(
            "/3D/Objects/part.model"
        ),
        "3D/Objects/part.model": child_model or _child_model(),
        "Metadata/full_spectrum_palette.json": palette or _palette_metadata(),
    }


def _inline_members(main_model: bytes) -> dict[str, bytes]:
    return {
        "[Content_Types].xml": _content_types(),
        "_rels/.rels": _relationships("/3D/3dmodel.model"),
        "3D/3dmodel.model": main_model,
        "Metadata/full_spectrum_palette.json": _palette_metadata(),
    }


def _write_archive(
    path: Path,
    members: Mapping[str, bytes],
    *,
    extra_members: Sequence[tuple[str, bytes]] = (),
) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
            for name, payload in extra_members:
                archive.writestr(name, payload)
    return path


def _mark_archive_encrypted(path: Path) -> None:
    """Set ZIP encryption bits without needing an encryption-capable writer."""

    data = bytearray(path.read_bytes())
    patched = 0
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while True:
            offset = data.find(signature, start)
            if offset < 0:
                break
            flags = struct.unpack_from("<H", data, offset + flag_offset)[0]
            struct.pack_into("<H", data, offset + flag_offset, flags | 0x1)
            patched += 1
            start = offset + 4
    if not patched:
        raise AssertionError("test ZIP did not contain a patchable header")
    path.write_bytes(data)


def _replace_raw_member_name(path: Path, old: bytes, new: bytes) -> None:
    """Mutate same-length local/central names that ZipFile normalises."""

    if len(old) != len(new):
        raise ValueError("raw ZIP member-name replacement must preserve length")
    data = path.read_bytes()
    replaced = data.count(old)
    if replaced != 2:
        raise AssertionError(
            f"expected local and central member names, found {replaced}"
        )
    path.write_bytes(data.replace(old, new))


def _palette_with(mutator: object) -> bytes:
    document = json.loads(_palette_metadata())
    if not callable(mutator):
        raise TypeError("mutator must be callable")
    mutator(document)
    return json.dumps(document).encode("utf-8")


def _inline_component_model(*, depth: int, cycle: bool = False) -> bytes:
    if depth < 2:
        raise ValueError("depth must be at least two")
    objects: list[str] = []
    for object_id in range(1, depth):
        target = 1 if cycle and object_id == depth - 1 else object_id + 1
        objects.append(
            f'''  <object id="{object_id}" type="model">
   <components><component objectid="{target}"/></components>
  </object>'''
        )
    if not cycle:
        objects.append(
            f'''  <object id="{depth}" type="model">
{_mesh_xml(material_id=1000)}
  </object>'''
        )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="{CORE_NS}">
 <resources>
{_basematerials_xml(1000)}
{chr(10).join(objects)}
 </resources>
 <build><item objectid="1" printable="1"/></build>
</model>
'''.encode("utf-8")


class ColorDepth3MFInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _archive(
        self,
        name: str = "probe.3mf",
        *,
        members: Mapping[str, bytes] | None = None,
        extra_members: Sequence[tuple[str, bytes]] = (),
    ) -> Path:
        return _write_archive(
            self.directory / name,
            members or _valid_members(),
            extra_members=extra_members,
        )

    def _assert_rejected(
        self,
        path: Path,
        code: str,
        **kwargs: object,
    ) -> ColorDepth3MFInputError:
        with self.assertRaises(ColorDepth3MFInputError) as caught:
            import_color_depth_3mf(path, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertIsInstance(caught.exception.details, dict)
        return caught.exception

    def test_import_resolves_relationship_component_build_transform_and_unit(self) -> None:
        imported = import_color_depth_3mf(
            self._archive(),
            expected_physical_slot_order=PHYSICAL,
            expected_state_pairs=STATE_PAIRS,
        )

        self.assertEqual(imported.physical_slot_order, PHYSICAL)
        self.assertEqual(imported.print_mix_specs, ((1, 2), (1, 3)))
        np.testing.assert_array_equal(imported.face_target_labels, TETRA_LABELS)
        self.assertEqual(imported.vertices_mm.shape, (4, 3))
        self.assertEqual(imported.faces.shape, (4, 3))
        # Both model documents use centimetres.  The component's quarter turn
        # and (1,2,3) translation are applied before the build's (10,20,30)
        # translation.  Import then canonicalises the resolved millimetre mesh
        # to XY bbox centre zero and minimum Z zero; the writer owns its later
        # +128 mm plate placement and must not inherit the build translation.
        np.testing.assert_allclose(
            np.min(imported.vertices_mm, axis=0),
            [-5.0, -5.0, 0.0],
            rtol=0.0,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            np.max(imported.vertices_mm, axis=0),
            [5.0, 5.0, 10.0],
            rtol=0.0,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            imported.vertices_mm,
            [
                [5.0, -5.0, 0.0],
                [5.0, 5.0, 0.0],
                [-5.0, -5.0, 0.0],
                [5.0, -5.0, 10.0],
            ],
            rtol=0.0,
            atol=1e-12,
        )
        transform = imported.metadata["transform"]
        self.assertEqual(transform["unit_scale_to_mm"], 10.0)
        self.assertGreater(transform["determinant"], 0.0)
        self.assertEqual(np.asarray(transform["composed_3mf_matrix"]).shape, (4, 4))
        canonicalization = imported.metadata["canonicalization"]
        self.assertEqual(
            canonicalization["policy"],
            "xy-bbox-center-and-min-z",
        )
        np.testing.assert_allclose(
            canonicalization["xy_center_mm"],
            [105.0, 225.0],
            rtol=0.0,
            atol=1e-12,
        )
        self.assertEqual(canonicalization["min_z_mm"], 330.0)
        np.testing.assert_allclose(
            canonicalization["translation_mm"],
            [-105.0, -225.0, -330.0],
            rtol=0.0,
            atol=1e-12,
        )

    def test_pure_build_translation_is_removed_by_canonicalization(self) -> None:
        identity = "1 0 0 0 1 0 0 0 1 0 0 0"
        untranslated = import_color_depth_3mf(
            self._archive(
                "local.3mf",
                members=_valid_members(
                    main_model=_main_model(
                        component_transform=identity,
                        build_transform=identity,
                    )
                ),
            )
        )
        translated = import_color_depth_3mf(
            self._archive(
                "translated.3mf",
                members=_valid_members(
                    main_model=_main_model(component_transform=identity)
                ),
            )
        )

        np.testing.assert_allclose(
            translated.vertices_mm,
            untranslated.vertices_mm,
            rtol=0.0,
            atol=1e-12,
        )
        np.testing.assert_array_equal(translated.faces, untranslated.faces)
        np.testing.assert_array_equal(
            translated.face_target_labels,
            untranslated.face_target_labels,
        )

    def test_archive_preflight_rejects_duplicate_and_unsafe_members(self) -> None:
        duplicate = self._archive(
            "duplicate.3mf",
            extra_members=[("3D/3dmodel.model", _main_model())],
        )
        self._assert_rejected(duplicate, "archive_duplicate_member")

        for index, unsafe_name in enumerate(
            ("../outside.xml", "/absolute.xml", "C:/drive.xml")
        ):
            with self.subTest(name=unsafe_name):
                path = self._archive(
                    f"unsafe-{index}.3mf",
                    extra_members=[(unsafe_name, b"not referenced")],
                )
                self._assert_rejected(path, "archive_member_path_unsafe")

        # ZipFile deliberately maps backslashes to forward slashes on Windows;
        # patch the same-length raw names to exercise an actually hostile ZIP.
        backslash = self._archive(
            "unsafe-backslash.3mf",
            extra_members=[("3D/backslash.xml", b"not referenced")],
        )
        _replace_raw_member_name(
            backslash,
            b"3D/backslash.xml",
            b"3D\\backslash.xml",
        )
        self._assert_rejected(backslash, "archive_member_path_unsafe")

    def test_archive_preflight_rejects_encrypted_member_flag(self) -> None:
        path = self._archive("encrypted-flag.3mf")
        _mark_archive_encrypted(path)
        self._assert_rejected(path, "archive_encrypted_member")

    def test_archive_preflight_rejects_member_count_limit(self) -> None:
        # Unreferenced payloads count too: they must not bypass the
        # archive-wide resource budget.
        extras = [(f"Metadata/padding-{index:04d}.txt", b"") for index in range(3)]
        path = self._archive("too-many-members.3mf", extra_members=extras)
        with mock.patch.object(input_module, "_MAX_ARCHIVE_MEMBERS", 8):
            self._assert_rejected(path, "archive_member_count_exceeded")

    def test_archive_preflight_rejects_declared_member_and_total_sizes(self) -> None:
        member = self._archive("oversized-member.3mf")
        with mock.patch.object(
            input_module,
            "_MAX_MEMBER_UNCOMPRESSED_BYTES",
            32,
        ):
            self._assert_rejected(member, "archive_member_size_exceeded")

        total = self._archive("oversized-total.3mf")
        with (
            mock.patch.object(
                input_module,
                "_MAX_MEMBER_UNCOMPRESSED_BYTES",
                10_000_000,
            ),
            mock.patch.object(
                input_module,
                "_MAX_TOTAL_UNCOMPRESSED_BYTES",
                64,
            ),
        ):
            self._assert_rejected(total, "archive_total_size_exceeded")

    def test_archive_preflight_rejects_compression_ratio_bomb(self) -> None:
        members = _valid_members()
        members["Metadata/highly-compressible.bin"] = b"0" * 8192
        path = self.directory / "compression-bomb.3mf"
        with zipfile.ZipFile(
            path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        with mock.patch.object(input_module, "_MAX_COMPRESSION_RATIO", 2.0):
            self._assert_rejected(path, "archive_compression_ratio_exceeded")

    def test_archive_preflight_rejects_normalized_and_case_collisions(self) -> None:
        collisions = (
            "3D/%33dmodel.model",
            "3d/3dmodel.model",
        )
        for index, name in enumerate(collisions):
            with self.subTest(name=name):
                path = self._archive(
                    f"member-collision-{index}.3mf",
                    extra_members=[(name, _main_model())],
                )
                self._assert_rejected(path, "archive_member_collision")

    def test_xml_dtd_and_entity_are_rejected_before_expansion(self) -> None:
        model = _main_model().decode("utf-8").replace(
            '<model unit="centimeter"',
            '<!DOCTYPE model [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>\n'
            '<model unit="centimeter"',
            1,
        ).replace('name="print root"', 'name="&xxe;"', 1)
        path = self._archive(
            "entity.3mf",
            members=_valid_members(main_model=model.encode("utf-8")),
        )
        self._assert_rejected(path, "xml_forbidden_construct")

    def test_root_model_relationship_is_internal_unique_and_required(self) -> None:
        missing_members = _valid_members()
        del missing_members["_rels/.rels"]
        missing = self._archive("missing-root-rel.3mf", members=missing_members)
        self._assert_rejected(missing, "model_relationship_missing")

        external_rel = f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
 <Relationship Target="https://example.invalid/model" TargetMode="External"
  Id="rel-1" Type="{MODEL_REL}"/>
</Relationships>
'''.encode("utf-8")
        external = self._archive(
            "external-root-rel.3mf",
            members={**_valid_members(), "_rels/.rels": external_rel},
        )
        self._assert_rejected(external, "relationship_external_target")

    def test_unknown_relationship_target_mode_is_rejected(self) -> None:
        unknown_mode_rel = f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
 <Relationship Target="/3D/3dmodel.model" TargetMode="Remote"
  Id="rel-1" Type="{MODEL_REL}"/>
</Relationships>
'''.encode("utf-8")
        unknown_mode = self._archive(
            "unknown-target-mode.3mf",
            members={**_valid_members(), "_rels/.rels": unknown_mode_rel},
        )
        self._assert_rejected(
            unknown_mode,
            "relationship_target_mode_invalid",
        )

    def test_multiple_root_model_relationships_are_rejected(self) -> None:
        multiple_rel = f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="{MODEL_REL}"/>
 <Relationship Target="/3D/Objects/part.model" Id="rel-2" Type="{MODEL_REL}"/>
</Relationships>
'''.encode("utf-8")
        multiple = self._archive(
            "multiple-root-rel.3mf",
            members={**_valid_members(), "_rels/.rels": multiple_rel},
        )
        self._assert_rejected(
            multiple,
            "model_relationship_count_invalid",
        )

    def test_source_archive_change_during_read_is_rejected(self) -> None:
        path = self._archive("changed-during-read.3mf")
        initial = "A" * 64
        final = "B" * 64
        with mock.patch.object(
            input_module,
            "_sha256_file",
            side_effect=(initial, final),
        ) as digest:
            error = self._assert_rejected(
                path,
                "source_archive_changed_during_read",
            )

        self.assertEqual(digest.call_count, 2)
        self.assertEqual(error.details["initial_sha256"], initial)
        self.assertEqual(error.details["final_sha256"], final)

    def test_component_cycle_and_excessive_depth_are_rejected(self) -> None:
        cycle = self._archive(
            "cycle.3mf",
            members=_inline_members(_inline_component_model(depth=3, cycle=True)),
        )
        self._assert_rejected(cycle, "component_cycle")

        deep = self._archive(
            "deep.3mf",
            members=_inline_members(_inline_component_model(depth=70)),
        )
        self._assert_rejected(deep, "component_depth_exceeded")

    def test_transform_parser_fails_closed(self) -> None:
        cases = (
            ("1 0 0", "transform_invalid"),
            ("1 0 0 0 1 0 0 0 nan 0 0 0", "transform_nonfinite"),
            ("0 0 0 0 1 0 0 0 1 0 0 0", "transform_singular"),
            ("-1 0 0 0 1 0 0 0 1 0 0 0", "transform_reflection"),
        )
        for index, (transform, code) in enumerate(cases):
            with self.subTest(transform=transform):
                path = self._archive(
                    f"transform-{index}.3mf",
                    members=_valid_members(
                        main_model=_main_model(component_transform=transform)
                    ),
                )
                self._assert_rejected(path, code)

    def test_exactly_one_printable_instance_and_mesh_are_required(self) -> None:
        instances = self._archive(
            "two-instances.3mf",
            members=_valid_members(main_model=_main_model(second_build_item=True)),
        )
        self._assert_rejected(instances, "printable_instance_count_invalid")

        meshes = self._archive(
            "two-meshes.3mf",
            members=_valid_members(main_model=_main_model(second_component=True)),
        )
        self._assert_rejected(meshes, "printable_mesh_count_invalid")

    def test_triangle_material_binding_and_label_bounds_are_strict(self) -> None:
        missing = self._archive(
            "missing-pid.3mf",
            members=_valid_members(child_model=_child_model(omit_pid=True)),
        )
        self._assert_rejected(missing, "triangle_material_missing")

        labels = list(TETRA_LABELS)
        labels[0] = len(STATE_COLORS)
        out_of_bounds = self._archive(
            "label-bounds.3mf",
            members=_valid_members(child_model=_child_model(labels=labels)),
        )
        self._assert_rejected(out_of_bounds, "material_index_out_of_bounds")

        split = self._archive(
            "split-corner-label.3mf",
            members=_valid_members(
                child_model=_child_model(split_corner_label=True)
            ),
        )
        self._assert_rejected(split, "triangle_mixed_material_not_supported")

    def test_equal_p1_p2_p3_corner_labels_are_one_face_target(self) -> None:
        child = _child_model().decode("utf-8").replace(
            'pid="2" p1="0"',
            'pid="2" p1="0" p2="0" p3="0"',
            1,
        )
        imported = import_color_depth_3mf(
            self._archive(
                "equal-corner-labels.3mf",
                members=_valid_members(child_model=child.encode("utf-8")),
            )
        )
        np.testing.assert_array_equal(imported.face_target_labels, TETRA_LABELS)

    def test_embedded_palette_identity_must_match_expected_job(self) -> None:
        path = self._archive("palette-identity.3mf")
        self._assert_rejected(
            path,
            "physical_slot_order_mismatch",
            expected_physical_slot_order=(
                "#000000",
                PHYSICAL[1],
                PHYSICAL[2],
                PHYSICAL[3],
            ),
        )
        self._assert_rejected(
            path,
            "palette_state_pair_mismatch",
            expected_state_pairs={4: (1, 3), 5: (1, 3)},
        )

    def test_palette_metadata_is_required_and_internally_consistent(self) -> None:
        missing_members = _valid_members()
        del missing_members["Metadata/full_spectrum_palette.json"]
        missing = self._archive("missing-palette.3mf", members=missing_members)
        missing_error = self._assert_rejected(
            missing,
            "archive_required_member_missing",
        )
        self.assertEqual(
            missing_error.details["member"],
            "Metadata/full_spectrum_palette.json",
        )

        state_count = self._archive(
            "state-count.3mf",
            members=_valid_members(
                palette=_palette_with(
                    lambda value: value.__setitem__("palette_state_count", 7)
                )
            ),
        )
        self._assert_rejected(state_count, "palette_state_table_invalid")

        short_specs = self._archive(
            "short-print-specs.3mf",
            members=_valid_members(
                palette=_palette_with(
                    lambda value: value["print_mix_specs"].pop()
                )
            ),
        )
        self._assert_rejected(short_specs, "palette_mix_table_invalid")

        def set_bad_physical_slot(value: dict[str, object]) -> None:
            specs = value["print_mix_specs"]
            assert isinstance(specs, list)
            assert isinstance(specs[0], dict)
            specs[0]["physical_b"] = 5

        bad_slot = self._archive(
            "print-spec-slot.3mf",
            members=_valid_members(
                palette=_palette_with(set_bad_physical_slot)
            ),
        )
        self._assert_rejected(
            bad_slot,
            "palette_mix_table_invalid",
        )

    def test_vertex_triangle_numbers_and_indices_fail_closed(self) -> None:
        nonfinite_vertices = TETRA_VERTICES.copy()
        nonfinite_vertices[0, 0] = np.nan
        nonfinite = self._archive(
            "nonfinite-vertex.3mf",
            members=_valid_members(
                child_model=_child_model(vertices=nonfinite_vertices)
            ),
        )
        self._assert_rejected(nonfinite, "mesh_vertex_nonfinite")

        degenerate_faces = TETRA_FACES.copy()
        degenerate_faces[0] = [0, 0, 1]
        degenerate = self._archive(
            "degenerate-triangle.3mf",
            members=_valid_members(
                child_model=_child_model(faces=degenerate_faces)
            ),
        )
        self._assert_rejected(degenerate, "mesh_triangle_degenerate")

        invalid_faces = TETRA_FACES.copy()
        invalid_faces[0, 2] = len(TETRA_VERTICES)
        invalid_index = self._archive(
            "triangle-index.3mf",
            members=_valid_members(
                child_model=_child_model(faces=invalid_faces)
            ),
        )
        self._assert_rejected(
            invalid_index,
            "mesh_triangle_index_out_of_bounds",
        )

    def test_nonwatertight_mesh_is_rejected(self) -> None:
        path = self._archive(
            "open.3mf",
            members=_valid_members(
                child_model=_child_model(
                    faces=TETRA_FACES[:-1],
                    labels=TETRA_LABELS[:-1],
                )
            ),
        )
        self._assert_rejected(path, "mesh_not_watertight")

    def test_inconsistently_oriented_mesh_is_rejected(self) -> None:
        faces = TETRA_FACES.copy()
        faces[0] = faces[0, ::-1]
        path = self._archive(
            "winding.3mf",
            members=_valid_members(child_model=_child_model(faces=faces)),
        )
        self._assert_rejected(path, "mesh_not_oriented")

    def test_negative_signed_volume_is_rejected_without_auto_repair(self) -> None:
        faces = TETRA_FACES[:, ::-1]
        path = self._archive(
            "negative-volume.3mf",
            members=_valid_members(child_model=_child_model(faces=faces)),
        )
        self._assert_rejected(path, "mesh_volume_nonpositive")

    def test_disconnected_closed_bodies_in_one_mesh_are_rejected(self) -> None:
        vertices = np.vstack(
            (TETRA_VERTICES, TETRA_VERTICES + np.asarray([3.0, 0.0, 0.0]))
        )
        faces = np.vstack((TETRA_FACES, TETRA_FACES + 4))
        labels = TETRA_LABELS + TETRA_LABELS
        path = self._archive(
            "two-bodies.3mf",
            members=_valid_members(
                child_model=_child_model(vertices=vertices, faces=faces, labels=labels)
            ),
        )
        self._assert_rejected(path, "mesh_body_count_invalid")


if __name__ == "__main__":
    unittest.main()
