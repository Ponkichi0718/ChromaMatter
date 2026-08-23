from __future__ import annotations

import json
import locale
import os
from pathlib import Path
from typing import Any, Iterable


DEFAULT_LANGUAGE = "ja"
SUPPORTED_LANGUAGES = ("ja", "en")
LANGUAGE_DISPLAY_NAMES = {
    "ja": "日本語",
    "en": "English",
}


# Keep UI copy in one place.  Keys are deliberately grouped by feature so a
# future tab (for example freehand part separation) can be translated without
# coupling geometry code to Tk or to a particular language.
CATALOG: dict[str, dict[str, str]] = {
    # Application shell
    "language.label": {"ja": "言語", "en": "Language"},
    # Compatibility key: the command now accepts either supported model type.
    "toolbar.open_obj": {"ja": "OBJ / GLBを開く", "en": "Open OBJ / GLB"},
    "toolbar.open_reference": {"ja": "元画像を開く", "en": "Open Reference"},
    "toolbar.save_project": {"ja": "プロジェクト保存", "en": "Save Project"},
    "toolbar.load_project": {"ja": "プロジェクト読込", "en": "Load Project"},
    "toolbar.open_paint": {"ja": "マニュアル修正", "en": "Manual Editing"},
    "toolbar.help": {"ja": "使い方", "en": "Help"},
    "toolbar.licenses": {"ja": "ライセンス", "en": "Licenses"},
    # Show the other language beside the selector so the switch is obvious to
    # someone who cannot yet read the current interface language.
    "toolbar.language_opposite": {"ja": "Language", "en": "言語"},
    "toolbar.launch_orca": {"ja": "Snapmaker Orca起動", "en": "Launch Snapmaker Orca"},
    "toolbar.export_3mf": {"ja": "3MFを書き出す", "en": "Export 3MF"},
    # This compact notice is always reachable from the public toolbar.  Exact
    # release URLs and local document locations are supplied by legal_notice.py.
    "legal_notice.title": {
        "ja": "ライセンスとソース",
        "en": "Licenses & Source",
    },
    "legal_notice.application": {
        "ja": "ChromaMatter本体は{license}で提供される自由ソフトウェアです。",
        "en": "The ChromaMatter application is free software provided under {license}.",
    },
    "legal_notice.no_warranty": {
        "ja": "本ソフトウェアは無保証です。商品性・特定目的への適合性を含む、いかなる保証もありません。",
        "en": "This software comes with NO WARRANTY, including no implied warranty of merchantability or fitness for a particular purpose.",
    },
    "legal_notice.rights": {
        "ja": "適用されるライセンス条件に従い、対象となるソフトウェアを再配布・改変できます。",
        "en": "You may redistribute and modify covered software under the terms of its applicable licence.",
    },
    "legal_notice.third_party": {
        "ja": "Windows配布物にはTetGen（{tetgen_license}）などの第三者ソフトウェアが含まれます。各構成要素にはそれぞれのライセンスが適用されます。",
        "en": "The Windows distribution includes third-party software such as TetGen ({tetgen_license}). Each component remains governed by its own licence.",
    },
    "legal_notice.source_heading": {
        "ja": "ライセンス原文・対応ソース・ビルド情報",
        "en": "Licence texts, corresponding source, and build information",
    },
    "legal_notice.source_url": {
        "ja": "公開ソース／リリース資料: {source_url}",
        "en": "Public source and release materials: {source_url}",
    },
    "legal_notice.local_documents": {
        "ja": "この配布物内のライセンス／ソース案内: {locations}",
        "en": "Licence and source notices in this distribution: {locations}",
    },
    "legal_notice.governing_terms": {
        "ja": "この概要ではなく、配布物に同梱された各ライセンス原文とソース案内が適用条件を定めます。",
        "en": "The full licence texts and source notices supplied with the distribution, rather than this summary, govern their respective components.",
    },
    "legal_notice.close": {"ja": "閉じる", "en": "Close"},
    # Compact, task-oriented help.  Each topic deliberately stays at four
    # short steps so the Help Center remains useful beside the working UI.
    "help_center.title": {"ja": "使い方・ヘルプ", "en": "Help Center"},
    "help_center.navigation": {"ja": "項目", "en": "Topics"},
    "help_center.steps": {"ja": "手順", "en": "Steps"},
    "help_center.close": {"ja": "閉じる", "en": "Close"},
    "help_center.action.open_obj": {"ja": "OBJ / GLBを開く", "en": "Open OBJ / GLB"},
    "help_center.action.select_filament": {
        "ja": "フィラメント設定へ",
        "en": "Go to Filament Settings",
    },
    "help_center.action.open_manual": {
        "ja": "マニュアル修正を開く",
        "en": "Open Manual Editing",
    },
    "help_center.action.export": {"ja": "3MFを書き出す", "en": "Export 3MF"},
    "help_center.topic.first_steps.title": {
        "ja": "まずはここから",
        "en": "First Steps",
    },
    "help_center.topic.first_steps.step1": {
        "ja": "OBJまたはGLBを開き、形状の処理が終わるまで待ちます。",
        "en": "Open an OBJ or GLB and wait for geometry processing to finish.",
    },
    "help_center.topic.first_steps.step2": {
        "ja": "パーツと、実際に使う基本4色を確認します。",
        "en": "Check the parts and the four base filaments you will use.",
    },
    "help_center.topic.first_steps.step3": {
        "ja": "自動変換を確認し、必要な所だけマニュアル修正します。",
        "en": "Review automatic mapping, then manually fix only what needs it.",
    },
    "help_center.topic.first_steps.step4": {
        "ja": "3MFを書き出し、Orcaで全レイヤーを確認します。",
        "en": "Export the 3MF and inspect every layer in Orca.",
    },
    "help_center.topic.parts_palette.title": {
        "ja": "パーツと基本4色",
        "en": "Parts & Four Base Colors",
    },
    "help_center.topic.parts_palette.step1": {
        "ja": "［全体共通］または編集するパーツを選びます。",
        "en": "Choose Common to All or the part you want to edit.",
    },
    "help_center.topic.parts_palette.step2": {
        "ja": "F1～F4を実物のフィラメント色に合わせます。",
        "en": "Match F1-F4 to your physical filament colors.",
    },
    "help_center.topic.parts_palette.step3": {
        "ja": "迷った場合は自動提案から始められます。",
        "en": "If unsure, start with an automatic recommendation.",
    },
    "help_center.topic.parts_palette.step4": {
        "ja": "U1へ同時に装填できる物理色は4本です。",
        "en": "The U1 can hold four physical filaments at once.",
    },
    "help_center.topic.auto_mapping.title": {
        "ja": "自動変換と黒なしグラデーション",
        "en": "Automatic Mapping & Black-Free Gradient",
    },
    "help_center.topic.auto_mapping.step1": {
        "ja": "自動変換は元の色を選択中の印刷色へ近づけます。",
        "en": "Automatic mapping matches source colors to the selected print colors.",
    },
    "help_center.topic.auto_mapping.step2": {
        "ja": "黒なしモードは、自動割当の黒混色だけを赤～茶へ置き換えます。",
        "en": "Black-Free mode remaps only automatically assigned black mixes toward red and brown.",
    },
    "help_center.topic.auto_mapping.step3": {
        "ja": "純黒と手塗りした色は変更しません。",
        "en": "Pure black and manually painted colors stay unchanged.",
    },
    "help_center.topic.auto_mapping.step4": {
        "ja": "プレビュー後、実機の小さな試し刷りで確認してください。",
        "en": "After previewing, verify the result with a small physical test print.",
    },
    "help_center.topic.manual_editing.title": {
        "ja": "マニュアル修正",
        "en": "Manual Editing",
    },
    "help_center.topic.manual_editing.step1": {
        "ja": "モデルの処理後に［マニュアル修正］を開きます。",
        "en": "Open Manual Editing after the model has been processed.",
    },
    "help_center.topic.manual_editing.step2": {
        "ja": "パーツと印刷色を選び、ブラシまたはエアブラシで塗ります。対応ペンは筆圧で線幅が変わります。",
        "en": "Choose a part and print color, then use Brush or Airbrush. Supported pens vary line width with pressure.",
    },
    "help_center.topic.manual_editing.step3": {
        "ja": "3Dスポイトで現在の色を取り、なじませで境界をぼかせます。折り目表示を使うと面の境界を確認できます。",
        "en": "Use the 3D Eyedropper to pick the current paint and Smudge to soften boundaries. Crease Overlay reveals folded edges.",
    },
    "help_center.topic.manual_editing.step4_guard": {
        "ja": "［局所ツールを折り目で止める］はB/A/M/S/Eに適用します。塗りつぶしFは同色の連結域を塗ります。",
        "en": "Stop Local Tools at Creases applies to B/A/M/S/E. Fill F paints the connected area of the same color.",
    },
    "help_center.topic.manual_editing.step4": {
        "ja": "［修正を保持して閉じる］でメイン画面へ戻ります。",
        "en": "Choose Keep Corrections and Close to return to the main window.",
    },
    "help_center.topic.export_3mf.title": {
        "ja": "3MF出力",
        "en": "Export 3MF",
    },
    "help_center.topic.export_3mf.step1": {
        "ja": "右下の［3MFを書き出す］を選びます。",
        "en": "Choose Export 3MF at the lower right.",
    },
    "help_center.topic.export_3mf.step2": {
        "ja": "安全に出力できない形状は、理由と確認先を表示します。",
        "en": "If safe export is not possible, the app shows why and where to check.",
    },
    "help_center.topic.export_3mf.step3": {
        "ja": "Orcaでは3MFをプロジェクトとして開きます。",
        "en": "Open the 3MF as a project in Orca.",
    },
    "help_center.topic.export_3mf.step4": {
        "ja": "色、パーツ、サポートを全レイヤーで確認します。",
        "en": "Inspect colors, parts, and supports across every layer.",
    },
    "help_center.topic.troubleshooting.title": {
        "ja": "困ったとき",
        "en": "Troubleshooting",
    },
    "help_center.topic.troubleshooting.step1": {
        "ja": "キャンセルやエラーでも、入力と設定はできるだけ保持されます。",
        "en": "Cancelling or encountering an error keeps inputs and settings whenever possible.",
    },
    "help_center.topic.troubleshooting.step2": {
        "ja": "まず安全設定と形状診断の表示を確認します。",
        "en": "Check the safety settings and geometry diagnostics first.",
    },
    "help_center.topic.troubleshooting.step3": {
        "ja": "エラー画面の詳細は、停止理由の確認や共有に使えます。",
        "en": "Error details can be used to review or share why processing stopped.",
    },
    "help_center.topic.troubleshooting.step4": {
        "ja": "不明なまま設定を弱めず、元モデルと表示内容を保存してください。",
        "en": "Do not weaken checks blindly; keep the source model and the displayed details.",
    },
    "tab.parts": {"ja": "パーツ", "en": "Parts"},
    "tab.palette": {"ja": "色・スポイト", "en": "Color & Eyedropper"},
    "tab.tone": {"ja": "陰影調整", "en": "Shading"},
    "tab.geometry": {"ja": "形状", "en": "Geometry"},
    "tab.assembly": {"ja": "パーツ処理", "en": "Part Processing"},
    "main.ribbon_filament": {
        "ja": "フィラメント設定",
        "en": "Filament Settings",
    },
    "main.ribbon_output": {"ja": "出力設定", "en": "Output Settings"},
    "main.ribbon_expand": {"ja": "リボンを展開", "en": "Expand Ribbon"},
    "main.ribbon_collapse": {"ja": "リボンを収納", "en": "Collapse Ribbon"},
    "main.group_parts": {
        "ja": "パーツ別設定・自動提案",
        "en": "Per-part Setup & Recommendations",
    },
    "main.group_geometry": {
        "ja": "サイズ・メッシュ",
        "en": "Size & Mesh",
    },
    "main.group_assembly": {
        "ja": "パーツ・造形準備",
        "en": "Parts & Print Preparation",
    },
    "main.filament_job_help": {
        "ja": "印刷時のフィラメント構成について",
        "en": "About Filament Sets for Printing",
    },
    "main.select_part_to_rename": {
        "ja": "先に［編集対象］からパーツを選択してください。",
        "en": "Select a part under Edit Target first.",
    },
    "main.active_outline_help": {
        "ja": "水色の輪郭 = フィラメント設定の編集対象パーツ",
        "en": "Cyan outline = part selected in Filament Settings",
    },
    "main.recipe_show": {
        "ja": "混色候補を表示",
        "en": "Show Mix Candidates",
    },
    "main.recipe_hide": {
        "ja": "混色候補を収納",
        "en": "Hide Mix Candidates",
    },
    # Parts
    "parts.intro": {
        "ja": "モデルの元のパーツ構成と配置は変えず、選択した印刷パーツだけ別の基本4色にできます。",
        "en": "Keep the model's original part layout while assigning a different set of four base filaments to a selected print part.",
    },
    "parts.column.part": {"ja": "パーツ", "en": "Part"},
    "parts.column.faces": {"ja": "面数", "en": "Faces"},
    "parts.column.settings": {"ja": "設定", "en": "Setup"},
    "parts.column.filaments": {"ja": "基本4色", "en": "4 Base Colors"},
    "parts.edit_target": {"ja": "編集対象", "en": "Edit Target"},
    "parts.common": {"ja": "全体共通", "en": "Common to All"},
    "parts.recommend_selected": {"ja": "選択パーツを自動提案", "en": "Recommend for Selected Part"},
    "parts.recommend_all": {"ja": "全パーツを自動提案", "en": "Recommend for All Parts"},
    "parts.copy_all": {"ja": "現在の4色を全パーツへコピー", "en": "Copy Current 4 Colors to All Parts"},
    "parts.reset_selected": {"ja": "選択パーツを全体共通設定へ戻す", "en": "Reset Selected Part to Common Setup"},
    "parts.u1_warning": {
        "ja": "重要: U1へ同時装填できる物理フィラメントは4本です。パーツ間で基本4色が異なる場合は、編集用設定として保持し、1回印刷では共通4色への統合が必要です。",
        "en": "Important: U1 can hold four physical filaments at once. Different four-color sets can be retained for editing, but a single print requires one common set of four.",
    },
    # Palette and eyedropper
    "palette.eyedropper_group": {"ja": "元画像スポイト", "en": "Reference Eyedropper"},
    "palette.eyedropper_start": {
        "ja": "混色候補用スポイト",
        "en": "Sample for Mix Recipes",
    },
    "palette.eyedropper_stop": {"ja": "スポイト終了", "en": "Stop Eyedropper"},
    "palette.eyedropper_hint": {
        "ja": "元画像をクリックして混色候補を表示",
        "en": "Click the reference image to show mix recipes",
    },
    "palette.base_group": {"ja": "基本フィラメント4色", "en": "Four Base Filaments"},
    "palette.material_pla": {"ja": "PLAで混色", "en": "Mix with PLA"},
    "palette.material_abs": {"ja": "ABSで混色 β", "en": "Mix with ABS β"},
    "palette.material_petg": {"ja": "PETGで混色 β", "en": "Mix with PETG β"},
    "palette.material_change_title": {
        "ja": "混色素材を変更",
        "en": "Change Mixing Material",
    },
    "palette.material_change_confirm": {
        "ja": "{old}から{new}へ変更します。異素材の製品情報は引き継がず、{new}だけで基本4色を再提案します。色番号と手修正{painted}面は保持されますが、実際の色は変わります。続けますか？",
        "en": "Change from {old} to {new}. Product identities from the other material will not be reused; all four base colors will be proposed from {new} only. Color IDs and {painted} manually painted faces remain, but their physical colors change. Continue?",
    },
    "palette.material_beta_title": {
        "ja": "素材別混色 β",
        "en": "Material Mixing Beta",
    },
    "palette.abs_warning_title": {
        "ja": "ABS混色 β の注意",
        "en": "ABS Mixing Beta Notice",
    },
    "palette.abs_warning": {
        "ja": "ABSはPLAより登録色・実測色・色域が少ないため、目的色が無い場合はABS内の近似になります。PLA/PETGでは補完しません。必ず実機比較チャートで確認してください。Snapmaker U1でABSを印刷する場合はTop Coverを前提にしてください。",
        "en": "ABS has fewer cataloged and measured colors and a smaller gamut than PLA. Missing target colors are approximated using ABS only; PLA/PETG are never used as fallback. Generate and print the physical comparison chart first. Use a Top Cover when printing ABS on Snapmaker U1.",
    },
    "palette.petg_warning": {
        "ja": "PETG混色はβ機能です。PETGだけで4色を構成し、PLA/ABSは混ぜません。実フィラメントで色味が変わるため、実機比較チャートで確認してください。",
        "en": "PETG mixing is beta. All four spools use PETG; PLA/ABS are not mixed in. Physical filament appearance varies, so verify with the physical comparison chart.",
    },
    "palette.material_mismatch_title": {
        "ja": "異素材は設定できません",
        "en": "Cross-material Selection Blocked",
    },
    "palette.material_mismatch": {
        "ja": "現在は{palette}で混色する設定です。{product}フィラメントは同じ4色構成に設定できません。",
        "en": "This palette mixes {palette}. A {product} filament cannot be assigned to the same four-color set.",
    },
    "palette.material_catalog_unavailable": {
        "ja": "{material}のフィラメントライブラリを利用できません。PLA候補での代用は行いません。",
        "en": "The {material} filament library is unavailable. PLA candidates will not be substituted.",
    },
    "palette.material_need_four": {
        "ja": "{material}で異なる基本色が4色そろいません（現在{count}色）。異素材では補完しません。",
        "en": "{material} does not provide four distinct base colors (currently {count}). Other materials will not be used as fallback.",
    },
    "palette.material_gamut_title": {
        "ja": "素材内の近似誤差が大きいです",
        "en": "Large Within-material Approximation Error",
    },
    "palette.material_gamut_warning": {
        "ja": "{material}の登録色{count}色だけで構成した結果、平均ΔE76は{delta:.1f}でした。目的色が素材の色域外にある可能性があります。異素材では補完していません。比較チャートで確認してください。",
        "en": "Using only {count} cataloged {material} colors produced mean delta-E76 {delta:.1f}. The target may be outside this material's available gamut. No other material was used. Verify with the comparison chart.",
    },
    "palette.material_result_metric": {
        "ja": "素材 {material} / 候補色 {count}色 / 素材内平均ΔE76 {delta:.1f}",
        "en": "Material {material} / {count} candidate colors / within-material mean delta-E76 {delta:.1f}",
    },
    "palette.material_changed_no_obj": {
        "ja": "{material}で混色する設定へ変更しました。モデルを開くと{material}だけで基本4色を提案します。",
        "en": "Changed to {material} mixing. After opening a model, all four base colors will be proposed from {material} only.",
    },
    "export.cross_material_title": {
        "ja": "異素材は1つの3MFへ混在できません",
        "en": "Materials Cannot Be Mixed in One 3MF",
    },
    "export.cross_material_body": {
        "ja": "現在のパーツには{materials}の設定があります。\n\nFull Spectrumでは1つの印刷ジョブを同一素材4本で構成するため、異素材を含む統合3MFは作成しません。\n\n各パーツを素材別の独立3MFとして出力しますか？\n［はい］: パーツ別3MFのみ出力\n［いいえ］: 設定を保持して中止",
        "en": "The current parts use {materials}.\n\nA Full Spectrum print job must use four spools from one material family, so no combined cross-material 3MF will be created.\n\nExport each part as an independent material-specific 3MF?\nYes: export individual part 3MFs only\nNo: keep the settings and cancel",
    },
    "export.cross_material_cancelled": {
        "ja": "3MF出力を中止しました。異素材のパーツ設定は保持されています",
        "en": "3MF export cancelled. The cross-material part settings were kept.",
    },
    "export.individual_only_status": {
        "ja": "パーツ別3MFのみ出力完了: {count}個",
        "en": "Individual-only 3MF export complete: {count} files",
    },
    "export.individual_only_heading": {
        "ja": "{folder}\n\n異素材を混在させた統合3MFは作成せず、各パーツを対応素材の独立3MFとして保存しました。\n\n",
        "en": "{folder}\n\nNo combined cross-material 3MF was created. Each part was saved as an independent 3MF for its selected material.\n\n",
    },
    "export.individual_only_done_title": {
        "ja": "パーツ別3MFの出力が完了しました",
        "en": "Individual Part 3MF Export Complete",
    },
    "export.individual_only_done_body": {
        "ja": "{folder}\n\n異素材を混在させた統合3MFは作成せず、各パーツを対応素材の独立3MFとして{count}個保存しました。\n\n通常層0.08 mmは記録済みです。サポートはOrca側で選び、Snapmaker Orcaでは各3MFを『プロジェクトとして開く』で開いてください。\n\n保存フォルダーを開きますか？",
        "en": "{folder}\n\nNo combined cross-material 3MF was created. {count} parts were saved as independent 3MF projects for their selected materials.\n\nThe 0.08 mm normal layer height is recorded. Choose supports in Orca and open each 3MF with Open as project in Snapmaker Orca.\n\nOpen the output folder?",
    },
    "export.done_status": {
        "ja": "出力完了（積層ピッチ0.08 mm）: {name}",
        "en": "Export complete (0.08 mm layer height): {name}",
    },
    "export.done_status_warning": {
        "ja": "出力完了・Orcaプレビュー要確認: {name}",
        "en": "Export complete - verify the Orca preview: {name}",
    },
    "export.done_title": {
        "ja": "出力が完了しました",
        "en": "Export Complete",
    },
    "export.single_glb_structure": {
        "ja": "単一GLBのUV／テクスチャ継ぎ目だけを統合し、穴埋めで形状を追加せず、1つの閉立体モデルとして出力しました。\n\n",
        "en": "Only the UV/texture seams of the single GLB were welded. No cap geometry was invented, and the result was exported as one closed model.\n\n",
    },
    "export.closed_structure": {
        "ja": "元のパーツ数・名前・配置を維持し、各パーツを閉じた印刷立体として出力しました。\n\n",
        "en": "The original part count, names, and placement were preserved, and each part was exported as a closed print solid.\n\n",
    },
    "export.current_structure": {
        "ja": "現在の印刷パーツ構造で出力しました。\n\n",
        "en": "The current print-part structure was exported.\n\n",
    },
    "export.individual_models_note": {
        "ja": "元のパーツ構成を保った個別3MFも {count} 個保存しました。\n\n",
        "en": "Also saved {count} individual 3MF files while preserving the original part structure.\n\n",
    },
    "export.common_palette_note": {
        "ja": "印刷パーツ別の基本4色設定は3MFメタデータへ保持し、印刷色は全体共通4色へ統合しました。\n\n",
        "en": "The per-part four-base-color settings were retained in 3MF metadata, while print colors were unified to one common four-color set.\n\n",
    },
    "export.self_intersection_warning": {
        "ja": "注意: 閉立体の必須検証は合格していますが、上限内の微小な自己交差を{parts}パーツ・{faces}面（合計面積 {area:.6g} mm²）で検出しました。Snapmaker Orcaで必ず『プロジェクトとして開く』を選び、スライスプレビューに欠落・異常な面・意図しない内部線がないことを確認してから印刷してください。\n\n",
        "en": "Caution: all mandatory solid checks passed, but bounded minor self-intersections were detected in {parts} part(s), affecting {faces} faces ({area:.6g} mm² total). Open the 3MF as a project in Snapmaker Orca and verify the slice preview for missing surfaces, abnormal faces, or unintended internal lines before printing.\n\n",
    },
    "export.done_instructions": {
        "ja": "積層ピッチは0.08 mmで記録済みです。サポートはOrca側で選択してください。\nSnapmaker Orcaでは『プロジェクトとして開く』を選んでください。\n\n保存フォルダーを開きますか？",
        "en": "The 0.08 mm layer height is recorded. Choose supports in Orca.\nIn Snapmaker Orca, select Open as project.\n\nOpen the output folder?",
    },
    "palette.apply_sample": {"ja": "取得色を反映", "en": "Apply Sample"},
    "palette.set_base_from_image": {
        "ja": "元画像から{slot}へ設定",
        "en": "Set {slot} from Image",
    },
    "palette.set_base_short": {"ja": "画像から", "en": "From Image"},
    "palette.pick_base_status": {
        "ja": "元画像をクリックすると{slot}へ直接反映します",
        "en": "Click the reference image to apply the sampled color directly to {slot}",
    },
    "palette.pick_reference_only": {
        "ja": "スポイトは左側の元画像内で使ってください",
        "en": "Use the eyedropper inside the reference image on the left",
    },
    "palette.pick_reference_for_slot": {
        "ja": "{slot}へ設定する色は左側の元画像内で選んでください",
        "en": "Choose the color for {slot} inside the reference image on the left",
    },
    "palette.sampled": {
        "ja": "スポイト: ({x}, {y}) = {color}",
        "en": "Sampled: ({x}, {y}) = {color}",
    },
    "palette.base_applied": {
        "ja": "{color}を{slot}へ設定しました。［現在の4色をプレビュー・3MFへ反映］で確認してください",
        "en": "Set {slot} to {color}. Choose Apply Current F1-F4 to Preview / 3MF to review it",
    },
    "palette.apply_physical": {
        "ja": "現在の4色をプレビュー・3MFへ反映",
        "en": "Apply Current F1-F4 to Preview / 3MF",
    },
    "palette.apply_physical_pending": {
        "ja": "基本4色を変更しました。［現在の4色をプレビュー・3MFへ反映］で、現在の色番号を保ったまま確認できます。",
        "en": "The four base colors changed. Choose Apply Current F1-F4 to Preview / 3MF to review them without changing the current color IDs.",
    },
    "palette.apply_physical_done": {
        "ja": "{target}の色番号を保ったまま、現在のF1〜F4を変換プレビューと3MFへ反映しました",
        "en": "Applied the current F1-F4 to the {target} preview and 3MF palette without changing its color IDs",
    },
    "palette.apply_physical_required_title": {
        "ja": "基本4色がまだ反映されていません",
        "en": "Base Colors Not Yet Applied",
    },
    "palette.apply_physical_required": {
        "ja": "次の設定では、基本4色の変更が変換プレビューへまだ反映されていません。\n\n{targets}\n\n各対象を選び、［現在の4色をプレビュー・3MFへ反映］を実行してから3MFを書き出してください。",
        "en": "Base-color changes have not yet been applied to the converted preview for:\n\n{targets}\n\nSelect each target and choose Apply Current F1-F4 to Preview / 3MF before exporting.",
    },
    "palette.reset_base": {"ja": "基本4色を初期値へ戻す", "en": "Reset Four Base Colors"},
    "palette.mix_group": {"ja": "混色パレット（F1〜F4）", "en": "Mixed Palette (F1-F4)"},
    "palette.primary_mix": {"ja": "主混色", "en": "Primary"},
    "palette.secondary_mix": {"ja": "追加混色", "en": "Additional"},
    "palette.extended": {
        "ja": "選択した16・24・32色を自動割当に使う",
        "en": "Use the selected 16, 24, or 32 colors for automatic mapping",
    },
    "palette.extended_short": {
        "ja": "表示中の混色を自動割当に使う",
        "en": "Use the shown mixes for automatic mapping",
    },
    "palette.state_count": {
        "ja": "混色を含む色数",
        "en": "Total palette colors",
    },
    "paint.palette_count_applied": {
        "ja": "パレットを{count}色へ変更しました",
        "en": "Changed the palette to {count} colors",
    },
    "palette.state_count_common_applied": {
        "ja": "{count}色を全体とパーツ設定{parts}件へ反映",
        "en": "Applied {count} colors to common and {parts} part settings",
    },
    "palette.state_count_part_applied": {
        "ja": "選択パーツを{count}色へ変更",
        "en": "Changed the selected part to {count} colors",
    },
    "palette.mix_help": {
        "ja": "各ペアに主混色と追加混色の2比率を設定できます。\n追加比率も保存されるため、手塗り済みの色IDを維持できます。",
        "en": "Set primary and additional ratios for every pair.\nAdditional ratios are saved, preserving manually painted color IDs.",
    },
    "palette.calibration_export": {
        "ja": "現在のパレットで実機比較チャートを生成…",
        "en": "Generate Physical Comparison Chart…",
    },
    "palette.calibration_help": {
        "ja": "現在の編集対象のF1～F4と混色比率を保存し、選択中の16・24・32色を実機で比較できる3MF一式を生成します。OBJは不要で、無効にした色も比較用に収録します。",
        "en": "Save the current target's F1-F4 colors and mix ratios as a printable 3MF bundle for the selected 16, 24, or 32 states. No OBJ is required, and disabled states are included for comparison.",
    },
    "palette.black_free_group": {
        "ja": "黒なしグラデーション（自動配色）",
        "en": "Black-Free Gradient (Automatic Mapping)",
    },
    "palette.black_free_enable": {
        "ja": "黒を含む混色を赤〜茶へ再割当",
        "en": "Remap black-containing mixes toward red-brown",
    },
    "palette.black_free_black_slot": {
        "ja": "黒",
        "en": "Black",
    },
    "palette.black_free_red_slot": {
        "ja": "赤",
        "en": "Red",
    },
    "palette.black_free_brown_slot": {
        "ja": "茶",
        "en": "Brown",
    },
    "palette.black_free_off_summary": {
        "ja": "OFF：従来どおり、黒を含む混色も自動配色に使用します。",
        "en": "Off: automatic mapping can use black-containing mixes as before.",
    },
    "palette.black_free_on_summary": {
        "ja": "ON：黒 {black} {black_hex} → 赤 {red} {red_hex}〜茶 {brown} {brown_hex} の候補 {candidates}色 / 手塗り黒混色 {manual}面は維持",
        "en": "On: black {black} {black_hex} -> {candidates} candidates from red {red} {red_hex} to brown {brown} {brown_hex} / {manual} manual black-mix faces preserved",
    },
    "palette.black_free_help": {
        "ja": "自動配色だけを変更し、純黒F単色・手塗りstate・3MF混色比率は維持します。",
        "en": "Only automatic mapping changes; pure-black F states, manual paint, and 3MF mix ratios are preserved.",
    },
    "palette.black_free_distinct_message": {
        "ja": "黒・赤・茶には、それぞれ異なるF1〜F4スロットを選んでください。",
        "en": "Choose three different F1-F4 slots for black, red, and brown.",
    },
    "palette.black_free_no_candidate_message": {
        "ja": "赤〜茶として使える黒なし候補がありません。選択した赤・茶のF単色または混色を自動配色で有効にしてください。",
        "en": "No enabled black-free red-brown candidate is available. Enable the selected red or brown F state, or one of their mixes, for automatic mapping.",
    },
    "palette.black_free_invalid_title": {
        "ja": "黒なしグラデーションを設定できません",
        "en": "Black-Free Gradient Cannot Be Applied",
    },
    "palette.black_free_enabled_status": {
        "ja": "黒 {black} を含む自動混色を赤 {red}〜茶 {brown}へ再割当しました。手塗り黒混色 {manual}面は維持します。",
        "en": "Remapped automatic mixes containing black {black} toward red {red}-brown {brown}. {manual} manually painted black-mix faces remain unchanged.",
    },
    "palette.black_free_disabled_status": {
        "ja": "黒なしグラデーションをOFFにし、従来の自動配色へ戻しました。",
        "en": "Black-Free Gradient is off; restored the original automatic mapping.",
    },
    "palette.black_free_developer_disabled_status": {
        "ja": "開発者機能OFF: 黒なし設定{palettes}件を解除",
        "en": "Developer features off: disabled Black-Free Gradient in {palettes} palettes",
    },
    "palette.black_free_manual_warning_title": {
        "ja": "手塗りの黒混色が残っています",
        "en": "Manually Painted Black Mixes Remain",
    },
    "palette.black_free_manual_warning_message": {
        "ja": "黒なしグラデーションがONの {parts} パーツに、黒を含む混色で手塗りした面が {faces} 面残っています。\n\nこの機能は自動配色だけを再割当するため、手塗りstateは変更しません。そのまま出力すると黒い積層痕が残る可能性があります。純黒のF単色はこの件数に含めていません。\n\nこのまま3MF出力を続けますか？",
        "en": "{faces} faces across {parts} Black-Free Gradient parts are explicitly painted with black-containing mixed states.\n\nThis mode remaps automatic assignments only, so manual states remain unchanged and may leave black layer lines. Pure-black F states are not included in this count.\n\nContinue exporting the 3MF?",
    },
    "palette.black_free_manual_warning_cancelled": {
        "ja": "手塗りの黒混色を確認するため、3MF出力を中止しました。",
        "en": "Cancelled 3MF export so the manually painted black mixes can be reviewed.",
    },
    "palette.black_output_group": {
        "ja": "実機黒補正",
        "en": "Physical Black Correction",
    },
    "palette.black_output_enable": {
        "ja": "実機黒補正（表示色・自動配色は維持）",
        "en": "Physical black correction (keep display and auto mapping)",
    },
    "palette.black_output_slot": {
        "ja": "黒フィラメント",
        "en": "Black filament",
    },
    "palette.black_output_preset": {
        "ja": "黒弱め",
        "en": "Reduce",
    },
    "palette.black_output_off_summary": {
        "ja": "補正OFF：目標／表示比率と3MF出力比率は同じです。",
        "en": "Correction off: target/display and 3MF output ratios are identical.",
    },
    "palette.black_output_summary": {
        "ja": "目標／表示の黒: {target}%  →  3MF出力の黒: {output}%",
        "en": "Target/display black: {target}%  ->  3MF output black: {output}%",
    },
    "palette.black_output_pure_warning": {
        "ja": "注意：純黒の色{state}（{slot}単色）は純黒のままです。補正されるのは{slot}を含む混色だけです。",
        "en": "Note: pure-black color {state} ({slot} alone) stays pure black. Only mixed states containing {slot} are corrected.",
    },
    "palette.black_output_applied": {
        "ja": "{slot}を黒として、3MF出力だけに「黒弱め 5〜25%」を適用しました。表示色と自動配色は変わりません。",
        "en": "Applied Weak Black 5-25% to 3MF output only, using {slot} as black. Display colors and auto mapping are unchanged.",
    },
    "palette.black_output_disabled": {
        "ja": "実機黒補正をOFFにしました。3MF出力は目標／表示比率と同じです。",
        "en": "Physical black correction is off. 3MF output now uses the target/display ratios.",
    },
    "palette.black_output_disabled_shell_too": {
        "ja": "実機黒補正をOFFにしたため、黒混色の内壁化もOFFにしました。3MF出力は従来のZ方向積層です。",
        "en": "Physical black correction was turned off, so black-inner-wall output was also disabled. The 3MF now uses the legacy Z-layer recipe.",
    },
    "palette.surface_shell_group": {
        "ja": "黒混色を内壁へ隠す（3MF・実験）",
        "en": "Hide Black Mixes on Inner Walls (3MF, Experimental)",
    },
    "palette.surface_shell_enable": {
        "ja": "黒を含む混色だけ、相手色を外壁・黒を内壁Cycleへ",
        "en": "For black-containing mixes only: partner outside, black in the inner-wall cycle",
    },
    "palette.surface_shell_help": {
        "ja": "実機黒補正の「黒弱め 5〜25%」presetが必須です。黒を含む混色だけを相手色の固定外壁＋相手色／黒の内壁Cycleへ変換し、補正後の黒と相手色の2色比率全体を維持します。非黒混色は従来recipe、純黒を含むF1〜F4単色は変更しません。3MFはClassic wall、壁2本、外壁／内壁0.42 mmに加え、support／raftのbaseとinterfaceを最明色の物理Fスロットへ固定し、purge-to-support／infill／objectsをすべて無効化します。サポート生成自体は強制しません。主対象は垂直側面です。天面・底面・薄い部分・強い斜面では同じ隠れ方になりません。",
        "en": "The Weak Black 5-25% physical-correction preset is required. Only mixes containing black are converted to a fixed partner-color outer wall plus a partner/black inner cycle, retaining the complete corrected two-color ratio. Non-black mixes keep the legacy recipe, and pure F1-F4 states, including pure black, are unchanged. The 3MF fixes Classic walls, two equal 0.42 mm perimeters, support/raft base and interface to the lightest physical F slot, and disables every purge-to-print path: support, infill, and objects. It does not force support generation. This targets vertical sidewalls; top, bottom, thin, and steeply sloped areas do not hide black in the same way.",
    },
    "palette.surface_shell_off_summary": {
        "ja": "OFF：全混色を従来どおりZ方向へ積層します。",
        "en": "Off: every mixed state uses the legacy Z-layer recipe.",
    },
    "palette.surface_shell_on_summary": {
        "ja": "ON：黒を含む混色だけ、相手色を外壁・補正後の黒を内壁へ配置します。非黒混色は従来recipe、純黒は純黒のままです。Grouped Cycle保護のためpurge-to-support／infill／objectsは無効になります。",
        "en": "On: only black-containing mixes place the partner outside and corrected black on the inner wall. Non-black mixes keep the legacy recipe; pure black stays pure black. Purge-to-support, infill, and objects are disabled to protect grouped Cycle output.",
    },
    "palette.surface_shell_requires_black_summary": {
        "ja": "利用するには、先に実機黒補正の「黒弱め 5〜25%」を適用してください。",
        "en": "Apply the Weak Black 5-25% physical-correction preset before enabling this mode.",
    },
    "palette.surface_shell_custom_summary": {
        "ja": "現在の3MF出力比率はcustom値です。値を上書きしないため、黒混色の内壁化は利用できません。",
        "en": "The current 3MF output ratios are custom. Black-inner-wall mode is unavailable so those values are not overwritten.",
    },
    "palette.surface_shell_slot_mismatch_summary": {
        "ja": "黒補正で選択したFスロットが、現在のF1〜F4で最暗色ではありません。黒フィラメントの指定を確認してください。",
        "en": "The F slot selected for black correction is not the darkest current F1-F4 color. Check the black-filament selection.",
    },
    "palette.surface_shell_unavailable_title": {
        "ja": "黒混色の内壁化をONにできません",
        "en": "Black-inner-wall mode cannot be enabled",
    },
    "palette.surface_shell_requires_black_message": {
        "ja": "この機能は補正後の黒量から内壁Cycleを作るため、実機黒補正の「黒弱め 5〜25%」presetが必要です。先に実機黒補正をONにしてください。",
        "en": "This feature builds its inner-wall cycle from the corrected black share. Enable the Weak Black 5-25% physical-correction preset first.",
    },
    "palette.surface_shell_custom_message": {
        "ja": "現在の3MF出力比率は「黒弱め 5〜25%」presetと完全一致しないcustom値です。custom値は変更していません。内壁化を使う場合は「黒弱め 5〜25%を適用」を押してください。",
        "en": "The current 3MF output ratios are custom and do not exactly match the Weak Black 5-25% preset. They were left unchanged. Click Apply Weak Black 5-25% before using inner-wall mode.",
    },
    "palette.surface_shell_slot_mismatch_message": {
        "ja": "実機黒補正で選択したスロットと、F1〜F4の最暗色が一致しません。実際の黒フィラメントを選び直すか、F1〜F4の色設定を確認してください。",
        "en": "The slot selected by physical black correction does not match the darkest F1-F4 color. Select the actual black filament or check the F1-F4 color settings.",
    },
    "palette.surface_shell_enabled_status": {
        "ja": "黒混色の内壁化をONにしました。黒を含む混色の3MF recipeだけを変更します。",
        "en": "Black-inner-wall mode is on. Only 3MF recipes for black-containing mixes are changed.",
    },
    "palette.surface_shell_disabled_status": {
        "ja": "黒混色の内壁化をOFFにしました。全混色を従来のZ方向積層で出力します。",
        "en": "Black-inner-wall mode is off. Every mixed state will use the legacy Z-layer output.",
    },
    "palette.surface_shell_unavailable_group": {
        "ja": "黒混色の内壁化（現在無効）",
        "en": "Black-inner-wall output (currently disabled)",
    },
    "palette.surface_shell_unavailable_label": {
        "ja": "現在無効（Snapmaker Orcaアクセス違反対策）",
        "en": "Currently disabled (Snapmaker Orca access-violation safeguard)",
    },
    "palette.surface_shell_unavailable_help": {
        "ja": "Grouped Cycleが仮想混色IDを物理ツールとして扱い、Snapmaker Orca 2.3.5でアクセス違反を起こす経路があるため無効化しています。実機黒補正のRatio出力、表示色、非黒混色、F1〜F4単色、パーツ別paletteは変更しません。安全なCycle-free方式は別途検証します。",
        "en": "Disabled because Grouped Cycle can expose a virtual mixed-state ID as a physical tool and trigger an access violation in Snapmaker Orca 2.3.5. Physical black-correction Ratio output, display colors, non-black mixes, pure F1-F4 states, and per-part palettes remain unchanged. A safe Cycle-free replacement will be evaluated separately.",
    },
    "palette.surface_shell_unavailable_summary": {
        "ja": "現在無効（Snapmaker Orcaアクセス違反対策）。3MFは安全な従来Ratioで出力し、実機黒補正はそのまま保持します。",
        "en": "Currently disabled to prevent Snapmaker Orca access violations. 3MF uses the safe legacy Ratio recipe and preserves physical black correction.",
    },
    "palette.surface_shell_unavailable_status": {
        "ja": "黒混色の内壁化は現在無効です。安全なRatio出力を使用します。",
        "en": "Black-inner-wall output is currently disabled. The safe Ratio output path is used.",
    },
    "developer_features.show": {
        "ja": "開発者向け実験機能を表示",
        "en": "Show Developer Experimental Features",
    },
    "developer_features.enabled_status": {
        "ja": "開発者向け実験機能を表示しました。実験出力は通常出力と分離されています。",
        "en": "Developer experimental features are now visible. Laboratory exports remain separate from normal output.",
    },
    "developer_features.disabled_status": {
        "ja": "開発者向け実験機能を非表示にしました。通常出力は変更されません。",
        "en": "Developer experimental features are hidden. Normal output is unchanged.",
    },
    "developer_features.required_title": {
        "ja": "開発者向け実験機能は非表示です",
        "en": "Developer Experimental Features Are Hidden",
    },
    "developer_features.required_message": {
        "ja": "［フィラメント設定］の「開発者向け実験機能を表示」をONにしてから実行してください。通常の3MF出力には影響しません。",
        "en": "Enable Show Developer Experimental Features under Filament Settings before using this command. Normal 3MF output is unaffected.",
    },
    "color_depth.group": {
        "ja": "ColorDepth Lab（r21・全混色state）",
        "en": "ColorDepth Lab (r21, all mixed states)",
    },
    "color_depth.enable": {
        "ja": "未校正の実験出力を有効にする（SLICE ONLY）",
        "en": "Enable uncalibrated experimental output (SLICE ONLY)",
    },
    "color_depth.outer_thickness": {
        "ja": "共通の外壁厚さ",
        "en": "Common outer thickness",
    },
    "color_depth.export": {
        "ja": "ColorDepth実験3MFを書き出す…",
        "en": "Export ColorDepth laboratory 3MF…",
    },
    "color_depth.convert_part_3mf": {
        "ja": "通常のパーツ別3MFから変換…",
        "en": "Convert per-part 3MF…",
    },
    "color_depth.help": {
        "ja": "FullSpectrumのstateは目標色ラベルとしてだけ使い、従来のRatio／Cycle比率は無視します。混色ごとに明るい物理色を外側、もう一方を内側へ法線方向に配置します。同じ2色の複数shadeは、未校正の共通外壁方式では同じ見た目へ統合されます。物理F1～F4だけの3MFですが、現段階は必ずSLICE ONLYです。",
        "en": "FullSpectrum states are used only as target-colour labels; legacy Ratio/Cycle percentages are ignored. For each mixed state, the brighter physical member is placed outside and the other behind it along surface depth. Multiple shades of the same pair collapse under this uncalibrated common-skin policy. The 3MF uses physical F1-F4 only and remains strictly SLICE ONLY.",
    },
    "color_depth.enabled_status": {
        "ja": "ColorDepth Labを有効にしました。未校正・SLICE ONLYです。",
        "en": "ColorDepth Lab enabled. It is uncalibrated and SLICE ONLY.",
    },
    "color_depth.disabled_status": {
        "ja": "ColorDepth Labを無効にしました。通常出力は変更されません。",
        "en": "ColorDepth Lab disabled. Normal output is unchanged.",
    },
    "color_depth.confirm_title": {
        "ja": "未校正ColorDepthを書き出しますか？",
        "en": "Export uncalibrated ColorDepth?",
    },
    "color_depth.confirm_message": {
        "ja": "外壁 {thickness:.2f} mm／固定レイヤー {layer:.2f} mmで、全混色stateを法線方向の物理材料へ変換します。従来のRatio／Cycle比率は使わず、同じ2色のshadeは同じrecipeへ統合されます。\n\nこれは色校正前のSLICE ONLY出力です。Snapmaker Orcaで全レイヤーを確認し、まだプリンターへ送らないでください。",
        "en": "All mixed states will become normal-depth physical materials with a {thickness:.2f} mm outer skin and fixed {layer:.2f} mm layers. Legacy percentages are unused, and shades sharing one pair collapse to the same recipe.\n\nThis is an uncalibrated SLICE ONLY output. Inspect every layer in Snapmaker Orca and do not send it to the printer yet.",
    },
    "color_depth.convert_confirm_title": {
        "ja": "パーツ別3MFをColorDepthへ変換しますか？",
        "en": "Convert this per-part 3MF to ColorDepth?",
    },
    "color_depth.convert_confirm_message": {
        "ja": "変換元3MFに埋め込まれた定義:\n{physical_slots}\nstate数: {state_count}\n混色state→物理ペア:\n{state_pairs}\n\nColorDepth出力: 外壁 {thickness:.2f} mm／固定レイヤー {layer:.2f} mm\n従来のRatio／Cycle比率は無視します。\n\nこれは色校正前のSLICE ONLY出力です。Snapmaker Orcaで全レイヤーを確認し、まだプリンターへ送らないでください。",
        "en": "Definitions embedded in the source 3MF:\n{physical_slots}\nState count: {state_count}\nMixed state → physical pair:\n{state_pairs}\n\nColorDepth output: {thickness:.2f} mm outer skin / fixed {layer:.2f} mm layers\nLegacy Ratio/Cycle percentages are ignored.\n\nThis is an uncalibrated SLICE ONLY output. Inspect every layer in Snapmaker Orca and do not send it to the printer yet.",
    },
    "color_depth.inspecting_part_3mf": {
        "ja": "パーツ別3MFの埋め込み定義を検証しています…",
        "en": "Validating the embedded per-part 3MF definitions…",
    },
    "color_depth.reason.source_equals_destination": {
        "ja": "変換元3MFは上書きできません。別のファイル名を指定してください。",
        "en": "The source 3MF cannot be overwritten. Choose a different file name.",
    },
    "color_depth.reason.invalid_part_3mf": {
        "ja": "通常のパーツ別3MFとして安全に読み込めませんでした。\n\n{reason}",
        "en": "The file could not be safely read as a normal per-part 3MF.\n\n{reason}",
    },
    "color_depth.running": {
        "ja": "ColorDepth物理材料3MFを生成しています…",
        "en": "Creating the ColorDepth physical-material 3MF…",
    },
    "color_depth.done_title": {
        "ja": "ColorDepth SLICE ONLY 3MFを生成しました",
        "en": "ColorDepth SLICE ONLY 3MF created",
    },
    "color_depth.done_message": {
        "ja": "{path}\n\n外壁 {thickness:.2f} mm／固定 {layer:.2f} mm、同一recipeへ統合された対象ラベル数 {collapsed}。Snapmaker Orcaでは「プロジェクトとして開く」を選び、物理F1～F4以外がないこと、欠損・重なり・経路競合・アクセス違反がないことを全レイヤーで確認してください。まだ印刷許可ではありません。\n\n保存フォルダーを開きますか？",
        "en": "{path}\n\nOuter skin {thickness:.2f} mm / fixed {layer:.2f} mm; {collapsed} target labels belong to collapsed recipe groups. Open as a project in Snapmaker Orca and inspect every layer for physical F1-F4 only, with no missing region, overlap, path conflict, or access violation. This is not print approval.\n\nOpen the saved folder?",
    },
    "color_depth.error_title": {
        "ja": "ColorDepth実験3MFを生成できません",
        "en": "Could not create ColorDepth laboratory 3MF",
    },
    "color_depth.error_message": {
        "ja": "安全条件を満たさないため近似出力は行いませんでした。\n\n{reason}",
        "en": "No approximate output was written because the safety conditions were not met.\n\n{reason}",
    },
    "color_depth.reason.opt_in_required": {
        "ja": "先に「未校正の実験出力を有効にする」をONにしてください。通常の3MF出力とは独立した設定です。",
        "en": "Enable the uncalibrated experiment first. This opt-in is separate from normal 3MF output.",
    },
    "color_depth.reason.recipe_policy": {
        "ja": "未校正SLICE ONLY recipe policyが明示されていません。設定を読み直してください。",
        "en": "The explicit uncalibrated SLICE ONLY recipe policy is missing. Reload the settings.",
    },
    "color_depth.reason.fixed_layer": {
        "ja": "ColorDepth Labの初期検証は0.20 mmレイヤー固定です。",
        "en": "The initial ColorDepth Lab validation requires fixed 0.20 mm layers.",
    },
    "color_depth.reason.closed_mesh": {
        "ja": "形状を穴のない閉立体として検証できません。穴、自己交差、分離shellを修復してください。",
        "en": "The geometry is not verified as a watertight solid. Repair holes, self-intersections, and disconnected shells.",
    },
    "color_depth.reason.palette": {
        "ja": "対象stateまたはF1～F4の定義がColorDepthへ変換できません。palette設定を確認してください。",
        "en": "A target state or F1-F4 definition cannot be converted to ColorDepth. Check the palette settings.",
    },
    "color_depth.reason.shared_palette": {
        "ja": "複数パーツでF1～F4またはstate表の意味が異なります。1つの物理材料3MFでは共通定義が必要です（パーツ {part_index}）。",
        "en": "Parts use different F1-F4 or target-state meanings. One physical-material 3MF requires a shared definition (part {part_index}).",
    },
    "color_depth.reason.builder_unavailable": {
        "ja": "実モデル用のColorDepth形状builderを読み込めません。r21の完全版を起動し直してください。",
        "en": "The real-model ColorDepth geometry builder is unavailable. Restart the complete r21 build.",
    },
    "color_depth.reason.thickness": {
        "ja": "外壁厚さが不正です。0.14～0.60 mmで指定してください。",
        "en": "The outer thickness is invalid. Use 0.14 to 0.60 mm.",
    },
    "color_depth.reason.ambiguous_outer": {
        "ja": "混色を構成する2本の明るさが同じため、未校正ruleでは外側を一意に決められません。F1～F4の色設定または校正LUTが必要です。",
        "en": "The two physical members have equal luminance, so the uncalibrated rule cannot choose an outside material. Adjust F1-F4 colours or provide a calibrated LUT.",
    },
    "color_depth.reason.geometry": {
        "ja": "表面を保ったまま、隙間・重なりのない物理材料領域へ分割できませんでした。近似出力は保存していません。",
        "en": "The surface could not be partitioned into gap-free, overlap-free physical material regions. No approximate output was saved.",
    },
    "radial.group": {
        "ja": "完全ラジアル黒内層（r20実験版）",
        "en": "Full-radial black interior (r20 laboratory)",
    },
    "radial.skin_thickness": {
        "ja": "相手色の外皮厚",
        "en": "Partner-color skin",
    },
    "radial.export": {
        "ja": "ラジアル実験3MFを書き出す…",
        "en": "Export radial laboratory 3MF…",
    },
    "radial.help": {
        "ja": "Grouped Cycleは使わず、相手色の閉じた外皮と純黒の内部を同一PrintObject内の物理F1〜F4パーツとして生成します。初版は、閉立体1パーツの全面が同じ黒混色stateである場合だけ安全に変換します。複数色・部分塗り・複数パーツは近似せず停止します。生成物はSLICE ONLYです。",
        "en": "Uses no Grouped Cycle. It creates a closed partner-color skin and a pure-black interior as physical F1-F4 parts in one PrintObject. This first release safely converts only one closed part whose entire exterior uses one black-containing mixed state. Multi-color, partially painted, and multi-part models stop instead of being approximated. Output is SLICE ONLY.",
    },
    "radial.running": {
        "ja": "完全ラジアル実験3MFを生成しています…",
        "en": "Creating the full-radial laboratory 3MF…",
    },
    "radial.done_title": {
        "ja": "ラジアル実験3MFを生成しました",
        "en": "Radial laboratory 3MF created",
    },
    "radial.done_message": {
        "ja": "{path}\n\n外皮 {thickness:.2f} mm／固定 {layer:.2f} mmピッチです。Snapmaker Orcaでは『プロジェクトとして開く』を選び、まずスライスと全レイヤーのプレビューだけを確認してください。まだ自動で印刷許可にはなりません。\n\n保存フォルダーを開きますか？",
        "en": "{path}\n\nPartner skin {thickness:.2f} mm / fixed {layer:.2f} mm layers. In Snapmaker Orca, choose Open as project and inspect slicing plus every layer before anything else. This output is not automatically approved for printing.\n\nOpen the saved folder?",
    },
    "radial.error_title": {
        "ja": "ラジアル実験3MFを生成できません",
        "en": "Could not create radial laboratory 3MF",
    },
    "radial.error_message": {
        "ja": "安全条件を満たさないため、近似出力は行いませんでした。\n\n{reason}",
        "en": "No approximate output was written because the safety conditions were not met.\n\n{reason}",
    },
    "radial.reason.invalid_black_slot": {
        "ja": "純黒として使うフィラメントを特定できません。F1〜F4の黒スロットを選び直してください。",
        "en": "The physical black filament could not be identified. Select its F1-F4 slot again.",
    },
    "radial.reason.invalid_physical_colors": {
        "ja": "F1〜F4の実フィラメント色が不正です。4色すべてのカラーコードを確認してください。",
        "en": "The physical F1-F4 colours are invalid. Check all four filament colour codes.",
    },
    "radial.reason.unique_darkest_black_required": {
        "ja": "最も暗いフィラメントが1本に決まりません（候補: {slots}）。実際の黒1本だけが最暗になるようF1〜F4の色を設定してください。",
        "en": "There is no single darkest filament (candidates: {slots}). Set F1-F4 so that the actual black spool alone is darkest.",
    },
    "radial.reason.selected_black_not_darkest": {
        "ja": "黒スロットに{selected}が選ばれていますが、設定色で最も暗いのは{darkest}です。実際の黒スロットを選び直してください。",
        "en": "{selected} is selected as black, but {darkest} is darkest in the configured colours. Select the slot holding the actual black spool.",
    },
    "radial.reason.single_part_required": {
        "ja": "この実験出力は閉じた印刷パーツ1個だけに対応します（現在 {part_count} 個）。対象を1パーツにまとめてから再実行してください。",
        "en": "This laboratory export supports exactly one closed print part (currently {part_count}). Reduce the target to one part and try again.",
    },
    "radial.reason.single_palette_required": {
        "ja": "対象に複数のフィラメント構成があります。1パーツ・1組のF1〜F4設定にそろえてから再実行してください。",
        "en": "The target uses multiple filament sets. Use one part with one F1-F4 set and try again.",
    },
    "radial.reason.closed_mesh_required": {
        "ja": "形状が、穴のない閉立体1個として安全に確認できません。メッシュの穴・自己交差・分離した殻を修復してください。",
        "en": "The geometry could not be verified as one watertight solid. Repair holes, self-intersections, and disconnected shells first.",
    },
    "radial.reason.generated_surface_not_supported": {
        "ja": "修復で追加された面を含むため、元の外観を保証できません。元モデルを閉立体として修正してから再処理してください。",
        "en": "Repair-generated faces prevent an exterior-preservation guarantee. Fix the source model into a closed solid, then process it again.",
    },
    "radial.reason.uniform_black_mix_required": {
        "ja": "外面全体が同じ『黒＋相手色』の混色ではありません。初版では1種類の黒混色だけで全面を塗り、部分塗りや複数混色をなくしてください。",
        "en": "The whole exterior is not one identical black-plus-partner mix. For this first release, cover every exterior face with one black-containing mix and remove partial or multi-state painting.",
    },
    "radial.reason.skin_thickness_failed": {
        "ja": "指定した外皮厚では内部を安全に残せません。外皮を薄くするか、細すぎる部分のない大きなモデルで試してください。",
        "en": "The requested skin cannot leave a safe interior. Reduce skin thickness or use a larger model without very thin regions.",
    },
    "radial.reason.geometry_generation_failed": {
        "ja": "外形を保ったまま外皮と内部を隙間なく分割できませんでした。この形状では出力せず、メッシュを簡略化・修復して再試行してください。",
        "en": "The model could not be split into an exact-touch skin and core while preserving its exterior. No output was written; simplify or repair the mesh and try again.",
    },
    "radial.reason.geometry_rejected": {
        "ja": "形状の安全検証に合格しませんでした。閉立体1パーツ・全面1種類の黒混色・十分な厚みを確認してください。",
        "en": "Geometry safety validation failed. Check for one watertight part, one black-containing mix over the full exterior, and sufficient thickness.",
    },
    # Filament product candidates (beta).  This stays separate from the mix
    # recipe UI because it compares the four physical F1-F4 colors against a
    # bundled product-color database, not against Full Spectrum mix states.
    "filament_candidates.button": {
        "ja": "フィラメント候補 β",
        "en": "Filament Candidates β",
    },
    "filament_candidates.title": {
        "ja": "フィラメント候補 β",
        "en": "Filament Candidates β",
    },
    "filament_candidates.intro": {
        "ja": "現在選択中の素材だけで、F1～F4に近い製品を各色3候補ずつ表示します。PLAが既定です。",
        "en": "Shows three products near each F1-F4 color using only the selected material. PLA is the default.",
    },
    "filament_candidates.notice": {
        "ja": "β版・参考比較です。販売中や在庫ありを保証しません。実物の色は仕上げ、印刷条件、照明、製造ロットなどで変わります。",
        "en": "Beta reference comparison. Availability and stock are not guaranteed. Actual color varies with finish, print settings, lighting, production lot, and other factors.",
    },
    "filament_candidates.brand": {"ja": "メーカー", "en": "Brand"},
    "filament_candidates.finish": {"ja": "仕上げ", "en": "Finish"},
    "filament_candidates.all": {"ja": "すべて", "en": "All"},
    "filament_candidates.prefer_measured": {
        "ja": "同一製品は実測値を使用",
        "en": "Use measured value for same product",
    },
    "filament_candidates.refresh": {"ja": "候補を更新", "en": "Refresh"},
    "filament_candidates.mode": {"ja": "候補の範囲", "en": "Candidate scope"},
    "filament_candidates.mode_all": {
        "ja": "全フィラメント",
        "en": "All filaments",
    },
    "filament_candidates.mode_owned": {
        "ja": "手持ちのみ",
        "en": "Owned only",
    },
    "filament_candidates.inventory": {
        "ja": "手持ちフィラメント",
        "en": "Owned Filaments",
    },
    "filament_candidates.inventory_help": {
        "ja": "メーカーまたは製品をダブルクリックすると、まとめて手持ち登録・解除できます。",
        "en": "Double-click a brand or product to add or remove it from your owned inventory.",
    },
    "filament_candidates.inventory_product": {
        "ja": "メーカー / 製品",
        "en": "Brand / Product",
    },
    "filament_candidates.inventory_owned": {"ja": "手持ち", "en": "Owned"},
    "filament_candidates.inventory_add": {
        "ja": "選択を手持ちに追加",
        "en": "Add Selection",
    },
    "filament_candidates.inventory_remove": {
        "ja": "選択を手持ちから解除",
        "en": "Remove Selection",
    },
    "filament_candidates.inventory_count": {
        "ja": "手持ち {count}製品",
        "en": "{count} owned products",
    },
    "filament_candidates.inventory_unresolved": {
        "ja": "見つからない登録 ({count})",
        "en": "Unresolved registrations ({count})",
    },
    "filament_candidates.inventory_empty": {
        "ja": "手持ちフィラメントを左の一覧から登録してください。",
        "en": "Register owned filaments from the list on the left.",
    },
    "filament_candidates.snapshot_only": {
        "ja": "データベースを利用できないため、保存済みの手持ち製品情報だけを使用しています。",
        "en": "The database is unavailable; using saved owned-product snapshots only.",
    },
    "filament_candidates.inventory_saved": {
        "ja": "手持ちフィラメントを{count}製品保存しました。",
        "en": "Saved {count} owned filament products.",
    },
    "filament_candidates.inventory_save_error": {
        "ja": "手持ち設定を保存できませんでした: {reason}",
        "en": "Could not save owned-filament settings: {reason}",
    },
    "filament_candidates.set_slot": {
        "ja": "選択製品を{slot}へ",
        "en": "Assign to {slot}",
    },
    "filament_candidates.select_product": {
        "ja": "先にメーカー内の製品を1つ選択してください。",
        "en": "Select one product under a brand first.",
    },
    "filament_candidates.auto_owned": {
        "ja": "手持ちから4色を自動構成",
        "en": "Auto-build Four Colors from Owned",
    },
    "filament_candidates.auto_target": {
        "ja": "適用先: {target}",
        "en": "Target: {target}",
    },
    "filament_candidates.auto_common": {
        "ja": "全体共通",
        "en": "Common palette",
    },
    "filament_candidates.auto_running": {
        "ja": "手持ちフィラメントから4色と混色比率を計算しています…",
        "en": "Building four colors and optimizing mix ratios from owned filaments…",
    },
    "filament_candidates.auto_need_four": {
        "ja": "自動構成には手持ちフィラメントを4製品以上登録してください。現在は{count}製品です。",
        "en": "Auto-build requires at least four owned filament products. Currently registered: {count}.",
    },
    "filament_candidates.auto_missing": {
        "ja": "登録済み製品のうち{count}件が現在のデータベースにありません。手持ち一覧で登録を更新してください。",
        "en": "{count} registered products are missing from the current database. Update the owned inventory list.",
    },
    "filament_candidates.auto_stale_title": {
        "ja": "保存時の色情報を使用",
        "en": "Use Saved Color Snapshots",
    },
    "filament_candidates.auto_stale": {
        "ja": "{count}製品は現在のデータベースにないため、登録時に保存した色情報を使用します。続けますか？",
        "en": "{count} products are no longer in the current database. Use their saved color snapshots and continue?",
    },
    "filament_candidates.auto_same_color": {
        "ja": "登録された製品がすべて同じ表示色のため、4色構成を計算できません。異なる色の製品を追加してください。",
        "en": "All registered products have the same display color. Add products with different colors before auto-building.",
    },
    "filament_candidates.auto_need_distinct": {
        "ja": "自動4色構成には異なる表示色が4色以上必要です。現在は{count}色です。別の色の製品を追加してください。",
        "en": "Auto-build requires at least four distinct display colors. Currently available: {count}. Add products in other colors.",
    },
    "filament_candidates.auto_no_obj": {
        "ja": "先に色付きOBJまたはGLBを開いてください。",
        "en": "Open a colored OBJ or GLB first.",
    },
    "filament_candidates.auto_no_target_faces": {
        "ja": "{target}が実際に反映される面がありません。パーツ別フィラメント設定を確認してください。",
        "en": "No faces currently use {target}. Check the per-part filament settings.",
    },
    "filament_candidates.auto_manual_title": {
        "ja": "手修正の実際の色も変化します",
        "en": "Manual Paint Colors Will Change",
    },
    "filament_candidates.auto_manual_confirm": {
        "ja": "{target}の対象範囲には、手修正または細分塗り分けを含む面が{count}面あります（手修正 {manual}面／細分塗り分け {trees}面）。\n\n基本色F1〜F4と主・追加混色12比率を変更すると、指定した色番号と塗り分け範囲は維持されますが、その実際の色が変わります。\n\n手持ち4色の自動構成を続けますか？",
        "en": "The {target} target contains {count} faces with manual or adaptive paint (manual: {manual}; adaptive paint trees: {trees}).\n\nChanging F1-F4 and all 12 primary/additional mix ratios preserves the assigned state numbers and painted regions, but changes their actual colors.\n\nContinue auto-building four colors from owned filament?",
    },
    "filament_candidates.auto_applied": {
        "ja": "{target}へ手持ち4色を反映し、混色比率の最適化を開始しました。",
        "en": "Applied four owned colors to {target} and started mix-ratio optimization.",
    },
    "filament_candidates.auto_result": {
        "ja": "{target}へ手持ち4色を反映しました: {products}\n主・追加混色12比率を最適化 平均ΔE76 {before:.2f} → {after:.2f}（{improvement:.1f}%改善）",
        "en": "Applied four owned colors to {target}: {products}\nOptimized 12 primary/additional mix ratios: mean ΔE76 {before:.2f} → {after:.2f} ({improvement:.1f}% improvement)",
    },
    "filament_candidates.auto_discarded": {
        "ja": "計算中にモデル、適用先、色調、パレット数、または手持ち設定が変わったため、結果を適用しませんでした。",
        "en": "The result was not applied because the model, target, tone, palette count, or owned inventory changed during calculation.",
    },
    "filament_candidates.auto_warning_title": {
        "ja": "実フィラメントの注意",
        "en": "Physical Filament Notice",
    },
    "filament_candidates.auto_special_finish": {
        "ja": "マット・メタリック・透明・繊維入りなどの特殊質感は、画面上の混色予測と実物がずれる場合があります:\n{products}",
        "en": "Special finishes such as matte, metallic, transparent, or fiber-filled materials may mix differently from the on-screen prediction:\n{products}",
    },
    "filament_candidates.auto_duplicate_colors": {
        "ja": "同じHEX色の手持ち製品は、自動構成では各色1製品として計算しました。",
        "en": "Owned products with the same HEX color were treated as one color during auto-build.",
    },
    "filament_candidates.searching": {
        "ja": "データベースを検索しています…",
        "en": "Searching the database…",
    },
    "filament_candidates.current": {
        "ja": "現在 {color}",
        "en": "Current {color}",
    },
    "filament_candidates.product": {
        "ja": "メーカー / シリーズ / 色名",
        "en": "Brand / Series / Color",
    },
    "filament_candidates.hex": {"ja": "候補HEX", "en": "Candidate HEX"},
    "filament_candidates.delta": {"ja": "ΔE00", "en": "ΔE00"},
    "filament_candidates.source": {"ja": "データ", "en": "Data"},
    "filament_candidates.none": {
        "ja": "条件に合う候補がありません",
        "en": "No candidates match these filters",
    },
    "filament_candidates.apply": {"ja": "この色を反映", "en": "Apply This Color"},
    "filament_candidates.confirm_title": {
        "ja": "基本フィラメント色を変更",
        "en": "Change Base Filament Color",
    },
    "filament_candidates.confirm_message": {
        "ja": "{slot}を {current} から {candidate} へ変更しますか？\n\n{brand} / {series} / {name}\nΔE00 {delta:.2f} / {source}",
        "en": "Change {slot} from {current} to {candidate}?\n\n{brand} / {series} / {name}\nΔE00 {delta:.2f} / {source}",
    },
    "filament_candidates.applied": {
        "ja": "{slot}へ{color}を反映しました（{brand} / {name}）",
        "en": "Applied {color} to {slot} ({brand} / {name})",
    },
    "filament_candidates.source_measured": {"ja": "実測", "en": "Measured"},
    "filament_candidates.source_catalog": {"ja": "カタログ", "en": "Catalog"},
    "filament_candidates.source_snapshot": {"ja": "保存情報", "en": "Saved snapshot"},
    "filament_candidates.finish.carbon_fiber": {"ja": "カーボン繊維", "en": "Carbon Fiber"},
    "filament_candidates.finish.glass_fiber": {"ja": "ガラス繊維", "en": "Glass Fiber"},
    "filament_candidates.finish.silk_metallic_glossy": {
        "ja": "シルク/メタリック/光沢",
        "en": "Silk / Metallic / Glossy",
    },
    "filament_candidates.finish.matte": {"ja": "マット", "en": "Matte"},
    "filament_candidates.finish.marble_stone": {
        "ja": "マーブル/ストーン",
        "en": "Marble / Stone",
    },
    "filament_candidates.finish.wood": {"ja": "木質", "en": "Wood-filled"},
    "filament_candidates.finish.standard_opaque": {
        "ja": "標準/不透明",
        "en": "Standard / Opaque",
    },
    "filament_candidates.finish.foaming_lw": {
        "ja": "発泡/LW",
        "en": "Foaming / Lightweight",
    },
    "filament_candidates.finish.glow": {"ja": "蓄光", "en": "Glow-in-the-dark"},
    "filament_candidates.finish.transparent": {
        "ja": "透明/半透明",
        "en": "Transparent / Translucent",
    },
    "filament_candidates.unavailable": {
        "ja": "フィラメント候補データベースを利用できません。モデル変換や色調整など、ほかの機能はそのまま使用できます。",
        "en": "The filament candidate database is unavailable. Model conversion, color editing, and all other features remain available.",
    },
    "filament_candidates.reason": {
        "ja": "理由: {reason}",
        "en": "Reason: {reason}",
    },
    "filament_candidates.error": {
        "ja": "候補を取得できませんでした: {reason}",
        "en": "Could not retrieve candidates: {reason}",
    },
    "filament_candidates.move_hint": {
        "ja": "このウィンドウは比較プレビューを隠さない位置や別モニターへ移動できます。",
        "en": "Move this window beside the comparison preview or onto another monitor.",
    },
    # Tone
    "tone.intro": {
        "ja": "モデル上の陰影を最大32色へ割り当てる前に調整します。",
        "en": "Adjust shading before mapping the model to up to 32 colors.",
    },
    "tone.black_point": {"ja": "黒点", "en": "Black Point"},
    "tone.white_point": {"ja": "白点", "en": "White Point"},
    "tone.gamma": {"ja": "ガンマ", "en": "Gamma"},
    "tone.contrast": {"ja": "コントラスト", "en": "Contrast"},
    "tone.saturation": {"ja": "彩度", "en": "Saturation"},
    "tone.protect_f4": {"ja": "赤みの強い領域をF4系で保護（任意）", "en": "Protect strong red areas with F4 mixes (optional)"},
    "tone.f4_threshold": {"ja": "F4系保護の判定", "en": "F4 Protection Threshold"},
    "tone.smoothing": {"ja": "微小な色飛びを近傍へ統合", "en": "Merge tiny color islands into neighbors"},
    "tone.smoothing_area": {"ja": "統合面積 mm²", "en": "Merge Area mm²"},
    "tone.delta_e": {"ja": "許容 ΔE", "en": "Allowed ΔE"},
    "tone.optimize_help": {
        "ja": "現在の基本4色を使い、モデルの陰影に合う混色比率を求めます。",
        "en": "Find mixing ratios that reproduce the model shading using the current four base colors.",
    },
    "tone.optimize": {"ja": "陰影を混色に反映（自動最適化）", "en": "Map Shading to Mixes (Auto Optimize)"},
    "tone.undo_optimize": {"ja": "直前の混色最適化を元に戻す", "en": "Undo Last Mix Optimization"},
    "tone.reset": {"ja": "陰影設定を初期値へ戻す", "en": "Reset Shading Settings"},
    # Geometry and assembly
    "geometry.height": {"ja": "出力高さ mm", "en": "Output Height mm"},
    "geometry.final_faces": {"ja": "最終面数", "en": "Final Face Count"},
    "geometry.preview_faces": {"ja": "プレビュー面数", "en": "Preview Face Count"},
    "geometry.min_component": {"ja": "微小部品の下限面数", "en": "Minimum Small-Part Faces"},
    "geometry.up_axis": {"ja": "Tripoの上方向", "en": "Tripo Up Axis"},
    "geometry.mirror": {"ja": "左右を反転", "en": "Mirror Left/Right"},
    "geometry.backup_obj": {"ja": "予備の頂点カラーOBJも保存", "en": "Also Save Backup Vertex-Color OBJ"},
    "geometry.adjust_face_count": {"ja": "面数調整を適用", "en": "Apply Face Count Adjustment"},
    "geometry.restore_original_faces": {"ja": "元の面数へ戻す", "en": "Restore Original Face Count"},
    "geometry.face_status_waiting_adjusted": {
        "ja": "現在: 面数調整を使用（モデル読込後に結果を表示）",
        "en": "Current: face count adjustment enabled (results appear after model import)",
    },
    "geometry.face_status_waiting_preserved": {
        "ja": "現在: 原形状の面数を保持（プレビューのみ軽量化）",
        "en": "Current: preserve original geometry faces (preview remains lightweight)",
    },
    "geometry.face_status_source": {
        "ja": "読込元 {source:,}面（再処理後に最終状態を表示）",
        "en": "Source {source:,} faces (final status appears after reprocessing)",
    },
    "geometry.face_status_adjusted": {
        "ja": "調整あり: 元 {source:,} / 整理後 {clean:,} / 最終 {final:,}面",
        "en": "Adjusted: source {source:,} / clean {clean:,} / final {final:,} faces",
    },
    "geometry.face_status_preserved": {
        "ja": "調整なし: 元 {source:,} / 整理後・最終 {clean:,} / {final:,}面",
        "en": "Not adjusted: source {source:,} / clean and final {clean:,} / {final:,} faces",
    },
    "geometry.manual_high_faces_title": {
        "ja": "高面数モデルのマニュアル修正",
        "en": "Manual Editing for a High-Face Model",
    },
    "geometry.manual_high_faces_warning": {
        "ja": "このモデルは面数調整なしで {count:,}面あります。形状品質は維持されますが、マニュアル修正の表示やブラシ操作が重くなる場合があります。\n\nこのまま開きますか？",
        "en": "This model has {count:,} faces without face-count adjustment. Geometry quality is preserved, but Manual Editing and brush interaction may be slower.\n\nOpen it anyway?",
    },
    "geometry.reprocess": {"ja": "この設定で形状を再処理", "en": "Reprocess Geometry with These Settings"},
    "geometry.reprocess_help": {
        "ja": "面数・上方向・反転を変更した場合は再処理が必要です。高さだけの変更はすぐ反映されます。",
        "en": "Face count, up axis, and mirroring require reprocessing. Height changes apply immediately.",
    },
    "assembly.intro": {
        "ja": "元のパーツ構成と色を保って開きます。必要な場合だけ［閉立体化］で印刷用の閉立体にします。",
        "en": "Open while preserving the original parts and colors. Use [Solidify] only when a closed printable model is needed.",
    },
    "assembly.local": {"ja": "パーツ認識・境界診断・閉立体化はPC内で行います（通信・Codex不要）。", "en": "Part detection, boundary diagnostics, and solidification run locally (no Codex or network required)."},
    "assembly.keep_raw": {"ja": "元パーツのまま開く／戻す", "en": "Keep / Restore Original Open Parts"},
    "assembly.solidify_now": {"ja": "パーツを閉立体化", "en": "Solidify Parts"},
    "assembly.show_diagnostics": {"ja": "開口境界を3Dで確認", "en": "Inspect Open Boundaries in 3D"},
    "assembly.repair_small_holes": {"ja": "微小な問題境界を修復して閉じる β", "en": "Repair Tiny Problem Boundaries and Close β"},
    "assembly.close_safely": {
        "ja": "閉立体化",
        "en": "Solidify",
    },
    "paint.front_visible_guard": {
        "ja": "表示中の面と選択パーツ内だけに適用",
        "en": "Affect visible faces in the selected part only",
    },
    "assembly.status_no_model": {"ja": "モデル読込後に印刷形状の状態を表示します。", "en": "Print-geometry status appears after opening a model."},
    "assembly.status_single_model": {"ja": "パーツ情報なし: 1モデルとして保持", "en": "No part markers: retained as one model"},
    "assembly.status_open": {"ja": "元パーツ {parts}個を保持（未閉立体）\n開口 {loops} / 対応済み {seams}組 / 要確認 {unmatched}", "en": "Original {parts} parts retained (not solid)\nOpen loops {loops} / matched seams {seams} / needs review {unmatched}"},
    "assembly.status_closed": {"ja": "閉立体化済み: {parts}パーツ / 微小開口修復 {repaired}箇所", "en": "Solidified: {parts} parts / tiny openings repaired {repaired}"},
    "assembly.status_closed_single_glb": {"ja": "閉立体化済み: GLBのUV/テクスチャ継ぎ目を統合（穴埋めによる形状追加なし）", "en": "Solidified: GLB UV/texture seams welded (no invented cap geometry)"},
    "assembly.raw_already_active": {"ja": "元パーツを保った未閉立体の状態です", "en": "The original open-part state is already active"},
    "assembly.diagnostics_title": {"ja": "開口境界の診断", "en": "Open-Boundary Diagnostics"},
    "assembly.no_open_boundaries": {"ja": "3Dで確認する開口境界はありません。", "en": "There are no open boundaries to inspect in 3D."},
    "assembly.solidify_title": {"ja": "パーツの閉立体化", "en": "Part Solidification"},
    "assembly.single_model_unchanged": {"ja": "Tripoの明示パーツ情報がないため、この操作では形状を変更しません。", "en": "This OBJ has no explicit Tripo part data, so this action will not change its geometry."},
    "assembly.already_closed": {"ja": "すべての印刷パーツは既に閉じています", "en": "All print parts are already closed"},
    "assembly.solidify_stopped_title": {"ja": "閉立体化を安全停止", "en": "Solidification Stopped Safely"},
    "assembly.solidify_stopped_unmatched": {"ja": "対応相手のない開口が {count}箇所あります。誤った蓋で形状を変えないよう処理は開始せず、元パーツを保持しました。\n\nマニュアル修正を開き、赤い問題境界を確認します。小さな穴だけなら［微小な問題境界を修復して閉じる β］を使用できます。", "en": "There are {count} open boundaries without a matching partner. To avoid changing the model with an incorrect cap, processing was not started and the original parts were retained.\n\nManual Editing will open with problem boundaries in red. For tiny holes only, use Repair Tiny Problem Boundaries and Close β."},
    "assembly.repair_confirm_title": {"ja": "微小開口を修復して閉じる β", "en": "Repair Tiny Openings and Close β"},
    "assembly.repair_confirm": {"ja": "要確認の開口 {count}箇所（最大幅 {largest:.3f} mm）へ局所的な蓋を作り、その後に元のパーツ構成を保って閉立体化します。\n\n幅2.0 mm以下で平面性を確認できた小穴だけが対象です。大きい欠損・自己交差・危険な形状は変更せず安全停止します。続けますか？", "en": "Create local caps for {count} openings needing review (largest span {largest:.3f} mm), then solidify while preserving the original part structure.\n\nOnly planar tiny holes up to 2.0 mm are eligible. Large gaps, self-intersections, or unsafe geometry remain unchanged and stop safely. Continue?"},
    "assembly.solidify_failed_kept_raw": {"ja": "閉立体化を安全停止し、読み込んだ元パーツを保持しました", "en": "Solidification stopped safely; the imported original parts were retained"},
    "assembly.solidify_failed_detail": {"ja": "閉立体化を完了できませんでしたが、読み込んだ元パーツ・色・手修正は失われていません。\n\n{error}\n\n開口境界を3Dで確認しますか？", "en": "Solidification could not finish, but the imported original parts, colors, and manual edits were preserved.\n\n{error}\n\nInspect the open boundaries in 3D?"},
    "assembly.export_blocked_title": {"ja": "未閉立体のため3MF出力を停止", "en": "3MF Export Blocked: Parts Are Open"},
    "assembly.export_blocked_open": {"ja": "境界エッジが {boundaries}本残っています（要確認 {unmatched}箇所）。Snapmaker Orca側の自動修復で色や形状を失わないよう、3MFはまだ出力しません。\n\n［パーツ処理］で閉立体化または修復してください。開口を3Dで確認しますか？", "en": "{boundaries} boundary edges remain ({unmatched} need review). To prevent Snapmaker Orca repair from losing colors or altering the shape, 3MF export has not started.\n\nSolidify or repair the model under Part Processing. Inspect the openings in 3D now?"},
    "assembly.export_auto_solidify_title": {
        "ja": "未閉立体を自動閉立体化して3MF出力",
        "en": "Automatically Solidify Before 3MF Export",
    },
    "assembly.export_auto_solidify_confirm": {
        "ja": "境界エッジが {boundaries}本残っています。\n\nChromaMatterが、対応を安全確認できたパーツ境界またはGLBの同一座標継ぎ目だけを自動で閉立体化し、成功後に3MF出力を再開します。実際の穴と判断した開口へ自動で蓋は作りません。\n\n閉立体化して出力を続けますか？",
        "en": "{boundaries} boundary edges remain.\n\nChromaMatter will automatically solidify only safely matched part boundaries or coincident GLB seams, then resume 3MF export after it succeeds. It will not automatically cap openings identified as real holes.\n\nSolidify and continue export?",
    },
    "assembly.export_auto_solidify_running": {
        "ja": "3MF出力前に安全な閉立体化を実行しています",
        "en": "Safely solidifying the model before 3MF export",
    },
    "assembly.export_auto_solidify_cancelled": {
        "ja": "自動閉立体化をキャンセルしました。元の形状・色・手修正は保持されています",
        "en": "Automatic solidification was cancelled. The original geometry, colors, and manual edits are preserved",
    },
    "assembly.export_auto_solidify_unsafe_title": {
        "ja": "実際の開口を検出したため3MF出力を安全停止",
        "en": "3MF Export Stopped Safely: Real Openings Detected",
    },
    "assembly.export_auto_solidify_unsafe": {
        "ja": "対応相手のない開口が {unmatched}箇所あります（境界エッジ {boundaries}本）。誤った蓋で形状を変えないよう、3MF出力時の自動閉立体化では塞ぎません。元の形状・色・手修正は保持されています。\n\n赤い問題境界を確認し、実際の欠損を元モデルで修正してください。微小な穴だと確認できる場合だけ、［出力設定］の［閉立体化］から明示的に修復できます。",
        "en": "There are {unmatched} openings without matching partners ({boundaries} boundary edges). Export-time automatic solidification will not cap them, avoiding an incorrect shape change. The original geometry, colors, and manual edits are preserved.\n\nInspect the red problem boundaries and repair real missing surfaces in the source model. Only when you have confirmed they are tiny holes, use [Solidify] under Output Settings to explicitly request repair.",
    },
    "assembly.export_auto_solidify_unsupported_title": {
        "ja": "このモデルは自動閉立体化できません",
        "en": "This Model Cannot Be Automatically Solidified",
    },
    "assembly.export_auto_solidify_unsupported": {
        "ja": "境界エッジが {boundaries}本残っています。このOBJには安全に対応付けられる複数パーツ境界がないため、ChromaMatterは推測で穴を塞ぎません。元の形状・色・手修正は保持されています。\n\n元モデル側で開口を閉じてから、形状を再処理してください。",
        "en": "{boundaries} boundary edges remain. This OBJ has no multipart boundaries that can be matched safely, so ChromaMatter will not guess how to cap the holes. The original geometry, colors, and manual edits are preserved.\n\nClose the openings in the source model, then reprocess the geometry.",
    },
    "assembly.export_auto_solidify_incomplete_title": {
        "ja": "閉立体化を完了できないため3MF出力を安全停止",
        "en": "3MF Export Stopped Safely: Solidification Incomplete",
    },
    "assembly.export_auto_solidify_incomplete": {
        "ja": "閉立体化後も境界エッジが {boundaries}本残っています（要確認 {unmatched}箇所）。未閉立体の3MFは出力しません。元の形状・色・手修正は保持されています。",
        "en": "{boundaries} boundary edges remain after solidification ({unmatched} need review). An open 3MF will not be exported. The original geometry, colors, and manual edits are preserved.",
    },
    "assembly.export_auto_solidify_inspect": {
        "ja": "\n\n開口境界を3Dで確認しますか？",
        "en": "\n\nInspect the open boundaries in 3D?",
    },
    "assembly.export_auto_solidify_stopped": {
        "ja": "未閉立体のため3MF出力を安全停止しました。元の状態は保持されています",
        "en": "3MF export stopped safely because the model is open. The original state is preserved",
    },
    "assembly.auto_joints": {"ja": "安全な継ぎ目だけ組立ジョイントを自動生成", "en": "Generate Assembly Joints Only on Safe Seams"},
    "assembly.clear_manual_joint": {"ja": "手動ジョイントを解除して再処理", "en": "Remove Manual Joint and Reprocess"},
    "assembly.no_manual_joint": {"ja": "解除する手動ジョイントはありません", "en": "There is no manual joint to remove"},
    "assembly.clear_manual_joint_confirm": {
        "ja": "手動ジョイントを解除し、元モデルから形状を再生成します。ジョイント形状に対するブラシ修正も解除されます。続けますか？",
        "en": "Remove the manual joint and rebuild from the source model? Paint edits made on the joint topology will also be cleared.",
    },
    "assembly.joints_help": {"ja": "余白が小さい、または強く曲がった継ぎ目は自動で省略します。", "en": "Seams with little clearance or strong curvature are skipped automatically."},
    "assembly.individual_3mf": {"ja": "各印刷パーツを個別3MFでも保存", "en": "Also Save Each Print Part as an Individual 3MF"},
    "assembly.layer_height": {
        "ja": "Snapmaker Orcaへ渡す積層ピッチ: 0.08 mm（固定）\n通常の固定レイヤー混色＋公式リブ型プライムタワーを記録。サポートはOrca側で選択できます。",
        "en": "Layer height sent to Snapmaker Orca: 0.08 mm (fixed)\nRecords stable fixed-layer mixing plus the official rib prime tower. Supports remain selectable in Orca.",
    },
    "assembly.processing_help": {
        "ja": "強く曲がった境界の閉立体化は、モデル規模により数分かかります。計算中も処理はPC内だけで行われます。",
        "en": "Solidifying strongly curved boundaries may take several minutes depending on model size. All computation stays on this PC.",
    },
    # Preview and recipes
    "preview.compare": {"ja": "比較", "en": "Compare"},
    "preview.columns": {"ja": "元画像  ｜  AIモデル色  ｜  Full Spectrum変換色", "en": "Reference  |  AI Model Color  |  Full Spectrum Color"},
    "preview.recipe_group": {"ja": "スポイト色の再現候補（公式混色モデルによる予測）", "en": "Sampled Color Recipes (Official Mixing Model Prediction)"},
    "preview.reference": {"ja": "元画像（スポイト対象）", "en": "Reference (Eyedropper)"},
    "preview.source": {"ja": "AIモデル色", "en": "AI Model Color"},
    "preview.target": {"ja": "Full Spectrum 変換色", "en": "Full Spectrum Color"},
    "preview.open_reference": {"ja": "元画像を開いてください", "en": "Open a reference image"},
    "preview.process_obj": {"ja": "モデルを処理すると表示されます", "en": "Shown after processing a model"},
    "preview.target_placeholder": {"ja": "変換色プレビュー", "en": "Converted Color Preview"},
    "preview.click_reference": {"ja": "元画像をクリックして色を取得", "en": "Click the reference image to sample a color"},
    "recipe.colors": {"ja": "使用色", "en": "Colors"},
    "recipe.ratio": {"ja": "比率 A : B", "en": "Ratio A : B"},
    "recipe.predicted": {"ja": "予測色", "en": "Predicted"},
    "recipe.guide": {"ja": "目安", "en": "Quality"},
    "recipe.apply": {"ja": "選択レシピを\n混色スロットへ反映", "en": "Apply Selected Recipe\nto Mix Slot"},
    "recipe.direct_none": {"ja": "基本色の近似: 未取得", "en": "Nearest Base Color: Not Sampled"},
    "recipe.very_close": {"ja": "かなり近い", "en": "Very close"},
    "recipe.close": {"ja": "近い", "en": "Close"},
    "recipe.test_print": {"ja": "要試刷り", "en": "Test print"},
    "recipe.difficult": {"ja": "4色では難しい", "en": "Difficult with 4 colors"},
    # Initial and stable status text
    "state.select_inputs": {"ja": "OBJまたはGLBと元画像を選択してください", "en": "Select an OBJ or GLB model and reference image"},
    "state.obj_none": {"ja": "モデル: 未選択", "en": "MODEL: Not selected"},
    "state.source_selected": {"ja": "モデル: {name}", "en": "MODEL: {name}"},
    "state.reference_none": {"ja": "元画像: 未選択", "en": "Reference: Not selected"},
    "state.not_sampled": {"ja": "未取得", "en": "Not sampled"},
    "state.parts_hint": {"ja": "モデル読込後にパーツを表示", "en": "Parts appear after opening a model"},
    "state.recommend_hint": {"ja": "モデルの色から原色・無彩色・肌色系を提案できます", "en": "Recommend primaries, neutrals, and skin-tone filaments from model colors"},
    "state.parts_detected_hint": {"ja": "モデル読込後にパーツを表示", "en": "Parts appear after opening a model"},
    "state.calibration_exporting": {
        "ja": "現在のパレットから実機比較チャートを生成しています…",
        "en": "Creating a physical comparison chart from the current palette…",
    },
    "state.calibration_done": {
        "ja": "実機比較チャートを生成しました（{count}色）: {folder}",
        "en": "Created a {count}-state physical comparison chart: {folder}",
    },
    "state.calibration_error": {
        "ja": "実機比較チャートを生成できません: {reason}",
        "en": "Could not create the physical comparison chart: {reason}",
    },
    "parts.common_short": {"ja": "共通", "en": "Common"},
    "parts.individual_short": {"ja": "個別", "en": "Individual"},
    # Common dialogs
    "dialog.settings.title": {"ja": "設定を確認してください", "en": "Check Settings"},
    "dialog.obj_required.title": {"ja": "モデルが必要です", "en": "Model Required"},
    "dialog.obj_required.open": {"ja": "先にOBJまたはGLBを開いてください。", "en": "Open an OBJ or GLB model first."},
    "dialog.obj_required.process": {"ja": "先にOBJまたはGLBを開き、形状処理を完了してください。", "en": "Open an OBJ or GLB model and finish geometry processing first."},
    "dialog.obj_required.optimize": {"ja": "先にOBJまたはGLBを開いてください。モデル全体の陰影分布から混色比率を求めます。", "en": "Open an OBJ or GLB model first. Mix ratios are optimized from shading across the whole model."},
    "dialog.busy.title": {"ja": "処理中です", "en": "Processing"},
    "dialog.busy.message": {"ja": "現在の処理が終わってから実行してください。", "en": "Wait for the current operation to finish."},
    "dialog.busy.open_obj": {"ja": "現在の処理が終わってから別のモデルを開いてください。", "en": "Wait for the current operation to finish before opening another model."},
    "dialog.source_format.title": {"ja": "対応していないモデル形式です", "en": "Unsupported Model Format"},
    "dialog.source_format.message": {"ja": "現在読み込める形式は、頂点カラーOBJとGLBです。", "en": "The supported source formats are vertex-color OBJ and GLB."},
    "dialog.no_sample.title": {"ja": "色が未取得です", "en": "No Color Sampled"},
    "dialog.no_sample.message": {"ja": "スポイトで元画像の色をクリックしてください。", "en": "Use the eyedropper to click a color in the reference image."},
    "dialog.no_recipe.title": {"ja": "候補がありません", "en": "No Recipe Available"},
    "dialog.open_image_error": {"ja": "画像を開けません", "en": "Could Not Open Image"},
    "dialog.open_paint_error": {"ja": "マニュアル修正を開けません", "en": "Could Not Open Manual Editing"},
    "dialog.launch_orca_error": {"ja": "Snapmaker Orcaを起動できません", "en": "Could Not Launch Snapmaker Orca"},
    "dialog.process_error": {"ja": "処理できませんでした", "en": "Processing Failed"},
    "dialog.calibration_done.title": {
        "ja": "実機比較チャートを生成しました",
        "en": "Physical Comparison Chart Created",
    },
    "dialog.calibration_done.message": {
        "ja": "{folder}\n\n{count}色の3MF、対応表、印刷手順、パレット記録、検証結果を保存しました。\nSnapmaker Orcaでは3MFを『プロジェクトとして開く』で開いてください。\n\n保存フォルダーを開きますか？",
        "en": "{folder}\n\nSaved the {count}-state 3MF, mapping table, print guide, palette snapshot, and validation report.\nIn Snapmaker Orca, open the 3MF as a project.\n\nOpen the saved folder?",
    },
    "dialog.calibration_error.title": {
        "ja": "実機比較チャートを生成できません",
        "en": "Could Not Create Physical Comparison Chart",
    },
    "dialog.calibration_error.message": {
        "ja": "F1～F4、混色比率、保存先を確認してください。\n\n{reason}",
        "en": "Check F1-F4, the mix ratios, and the destination folder.\n\n{reason}",
    },
    "dialog.calibration_folder_error.title": {
        "ja": "保存フォルダーを開けません",
        "en": "Could Not Open Saved Folder",
    },
    "dialog.calibration_folder_error.message": {
        "ja": "チャートは保存されていますが、フォルダーを開けませんでした。\n\n{reason}",
        "en": "The chart was saved, but its folder could not be opened.\n\n{reason}",
    },
    "filedialog.all": {"ja": "すべて", "en": "All Files"},
    "filedialog.model": {"ja": "3Dモデル（OBJ / GLB）", "en": "3D Model (OBJ / GLB)"},
    "filedialog.model_short": {"ja": "モデル", "en": "model"},
    "filedialog.image": {"ja": "画像", "en": "Images"},
    "filedialog.executable": {"ja": "実行ファイル", "en": "Executable"},
    "filedialog.open_obj": {"ja": "頂点カラーOBJまたはGLBを選択", "en": "Select a Vertex-Color OBJ or GLB Model"},
    "filedialog.open_reference": {"ja": "元画像を選択", "en": "Select Reference Image"},
    "filedialog.save_project": {"ja": "調整プロジェクトを保存", "en": "Save Adjustment Project"},
    "filedialog.load_project": {"ja": "調整プロジェクトを読み込む", "en": "Load Adjustment Project"},
    "project.save_choose_parent": {
        "ja": "プロジェクトフォルダーの保存先を選択",
        "en": "Choose Where to Save the Project Folder",
    },
    "project.load_choose_folder": {
        "ja": "保存したプロジェクトフォルダーを選択",
        "en": "Select a Saved Project Folder",
    },
    "project.menu_open_folder": {
        "ja": "プロジェクトフォルダーを開く（推奨）",
        "en": "Open Project Folder (Recommended)",
    },
    "project.menu_open_legacy_json": {
        "ja": "旧JSONを開く…",
        "en": "Open Legacy JSON…",
    },
    "project.load_choose_legacy_json": {
        "ja": "旧形式のプロジェクトJSONを選択",
        "en": "Select a Legacy Project JSON",
    },
    "project.source_required_title": {
        "ja": "先にOBJまたはGLBを開いてください",
        "en": "Open an OBJ or GLB First",
    },
    "project.source_required_message": {
        "ja": "プロジェクトは、元モデル・設定・手修正を1つのフォルダーへまとめて保存します。先にOBJまたはGLBを開いて形状準備を完了してください。",
        "en": "A project stores the source model, settings, and manual edits together in one folder. Open an OBJ or GLB and finish geometry preparation first.",
    },
    "project.geometry_outdated_title": {
        "ja": "形状設定を反映してください",
        "en": "Apply the Geometry Settings First",
    },
    "project.geometry_outdated_message": {
        "ja": "画面の形状設定と現在の3D形状が一致していません。［出力設定］の［この設定で形状を再処理］を実行してから保存してください。",
        "en": "The visible geometry settings do not match the prepared 3D shape. Run Reprocess Geometry with These Settings on Output Settings before saving.",
    },
    "project.save_working": {
        "ja": "元モデルと手修正をプロジェクトフォルダーへ保存しています",
        "en": "Saving the source model and manual edits to a project folder",
    },
    "project.saved": {
        "ja": "プロジェクトを保存しました: {name}",
        "en": "Project saved: {name}",
    },
    "project.save_error": {
        "ja": "プロジェクトを保存できません",
        "en": "Could Not Save Project",
    },
    "project.load_error": {
        "ja": "プロジェクトを読み込めません",
        "en": "Could Not Load Project",
    },
    "project.restore_working": {
        "ja": "保存時の形状と手修正を復元しています",
        "en": "Restoring the saved geometry and manual edits",
    },
    "project.loaded_exact": {
        "ja": "プロジェクトを復元しました: {name} / 手修正 {faces:,}面",
        "en": "Project restored: {name} / {faces:,} manually edited faces",
    },
    "project.legacy_choose_obj": {
        "ja": "旧プロジェクトの元モデルを選択: {name}",
        "en": "Select the Source Model for This Legacy Project: {name}",
    },
    "project.legacy_pending_title": {
        "ja": "元モデルが必要です",
        "en": "Source Model Required",
    },
    "project.legacy_pending_message": {
        "ja": "旧形式のJSONには元モデル本体が含まれていません。［OBJ / GLBを開く］で保存時と同じモデルを選ぶと、形状指紋を確認して手修正を復元します。",
        "en": "A legacy JSON does not contain its source model. Use Open OBJ / GLB to select the same model used when it was saved; the app will verify its geometry fingerprint before restoring manual edits.",
    },
    "project.ignored_legacy_title": {
        "ja": "旧版の分割・ジョイントは読み込みません",
        "en": "Legacy Split and Joint Data Was Ignored",
    },
    "project.ignored_legacy_message": {
        "ja": "公開版では分割・ジョイント編集を廃止したため、その記録は安全のため適用していません。元モデル・色設定・手塗りは引き続き読み込みます。",
        "en": "Split and joint editing was retired from the public edition, so those records were not applied. The source model, color settings, and manual paint are still loaded.",
    },
    "filedialog.save_3mf": {"ja": "Snapmaker Full Spectrum用3MFを保存", "en": "Save 3MF for Snapmaker Full Spectrum"},
    "filedialog.save_radial_3mf": {
        "ja": "完全ラジアル実験3MFを保存",
        "en": "Save Full-Radial Laboratory 3MF",
    },
    "filedialog.save_color_depth_3mf": {
        "ja": "ColorDepth SLICE ONLY 3MFを保存",
        "en": "Save ColorDepth SLICE ONLY 3MF",
    },
    "filedialog.open_color_depth_part_3mf": {
        "ja": "変換元の通常パーツ別3MFを選択",
        "en": "Select a Normal Per-Part 3MF to Convert",
    },
    "filedialog.save_converted_color_depth_3mf": {
        "ja": "変換したColorDepth SLICE ONLY 3MFを別名で保存",
        "en": "Save Converted ColorDepth SLICE ONLY 3MF As",
    },
    "filedialog.save_calibration_folder": {
        "ja": "実機比較チャートの保存先フォルダーを選択",
        "en": "Choose a Folder for the Physical Comparison Chart",
    },
    "filedialog.select_orca": {"ja": "Snapmaker Orcaの実行ファイルを選択", "en": "Select the Snapmaker Orca Executable"},
    # Paint editor (the editor inherits the selected app language when opened)
    "paint.title": {"ja": "マニュアル修正", "en": "Manual Editing"},
    "paint.orbit": {"ja": "回転", "en": "Orbit"},
    "paint.brush": {"ja": "ブラシ", "en": "Brush"},
    "paint.airbrush": {"ja": "エアブラシ", "en": "Airbrush"},
    "paint.eyedropper_3d": {"ja": "3Dスポイト", "en": "3D Eyedropper"},
    "paint.smudge": {"ja": "なじませ", "en": "Smudge"},
    "paint.fill": {"ja": "塗りつぶし", "en": "Fill"},
    "paint.smooth": {"ja": "境界ならし", "en": "Smooth Boundary"},
    "paint.erase": {"ja": "自動色へ戻す", "en": "Restore Automatic Color"},
    "paint.pick_reference": {"ja": "元画像スポイト", "en": "Reference Eyedropper"},
    "paint.undo": {"ja": "元に戻す", "en": "Undo"},
    "paint.redo": {"ja": "やり直す", "en": "Redo"},
    "paint.clear": {"ja": "全修正を解除", "en": "Clear All Corrections"},
    "paint.front": {"ja": "正面に戻す", "en": "Reset Front View"},
    "paint.edit_part": {"ja": "編集パーツ", "en": "Edit Part"},
    "paint.ribbon_home": {"ja": "ホーム", "en": "Home"},
    "paint.ribbon_brush": {"ja": "ブラシ・色", "en": "Brush & Color"},
    "paint.ribbon_shading": {"ja": "陰影", "en": "Shading"},
    "paint.ribbon_decal": {"ja": "デカール β", "en": "Decal β"},
    "paint.ribbon_parts": {"ja": "パーツ", "en": "Parts"},
    "paint.ribbon_shape": {"ja": "分割・ジョイント", "en": "Split & Joint"},
    "paint.ribbon_view": {"ja": "表示", "en": "View"},
    "paint.ribbon_expand": {"ja": "リボンを展開", "en": "Expand Ribbon"},
    "paint.ribbon_collapse": {"ja": "リボンを収納", "en": "Collapse Ribbon"},
    "paint.ribbon_hint": {
        "ja": "タブを選ぶと操作を表示します。Ctrl+F1でリボンを展開・収納できます。",
        "en": "Choose a tab to show its controls. Press Ctrl+F1 to expand or collapse the ribbon.",
    },
    "decal.import": {"ja": "PNG / SVGを開く", "en": "Open PNG / SVG"},
    "decal.source_none": {"ja": "画像未選択", "en": "No image selected"},
    "decal.source_loaded": {
        "ja": "{name}  {width}×{height}",
        "en": "{name}  {width}×{height}",
    },
    "decal.mode": {"ja": "色", "en": "Color"},
    "decal.mode_image": {
        "ja": "画像色 → 有効色へ",
        "en": "Image → Enabled Colors",
    },
    "decal.mode_selected": {
        "ja": "現在の選択色で単色",
        "en": "Current Selected Color",
    },
    "decal.x": {"ja": "横位置", "en": "X"},
    "decal.y": {"ja": "縦位置", "en": "Y"},
    "decal.size": {"ja": "幅", "en": "Width"},
    "decal.rotation": {"ja": "回転", "en": "Rotate"},
    "decal.x_unit": {"ja": "横位置 (%)", "en": "X (%)"},
    "decal.y_unit": {"ja": "縦位置 (%)", "en": "Y (%)"},
    "decal.size_unit": {"ja": "幅 (mm)", "en": "Width (mm)"},
    "decal.rotation_unit": {"ja": "回転 (°)", "en": "Rotate (°)"},
    "decal.flip_x": {"ja": "左右反転", "en": "Flip H"},
    "decal.flip_y": {"ja": "上下反転", "en": "Flip V"},
    "decal.opacity": {"ja": "不透明度", "en": "Opacity"},
    "decal.opacity_image_only": {
        "ja": "画像色モードのみ",
        "en": "Image mode only",
    },
    "decal.preview": {"ja": "プレビュー", "en": "Preview"},
    "decal.apply": {"ja": "適用", "en": "Apply"},
    "decal.cancel": {"ja": "取消", "en": "Cancel"},
    "decal.undo": {"ja": "デカールを1回戻す", "en": "Undo Decal Once"},
    "decal.overwrite": {
        "ja": "既存の手修正を上書き",
        "en": "Overwrite Existing Manual Paint",
    },
    "decal.protect_help": {
        "ja": "既定では手塗り・面内グラデーションを保護します",
        "en": "Manual paint and in-face gradients are protected by default.",
    },
    "decal.beta_help": {
        "ja": "β: 見えている編集中パーツだけへ投影し、輪郭裏へ回り込みません。透明部分はマスクです。保存解像度では細線が結合する場合があります。",
        "en": "β: visible active part only; no wrap behind the silhouette. Alpha is a mask. Fine lines may merge at bake resolution.",
    },
    "decal.image_mode_help": {
        "ja": "画像色 → 現在有効な16 / 24 / 32色。不透明度は下地色と合成して確定します。",
        "en": "Image colors → enabled 16 / 24 / 32 states; opacity blends with the current surface before baking.",
    },
    "decal.selected_mode_help": {
        "ja": "透明部分だけをマスクにして、現在の選択色を不透明で適用します。",
        "en": "Uses only image transparency as a mask and applies the current selected color opaquely.",
    },
    "decal.ready": {
        "ja": "画像を配置して［プレビュー］を押してください",
        "en": "Place the image, then choose Preview",
    },
    "decal.loading": {"ja": "画像を安全確認中…", "en": "Checking image safely…"},
    "decal.previewing": {
        "ja": "現在の面IDへプレビューを作成中…",
        "en": "Building a preview on the current face-ID map…",
    },
    "decal.view_wait": {
        "ja": "正確な面IDを描画中です…完了後に再プレビューしてください",
        "en": "Rendering the exact face-ID map… preview again when it settles",
    },
    "decal.view_settled": {
        "ja": "視点が確定しました。［プレビュー］で位置を再確認してください",
        "en": "View settled. Choose Preview to confirm placement again",
    },
    "decal.changed": {
        "ja": "配置を変更しました。再プレビューしてください",
        "en": "Placement changed. Preview again",
    },
    "decal.loaded": {
        "ja": "{name}を読み込みました。現在の視点へ配置できます",
        "en": "Loaded {name}. It can now be placed in the current view",
    },
    "decal.loading_error_title": {
        "ja": "デカール画像を開けません",
        "en": "Cannot Open Decal Image",
    },
    "decal.loading_error": {
        "ja": "PNG / SVGを読み込めませんでした。\n\n{reason}",
        "en": "The PNG / SVG could not be loaded.\n\n{reason}",
    },
    "decal.error_file": {
        "ja": "画像ファイルを読み取れません（{code}）",
        "en": "The image file cannot be read ({code}).",
    },
    "decal.error_unsupported": {
        "ja": "PNGまたはSVGファイルを選んでください（{code}）",
        "en": "Choose a PNG or SVG file ({code}).",
    },
    "decal.error_limit": {
        "ja": "画像が安全なサイズ・複雑さの上限を超えています（{code}）",
        "en": "The image exceeds the safe size or complexity limit ({code}).",
    },
    "decal.error_png": {
        "ja": "PNGが壊れているか、対応していない形式です（{code}）",
        "en": "The PNG is corrupt or uses an unsupported format ({code}).",
    },
    "decal.error_apng": {
        "ja": "アニメーションPNGには対応していません。静止PNGを保存してください。",
        "en": "Animated PNG is not supported. Save a still PNG instead.",
    },
    "decal.error_svg_unsafe": {
        "ja": "SVGに外部参照または安全でない要素があります（{code}）",
        "en": "The SVG contains an external reference or unsafe element ({code}).",
    },
    "decal.error_svg_invalid": {
        "ja": "SVGが壊れているか、対応していない構造です（{code}）",
        "en": "The SVG is invalid or uses an unsupported structure ({code}).",
    },
    "decal.error_svg_renderer": {
        "ja": "SVG描画エンジンを使用できません（{code}）。PNGへ書き出して再試行してください。",
        "en": "The SVG renderer is unavailable ({code}). Export a PNG and try again.",
    },
    "decal.error_generic": {
        "ja": "画像を読み込めません（{code}）",
        "en": "The image could not be loaded ({code}).",
    },
    "decal.svg_hint": {
        "ja": "SVGは文字をパス化し、外部画像・CSS・スクリプトを含まないPlain SVGで保存してください。",
        "en": "For SVG, convert text to paths and save a Plain SVG without external images, CSS, or scripts.",
    },
    "decal.preview_error_title": {
        "ja": "デカールをプレビューできません",
        "en": "Cannot Preview Decal",
    },
    "decal.preview_error": {
        "ja": "現在の表示ではプレビューできません。\n\n{reason}",
        "en": "A preview cannot be created from the current view.\n\n{reason}",
    },
    "decal.invalid_values": {
        "ja": "位置・幅・回転・不透明度の数値を確認してください",
        "en": "Check the position, width, rotation, and opacity values",
    },
    "decal.invalid_width": {
        "ja": "デカール幅は0より大きくしてください",
        "en": "Decal width must be greater than zero",
    },
    "decal.projection_limit": {
        "ja": "対象が複雑すぎます。デカールを小さくして再プレビューしてください",
        "en": "The target is too complex. Make the decal smaller and preview again",
    },
    "decal.projection_error": {
        "ja": "現在の配置を安全に処理できません。位置・サイズを変えて再プレビューしてください",
        "en": "This placement cannot be processed safely. Change its position or size and preview again",
    },
    "decal.preview_done": {
        "ja": "保存どおり: {faces:,}面 / {pixels:,}px / 保護{protected:,} / 非連続{disconnected:,}",
        "en": "Bake-faithful: {faces:,} faces / {pixels:,} px / {protected:,} protected / {disconnected:,} disconnected",
    },
    "decal.preview_nothing": {
        "ja": "保存される変更はありません（保護 {protected:,}面、非連続 {disconnected:,}面）。必要なら上書きを有効にしてください",
        "en": "No bakeable change ({protected:,} protected, {disconnected:,} disconnected). Enable overwrite if intended",
    },
    "decal.no_visible_target": {
        "ja": "デカールが現在見えている編集中パーツへ重なっていません",
        "en": "The decal does not overlap the visible active part",
    },
    "decal.applying": {
        "ja": "確認済みプレビューを保存中…完了後は［デカールを1回戻す］で復元できます",
        "en": "Saving the confirmed preview… use Undo Decal Once after it completes",
    },
    "decal.applied": {
        "ja": "デカールを{faces:,}面へ適用（細分化 {adaptive:,}面、保護 {protected:,}面）",
        "en": "Applied decal to {faces:,} faces ({adaptive:,} adaptive, {protected:,} protected)",
    },
    "decal.nothing_applied": {
        "ja": "変更対象はありません（保護 {protected:,}面、非連続 {disconnected:,}面）",
        "en": "Nothing changed ({protected:,} protected, {disconnected:,} disconnected)",
    },
    "decal.cancelled": {
        "ja": "デカール処理を取り消しました",
        "en": "Decal operation cancelled",
    },
    "decal.cancelling": {
        "ja": "安全に停止しています…",
        "en": "Stopping safely…",
    },
    "decal.apply_error_title": {
        "ja": "デカールを適用できません",
        "en": "Cannot Apply Decal",
    },
    "decal.overwrite_title": {
        "ja": "既存の手修正へ上書きしますか？",
        "en": "Overwrite Existing Manual Paint?",
    },
    "decal.overwrite_confirm": {
        "ja": "デカール範囲の手塗り・面内グラデーションへ上書きします。範囲外は保持し、この適用全体は1回の［元に戻す］で復元できます。続けますか？",
        "en": "The decal will overwrite hand paint and in-face gradients inside its footprint. Areas outside it stay unchanged, and the entire apply is restored by one Undo. Continue?",
    },
    "decal.selected_disabled": {
        "ja": "現在の選択色が無効です。ブラシ・色パネルで有効色を選んでください",
        "en": "The current selected color is disabled. Choose an enabled state in Brush & Color",
    },
    "decal.adaptive_unavailable": {
        "ja": "面内グラデーション保存の準備が完了していません",
        "en": "The in-face gradient store is not ready",
    },
    "decal.undo_unavailable": {
        "ja": "デカール後に別の操作があるため、通常の［元に戻す］を使用してください",
        "en": "Another edit follows the decal; use the regular Undo history instead",
    },
    "paint.shading_global_group": {
        "ja": "1  全体の陰影・色調",
        "en": "1  Global Shading & Tone",
    },
    "paint.shading_mix_group": {
        "ja": "2  混色比率を陰影に合わせる",
        "en": "2  Match Mix Ratios to Shading",
    },
    "paint.shading_local_group": {
        "ja": "3  面内グラデーション補正",
        "en": "3  In-face Gradient Correction",
    },
    "paint.shading_mix_target": {
        "ja": "対象: {name}",
        "en": "Target: {name}",
    },
    "paint.shading_invalid_points": {
        "ja": "白点は黒点より十分大きくしてください",
        "en": "White point must be sufficiently above black point",
    },
    "paint.shading_mix_unavailable": {
        "ja": "混色最適化はメイン画面と接続されていません",
        "en": "Mix optimization is not connected to the main window",
    },
    "paint.shading_tone_applied": {
        "ja": "全体の陰影・色調を更新しました",
        "en": "Updated global shading and tone",
    },
    "paint.shading_mix_applied": {
        "ja": "混色比率を更新しました",
        "en": "Updated mix ratios",
    },
    "paint.shading_settings_applied": {
        "ja": "陰影とフィラメント設定を更新しました",
        "en": "Updated shading and filament settings",
    },
    "paint.shading_undo_target_changed": {
        "ja": "直前の最適化とは対象パーツが異なるため、取り消せません",
        "en": "The active part differs from the last optimization target, so it cannot be undone",
    },
    "paint.reference_show": {"ja": "元画像を表示", "en": "Show Reference"},
    "paint.reference_hide": {"ja": "元画像を収納", "en": "Hide Reference"},
    "paint.reference_unavailable": {
        "ja": "元画像が開かれていません",
        "en": "No reference image is loaded",
    },
    "paint.reference_shown": {
        "ja": "元画像を表示しました",
        "en": "Reference image shown",
    },
    "paint.reference_hidden": {
        "ja": "元画像を収納しました",
        "en": "Reference image hidden",
    },
    "paint.palette_show": {"ja": "ブラシ・色を表示", "en": "Show Brush & Color"},
    "paint.palette_hide": {"ja": "ブラシ・色を収納", "en": "Hide Brush & Color"},
    "paint.parts_tool_title": {"ja": "パーツ", "en": "Parts"},
    "paint.parts_tool_show": {"ja": "パーツパネル", "en": "Parts Panel"},
    "paint.only_selected_visible": {
        "ja": "選択パーツ以外を非表示",
        "en": "Hide All Except Selected",
    },
    "paint.only_selected_transparent": {
        "ja": "選択パーツ以外を透明化",
        "en": "Make All Except Selected Transparent",
    },
    "paint.show_all_parts": {
        "ja": "パーツを全表示",
        "en": "Show All Parts",
    },
    "paint.tool_window_outside_hint": {
        "ja": "このパネルは編集画面の外へ移動できます",
        "en": "This panel can be moved outside the editor",
    },
    "paint.fullscreen_enter": {"ja": "全画面 F11", "en": "Full Screen F11"},
    "paint.fullscreen_exit": {"ja": "全画面を終了 Esc", "en": "Exit Full Screen Esc"},
    "paint.orbit_inverted": {
        "ja": "右ドラッグ回転を反転",
        "en": "Invert Right-drag Orbit",
    },
    "paint.orbit_inverted_on": {
        "ja": "右ドラッグ回転を反転しました",
        "en": "Right-drag orbit inverted",
    },
    "paint.orbit_inverted_off": {
        "ja": "右ドラッグ回転を標準へ戻しました",
        "en": "Right-drag orbit restored",
    },
    "paint.floating_palette_title": {"ja": "ブラシ・色", "en": "Brush & Color"},
    "paint.floating_palette_hint": {
        "ja": "見出しをドラッグして移動",
        "en": "Drag the header to move",
    },
    "paint.palette_tab_manual": {"ja": "手で塗る", "en": "Paint by Hand"},
    "paint.quick_help": {"ja": "? 操作ガイド F1", "en": "? Controls F1"},
    "paint.shortcut_help_button": {"ja": "ショートカット", "en": "Shortcuts"},
    "paint.shortcut_help_title": {"ja": "マニュアル修正のショートカット", "en": "Manual Editing Shortcuts"},
    "paint.shortcut_help_intro": {
        "ja": "入力欄へ文字を入力している間はショートカットを発動しません。",
        "en": "Shortcuts are suspended while typing in a text or value field.",
    },
    "paint.shortcut.undo": {"ja": "元に戻す", "en": "Undo"},
    "paint.shortcut.redo": {"ja": "やり直す", "en": "Redo"},
    "paint.shortcut.orbit": {"ja": "回転ツール", "en": "Orbit tool"},
    "paint.shortcut.brush": {"ja": "ブラシ", "en": "Brush"},
    "paint.shortcut.airbrush": {"ja": "エアブラシ", "en": "Airbrush"},
    "paint.shortcut.eyedropper": {"ja": "3Dスポイト", "en": "3D Eyedropper"},
    "paint.shortcut.smudge": {"ja": "なじませ", "en": "Smudge"},
    "paint.shortcut.fill": {"ja": "塗りつぶし", "en": "Fill"},
    "paint.shortcut.smooth": {"ja": "境界ならし", "en": "Smooth boundary"},
    "paint.shortcut.restore": {"ja": "自動色へ戻す", "en": "Restore automatic color"},
    "paint.shortcut.split": {"ja": "フリーハンド分割", "en": "Freehand separation"},
    "paint.shortcut.joint": {"ja": "ジョイント配置 β", "en": "Place Joint β"},
    "paint.shortcut.part_visible": {"ja": "編集中パーツを表示", "en": "Show active part"},
    "paint.shortcut.part_transparent": {"ja": "編集中パーツを透明化", "en": "Make active part transparent"},
    "paint.shortcut.part_hidden": {"ja": "編集中パーツを非表示", "en": "Hide active part"},
    "paint.shortcut.toggle_reference": {"ja": "元画像の表示・収納", "en": "Show or hide reference"},
    "paint.shortcut.toggle_palette": {"ja": "ブラシ・色の表示・収納", "en": "Show or hide Brush & Color"},
    "paint.shortcut.toggle_ribbon": {"ja": "リボンの展開・収納", "en": "Expand or collapse ribbon"},
    "paint.shortcut.toggle_fullscreen": {"ja": "全画面の開始・終了", "en": "Enter or exit full screen"},
    "paint.shortcut.show_help": {"ja": "この一覧を表示", "en": "Show this list"},
    "paint.shortcut_tool_selected": {
        "ja": "{tool}へ切り替えました",
        "en": "Switched to {tool}",
    },
    "paint.double_click_hint": {
        "ja": "3Dをダブルクリック: 編集パーツ切替",
        "en": "Double-click 3D: switch active part",
    },
    "paint.double_click_help": {
        "ja": "3D上のパーツをダブルクリックすると編集パーツを切り替えます。非表示パーツは対象外です。透明パーツは［透明パーツを選択対象にする］がONの時だけ選べます。",
        "en": "Double-click a 3D part to make it active. Hidden parts cannot be picked; transparent parts can be picked only when Allow Selecting Transparent Parts is enabled.",
    },
    "paint.double_click_no_part": {
        "ja": "この位置には選択できるパーツがありません",
        "en": "There is no selectable part at this position",
    },
    "paint.double_click_already_active": {
        "ja": "{part} は既に編集中です",
        "en": "{part} is already active",
    },
    "paint.double_click_selected": {
        "ja": "ダブルクリックで {part} を編集パーツに選びました",
        "en": "Selected {part} as the active part by double-click",
    },
    "paint.part_selected": {
        "ja": "編集パーツを {part} へ切り替えました",
        "en": "Switched the active part to {part}",
    },
    "paint.solidify_confirm": {
        "ja": "現在の色修正をすべて確定してマニュアル修正を閉じ、メイン画面と同じ安全な閉立体化を実行します。続けますか？",
        "en": "Commit all current color edits, close Manual Editing, and run the same safe solidification used on the main screen?",
    },
    "paint.solidify_closing": {
        "ja": "最後の修正を確定して閉じ、閉立体化へ移ります…",
        "en": "Committing the final edits, closing, and starting solidification…",
    },
    "paint.solidify_unavailable": {
        "ja": "この画面から閉立体化を開始できません",
        "en": "Solidification cannot be started from this window",
    },
    "paint.current_part": {"ja": "編集中のパーツ", "en": "Part Being Edited"},
    "paint.current_part_summary": {
        "ja": "{index}: {name}（{faces:,}面）",
        "en": "{index}: {name} ({faces:,} faces)",
    },
    "paint.part_name": {"ja": "パーツ名", "en": "Part Name"},
    "paint.rename_part": {"ja": "名前変更", "en": "Rename"},
    "paint.part_rename_title": {"ja": "パーツ名の変更", "en": "Rename Part"},
    "paint.part_renamed": {
        "ja": "パーツ名を「{name}」へ変更しました",
        "en": "Renamed the part to \"{name}\"",
    },
    "paint.view_background": {"ja": "3D背景", "en": "3D Background"},
    "paint.background_auto": {"ja": "自動（見やすさ優先）", "en": "Auto (Best Contrast)"},
    "paint.background_dark": {"ja": "暗色", "en": "Dark"},
    "paint.background_light": {"ja": "明色", "en": "Light"},
    "paint.background_neutral": {"ja": "中間グレー", "en": "Neutral Gray"},
    "paint.active_outline_help": {
        "ja": "水色の輪郭 = 現在編集中のパーツ",
        "en": "Cyan outline = part currently being edited",
    },
    "paint.background_changed": {
        "ja": "このモデルの3D背景を「{mode}」へ変更しました",
        "en": "Changed this model's 3D background to {mode}",
    },
    "paint.part_visibility": {"ja": "パーツ表示 (V/T/H)", "en": "Part Display (V/T/H)"},
    "paint.part_visible": {"ja": "表示", "en": "Visible"},
    "paint.part_transparent": {"ja": "透明", "en": "Transparent"},
    "paint.part_hidden": {"ja": "非表示", "en": "Hidden"},
    "paint.pick_transparent": {
        "ja": "透明パーツを選択対象にする",
        "en": "Allow Selecting Transparent Parts",
    },
    "paint.boundary_diagnostics": {
        "ja": "開口診断を表示（赤=要確認／黄=対応済み）",
        "en": "Show Boundary Diagnostics (red=review / yellow=matched)",
    },
    "paint.boundary_diagnostics_none": {
        "ja": "開口診断データなし",
        "en": "No boundary diagnostics",
    },
    "paint.boundary_diagnostics_status": {
        "ja": "開口診断: 要確認 {unmatched}箇所 / 対応済み {matched}ループ",
        "en": "Boundary diagnostics: {unmatched} need review / {matched} matched loops",
    },
    "paint.boundary_problem_detail": {
        "ja": "!1 要確認: {part} / 幅 {span:.3f} mm（赤い照準。回転・ズーム・ホイールドラッグで確認）",
        "en": "!1 Review: {part} / span {span:.3f} mm (red reticle; orbit, zoom, and middle-drag to inspect)",
    },
    "paint.visibility_changed": {
        "ja": "{part} の表示を「{mode}」へ変更しました",
        "en": "Changed {part} display to {mode}",
    },
    "paint.transparent_pick_changed": {
        "ja": "透明パーツの選択を{state}にしました",
        "en": "Transparent-part selection is now {state}",
    },
    "paint.enabled": {"ja": "有効", "en": "enabled"},
    "paint.disabled": {"ja": "無効", "en": "disabled"},
    "joint.place_tool": {"ja": "ジョイント配置 β", "en": "Place Joint β"},
    "joint.beta_label": {"ja": "回り止め四角ジョイント β", "en": "Keyed Rectangle Joint β"},
    "joint.width": {"ja": "横幅", "en": "Width"},
    "joint.length": {"ja": "縦長さ", "en": "Length"},
    "joint.depth": {"ja": "差込深さ", "en": "Insertion Depth"},
    "joint.clearance": {"ja": "クリアランス", "en": "Clearance"},
    "joint.undo": {"ja": "ジョイントを元に戻す", "en": "Undo Joint"},
    "joint.how_to": {"ja": "使い方", "en": "How to Use"},
    "joint.help": {
        "ja": "上部の［パーツを閉立体化］ → マニュアル修正を開き直す → 雄側を編集パーツにする → 相手を透明/非表示 → このツールを選択 → 閉立体化で追加された平面接合面をクリック。雌穴は同じ位置へ自動生成します。",
        "en": "Use Solidify Parts at the top → reopen Manual Editing → make the male side the active part → make its mate transparent/hidden → select this tool → click the planar interface added by solidification. The socket is created at the same position.",
    },
    "joint.workflow.title": {
        "ja": "ジョイント配置 β の手順",
        "en": "Place Joint β Workflow",
    },
    "joint.workflow.general_label": {
        "ja": "基本手順:",
        "en": "General workflow:",
    },
    "joint.workflow.solidify": {
        "ja": "1. マニュアル修正上部の［パーツを閉立体化］を実行する",
        "en": "1. Choose Solidify Parts at the top of Manual Editing",
    },
    "joint.workflow.reopen_manual": {
        "ja": "2. 閉立体化の完了後にマニュアル修正を開き直す",
        "en": "2. Reopen Manual Editing after solidification finishes",
    },
    "joint.workflow.select_male": {
        "ja": "3. 雄ジョイントを付ける側を［編集パーツ］にする",
        "en": "3. Choose the part that will receive the male key as the active part",
    },
    "joint.workflow.hide_other": {
        "ja": "4. 相手パーツを透明または非表示にして接合面を見えるようにする",
        "en": "4. Make the opposing part transparent or hidden to expose the interface",
    },
    "joint.workflow.select_tool": {
        "ja": "5. ［ジョイント配置 β］を選び、寸法とクリアランスを設定する",
        "en": "5. Select Place Joint β and set its dimensions and clearance",
    },
    "joint.workflow.click_generated_plane": {
        "ja": "6. 閉立体化で自動生成された平面接合面をクリックする",
        "en": "6. Click the planar interface generated during solidification",
    },
    "joint.workflow.reprocess": {
        "ja": "元モデルからパーツ形状を再処理して、閉立体化をやり直してください",
        "en": "Reprocess the part geometry from the source model and run solidification again",
    },
    "joint.workflow.disable_auto_joint": {
        "ja": "［パーツ処理］で自動ジョイントをOFFにして再処理してください",
        "en": "Turn automatic joints off under Part Processing and reprocess the geometry",
    },
    "joint.workflow.undo_existing_joint": {
        "ja": "既存ジョイントを元に戻してから形状を再処理してください",
        "en": "Undo the existing joint, then reprocess the geometry",
    },
    "joint.workflow.reprocess_before_split": {
        "ja": "元モデルから再処理し、フリーハンド分割より先にジョイントを配置してください",
        "en": "Reprocess from the source model and place the joint before freehand separation",
    },
    "joint.availability.ready": {
        "ja": "配置可能な自動生成平面共有面を {interfaces} 組確認しました。雄側を編集パーツにし、相手を透明/非表示にして平面接合面をクリックしてください。",
        "en": "Found {interfaces} generated planar interface pair(s). Select the male part, make its mate transparent/hidden, and click the planar interface.",
    },
    "joint.availability.needs_multiple_parts": {
        "ja": "ジョイントには相手となる別パーツが必要です。現在の形状は2パーツ以上として認識されていません。",
        "en": "A joint requires a separate opposing part. The current geometry is not recognized as two or more parts.",
    },
    "joint.availability.needs_solidify": {
        "ja": "ジョイントを置く平面接合面がまだ生成されていません。先に上部の［パーツを閉立体化］を実行し、完了後にマニュアル修正を開き直してください。",
        "en": "The planar interface needed for joint placement has not been generated. Choose Solidify Parts above, then reopen Manual Editing.",
    },
    "joint.availability.beta_no_planar_shared_interface": {
        "ja": "閉立体化後も対応する自動生成平面共有面がありません。この形状は現在のジョイントβ版では非対応です。通常の外装面や曲面へは安全に配置できません。",
        "en": "No corresponding generated planar shared interface exists after solidification. This geometry is unsupported by the current joint beta; arbitrary exterior surfaces and curved interfaces cannot be used safely.",
    },
    "joint.availability.automatic_joint_conflict": {
        "ja": "自動ジョイントが生成済みです。位置を手動指定する場合は、自動生成をOFFにして形状を再処理してください。",
        "en": "Automatic joints already exist. Turn automatic generation off and reprocess the geometry to choose a position manually.",
    },
    "joint.availability.already_jointed": {
        "ja": "この形状はジョイント加工済みです。別の位置へ置き直す場合は、既存ジョイントを元に戻して再処理してください。",
        "en": "This geometry already contains a joint. Undo it and reprocess the geometry before choosing another position.",
    },
    "joint.availability.freehand_split_unsupported": {
        "ja": "フリーハンド分割後は元の平面共有面との対応を保証できません。元モデルから再処理し、分割より先にジョイントを配置してください。",
        "en": "The original planar-interface correspondence cannot be guaranteed after freehand separation. Reprocess from the source model and place the joint before separating parts.",
    },
    "joint.availability.invalid_metadata": {
        "ja": "閉立体化で記録された接合面情報が現在の形状と一致しません。元モデルから形状を再処理してください。",
        "en": "The interface metadata recorded during solidification does not match the current geometry. Reprocess the geometry from the source model.",
    },
    "joint.click_prompt": {
        "ja": "雄側にする編集パーツの自動生成接合面をクリックしてください",
        "en": "Click the generated interface on the active part that will receive the male key",
    },
    "joint.auto_conflict": {
        "ja": "この形状には自動ジョイントが生成済みです。ユーザー指定位置へ置く場合は、メイン画面の［パーツ処理］で自動生成をOFFにして形状を再処理してから、もう一度マニュアル修正を開いてください。",
        "en": "Automatic joints already exist on this geometry. To choose the position yourself, turn automatic joint generation off under Part Processing, reprocess the geometry, and reopen Manual Editing.",
    },
    "joint.wait": {"ja": "前の処理が終わるまでお待ちください", "en": "Wait for the current operation to finish"},
    "joint.checking": {"ja": "接合面・埋め込み余白・肉厚を確認しています…", "en": "Checking the interface, embedded contact, and wall thickness…"},
    "joint.confirm_title": {"ja": "雄雌ジョイントを生成", "en": "Create Male/Female Joint"},
    "joint.confirm_message": {
        "ja": "雄: {male}\n雌: {female}\n位置: ユーザー指定点\n横幅 {width:.2f} mm / 縦長さ {length:.2f} mm\n差込深さ {depth:.2f} mm / クリアランス {clearance:.2f} mm\n\n四角形を接合面へ埋め込み、交差体積と閉立体を検査してから雄・雌を同時生成します。続けますか？",
        "en": "Male: {male}\nFemale: {female}\nPosition: user-selected point\nWidth {width:.2f} mm / length {length:.2f} mm\nInsertion depth {depth:.2f} mm / clearance {clearance:.2f} mm\n\nThe rectangle will be embedded into the interface and both solids will be accepted only after contact-volume and watertight checks. Continue?",
    },
    "joint.cancelled": {"ja": "ジョイント生成をキャンセルしました", "en": "Joint creation cancelled"},
    "joint.generating": {"ja": "雄・雌を生成し、接触体積と閉立体を検査しています…", "en": "Creating the male and socket and validating contact volume and watertight solids…"},
    "joint.completed": {"ja": "ユーザー指定位置へ雄・雌ジョイントを生成しました", "en": "Created the male and socket at the user-selected position"},
    "joint.undo_confirm_title": {"ja": "ジョイントを元に戻す", "en": "Undo Joint"},
    "joint.undo_confirm": {
        "ja": "ジョイント生成後のブラシ修正も破棄して、生成直前の形状へ戻しますか？",
        "en": "Return to the geometry immediately before joint creation? Paint edits made after creating the joint will also be discarded.",
    },
    "joint.undone": {"ja": "ジョイント生成前の形状へ戻しました", "en": "Restored the geometry from before joint creation"},
    "joint.adaptive_flatten_warning": {
        "ja": "滑らかブラシの細分化は、形状変更に合わせて面単位の代表色へ統合されます。",
        "en": "Adaptive sub-face brush detail will be flattened to representative face colors for the topology change.",
    },
    "paint.brush_radius": {"ja": "ブラシ半径", "en": "Brush Radius"},
    "paint.airbrush_strength": {"ja": "エアブラシ濃さ", "en": "Airbrush Flow"},
    "paint.smudge_strength": {"ja": "なじませ強さ", "en": "Smudge Strength"},
    "paint.edge_guard": {"ja": "局所ツールを折り目で止める", "en": "Stop Local Tools at Creases"},
    "paint.angle": {"ja": "折り目角度", "en": "Crease Angle"},
    "paint.crease_overlay": {"ja": "折り目を表示", "en": "Show Creases"},
    "paint.crease_overlay_on": {"ja": "{angle:.0f}°を超える折り目を表示します", "en": "Showing creases sharper than {angle:.0f}°"},
    "paint.crease_overlay_off": {"ja": "折り目表示を消しました", "en": "Crease overlay hidden"},
    "paint.zoom": {"ja": "拡大", "en": "Zoom"},
    "paint.view_wait": {"ja": "表示の更新後にもう一度操作してください", "en": "Try again after the view finishes updating"},
    "paint.eyedropper_prompt": {"ja": "現在の3D色をクリックしてください", "en": "Click the current paint on the 3D model"},
    "paint.airbrush_prompt": {"ja": "エアブラシ: 筆圧と濃さに応じてやわらかく塗ります", "en": "Airbrush: drag to paint softly with pressure and strength"},
    "paint.smudge_prompt": {"ja": "なじませ: 残したい色から境界へドラッグします", "en": "Smudge: drag from the color you want to keep toward the boundary"},
    "paint.eyedropper_wait": {"ja": "現在の色を取得できるまでお待ちください", "en": "Wait until the current paint is ready to sample"},
    "paint.eyedropper_picked": {"ja": "3Dスポイト: 色{state} {name}", "en": "3D Eyedropper: Color {state} {name}"},
    "paint.airbrush_drawing": {"ja": "エアブラシ入力中…離すと反映します", "en": "Airbrushing… release to apply"},
    "paint.smudge_drawing": {"ja": "なじませ入力中…離すと反映します", "en": "Smudging… release to apply"},
    "paint.airbrush_applied": {"ja": "エアブラシを{count:,}面へ反映しました", "en": "Airbrushed {count:,} faces"},
    "paint.smudge_applied": {"ja": "{count:,}面をなじませました", "en": "Smudged {count:,} faces"},
    "paint.smooth_passes": {"ja": "ならし回数", "en": "Smooth Passes"},
    "paint.paint_color": {"ja": "塗る色", "en": "Paint Color"},
    "paint.close": {"ja": "修正を保持して閉じる", "en": "Keep Corrections and Close"},
    "paint.nib": {"ja": "筆先", "en": "Nib"},
    "paint.round_nib": {"ja": "丸筆", "en": "Round"},
    "paint.marker_nib": {"ja": "マーカー（長方形）", "en": "Marker (Rectangle)"},
    "paint.marker_hint": {"ja": "マーカーは表示中のストローク方向へ追従します", "en": "The marker follows the visible stroke direction"},
    "paint.pressure_taper_nib": {
        "ja": "筆圧ペン（未検出時は先細り）",
        "en": "Pressure Pen (tapers if unavailable)",
    },
    "paint.pressure_waiting": {
        "ja": "筆圧: Windows Ink入力待機中。未検出の筆跡は両端を自動で先細りにします。",
        "en": "Pressure: waiting for Windows Ink. Undetected strokes taper automatically at both ends.",
    },
    "paint.pressure_detected": {
        "ja": "筆圧: ペンを検出しました（弱い筆圧で細く、強い筆圧で設定半径）。",
        "en": "Pressure: pen detected (light pressure is thin; firm pressure uses the set radius).",
    },
    "paint.pressure_unavailable": {
        "ja": "筆圧: この環境では未検出。両端が細い筆跡を自動生成します。",
        "en": "Pressure: unavailable in this environment. Strokes automatically taper at both ends.",
    },
    "paint.auto_shading": {
        "ja": "面内グラデーション補正",
        "en": "In-face Gradient Correction",
    },
    "paint.auto_quality": {"ja": "品質", "en": "Quality"},
    "paint.auto_quality_fast": {"ja": "高速", "en": "Fast"},
    "paint.auto_quality_standard": {"ja": "標準", "en": "Standard"},
    "paint.auto_quality_high": {"ja": "高品質", "en": "High Quality"},
    "paint.auto_strength": {"ja": "グラデーション強度", "en": "Gradient Strength"},
    "paint.auto_boundary_only": {"ja": "色境界付近のみ", "en": "Near Color Boundaries Only"},
    "paint.auto_apply": {
        "ja": "面内グラデーションを生成",
        "en": "Generate In-face Gradients",
    },
    "paint.controls_hint": {"ja": "左: ツール操作　右ドラッグ: 回転　ホイールドラッグ: 移動　ホイール: 拡大　C / Alt+左: 3Dスポイト", "en": "Left: use tool   Right drag: rotate   Middle drag: pan   Wheel: zoom   C / Alt+Left: 3D Eyedropper"},
    "paint.initializing": {"ja": "最終メッシュを準備しています…", "en": "Preparing the final mesh…"},
    "paint.edit_count_zero": {"ja": "手修正 0面", "en": "Manual edits: 0 faces"},
    "paint.choose_color": {"ja": "塗る色を選択してください", "en": "Select a paint color"},
    "paint.sample_initial": {"ja": "元画像をクリックすると現在の{count}色から近い色を選びます", "en": "Click the reference image to choose the nearest of the current {count} print colors"},
    "paint.selected_color": {"ja": "選択中 {state}: {name}{suffix}", "en": "Selected {state}: {name}{suffix}"},
    "paint.manual_only_suffix": {"ja": "（自動割当は無効・手動使用可）", "en": " (automatic assignment off; manual use available)"},
    "paint.palette_usage_focus": {
        "ja": "選択色の使用箇所を3Dで強調（診断表示）",
        "en": "Highlight selected color usage in 3D (diagnostic)",
    },
    "paint.palette_usage_off": {
        "ja": "ONにすると、他の色を暗くして選択色の配置を確認できます。出力色は変更しません。",
        "en": "Turn on to dim other colors and inspect placement. Export colors are not changed.",
    },
    "paint.palette_usage_wait": {
        "ja": "使用面を集計しています…",
        "en": "Calculating color usage…",
    },
    "paint.palette_usage_summary": {
        "ja": "対象: {part}\n色 {state}: {recipe}（3MF出力recipe上の公称比率 {selected_share}）\n使用: {faces:,}親面（{face_percent:.2f}%） / {area:.1f} mm²（表面積 {area_percent:.2f}%）\n{mode_note}\n表面割当からの基本色推定: {base_estimate}",
        "en": "Part: {part}\nColor {state}: {recipe} (nominal 3MF recipe share {selected_share})\nUsage: {faces:,} root faces ({face_percent:.2f}%) / {area:.1f} mm² ({area_percent:.2f}% of surface)\n{mode_note}\nEstimated base share from surface assignments: {base_estimate}",
    },
    "paint.palette_usage_summary_shell": {
        "ja": "対象: {part}\n色 {state}: {recipe}（3MF出力recipe上の公称比率・2本同幅前提 {selected_share}）\n使用: {faces:,}親面（{face_percent:.2f}%） / {area:.1f} mm²（表面積 {area_percent:.2f}%）\n{mode_note}\n表面割当からの基本色推定: {base_estimate}",
        "en": "Part: {part}\nColor {state}: {recipe} (nominal 3MF recipe share; two equal-width walls {selected_share})\nUsage: {faces:,} root faces ({face_percent:.2f}%) / {area:.1f} mm² ({area_percent:.2f}% of surface)\n{mode_note}\nEstimated base share from surface assignments: {base_estimate}",
    },
    "paint.palette_usage_face_level": {
        "ja": "集計精度: 面単位（このパーツに面内サブ三角形なし）",
        "en": "Detail: face-level (this part has no adaptive subtriangles)",
    },
    "paint.palette_usage_adaptive": {
        "ja": "面内補正込み: 該当 {roots} root / {selected_leaves} leaf（全 {total_roots} root / {total_leaves} leaf）",
        "en": "Includes adaptive detail: {roots} roots / {selected_leaves} leaves selected (of {total_roots} roots / {total_leaves} leaves)",
    },
    "paint.palette_usage_enabled": {
        "ja": "選択色の使用箇所を強調しています（表示のみ・出力には影響しません）",
        "en": "Highlighting selected color usage (display only; export is unchanged)",
    },
    "paint.palette_usage_disabled": {
        "ja": "通常の変換色表示へ戻しました",
        "en": "Restored the normal converted-color view",
    },
    "paint.reference_panel": {"ja": "元画像（クリックで近い印刷色を選択）", "en": "Reference (click to select nearest print color)"},
    "paint.no_reference": {"ja": "元画像なし", "en": "No reference image"},
    "paint.target_panel": {"ja": "変換色のマニュアル修正（平行投影・右ドラッグで全方向回転）", "en": "Manual Editing for Converted Colors (orthographic; right-drag to rotate)"},
    "paint.preparing_mesh": {"ja": "最終メッシュを準備中", "en": "Preparing final mesh"},
    # Reserved keys for the freehand separation feature.  Geometry code may
    # use these now without adding language conditionals.
    "tab.separate": {"ja": "分割", "en": "Separate"},
    "separate.freehand": {"ja": "フリーハンド分割", "en": "Freehand Separation"},
    "separate.floating_help": {
        "ja": "浮遊している独立形状を囲み、色を保った新規パーツへ分離",
        "en": "Enclose a floating disconnected shape to make a new part while preserving its colors",
    },
    "separate.start": {"ja": "領域を描く", "en": "Draw Region"},
    "separate.finish": {"ja": "囲った範囲をパーツ化", "en": "Create Part from Enclosed Region"},
    "separate.cancel": {"ja": "選択を解除", "en": "Clear Selection"},
    "separate.undo": {"ja": "分割を元に戻す", "en": "Undo Separation"},
    "separate.help": {
        "ja": "3Dモデルを見ながら輪郭をフリーハンドで囲み、囲った面を新しい印刷パーツにします。色設定は維持されます。",
        "en": "Draw a freehand outline on the 3D model to turn the enclosed faces into a new print part while preserving color assignments.",
    },
    "separate.visible_only": {"ja": "見えている面だけ選択", "en": "Select Visible Faces Only"},
    "separate.through": {"ja": "奥側まで貫通選択", "en": "Select Through Model"},
    "separate.new_part_name": {"ja": "新しいパーツ名", "en": "New Part Name"},
    "separate.confirm_title": {"ja": "フリーハンド分割を確認", "en": "Confirm Freehand Separation"},
    "separate.confirm_message": {
        "ja": "{source} から {faces:,}面を切り出し、\n「{new_name}」として追加します。\n\n囲み率: {coverage:.1f}%\n頂点・三角形・現在の色は変更しません。実行しますか？",
        "en": "Separate {faces:,} faces from {source} and add them as\n\"{new_name}\".\n\nEnclosed coverage: {coverage:.1f}%\nVertices, triangles, and current colors will not change. Continue?",
    },
    "separate.wait_for_view": {"ja": "3D表示の更新後に、もう一度囲んでください", "en": "Wait for the 3D view to update, then draw the region again"},
    "separate.checking": {"ja": "囲んだ独立形状を確認しています…", "en": "Checking the enclosed disconnected shape…"},
    "separate.cancelled": {"ja": "フリーハンド分割をキャンセルしました", "en": "Freehand separation was cancelled"},
    "separate.draw_prompt": {"ja": "右側の3D表示で、分けたい独立形状を囲んでください", "en": "Enclose the disconnected shape in the 3D view on the right"},
    "separate.trace_prompt": {"ja": "分けたい独立形状の外側を一周してください", "en": "Trace once around the disconnected shape to separate"},
    "separate.cannot_split": {"ja": "この範囲は分割できません", "en": "Cannot Separate This Selection"},
    "separate.error.invalid_mapping": {"ja": "3D表示の座標変換範囲が不正です", "en": "The 3D view mapping is not ready. Refresh the view and try again."},
    "separate.error.too_few_points": {"ja": "フリーハンド領域は3点以上で囲んでください", "en": "Draw at least three points to enclose the region."},
    "separate.error.invalid_face_map_size": {"ja": "面ID画像の大きさが不正です", "en": "The 3D face map has an invalid size. Refresh the view and try again."},
    "separate.error.invalid_coordinates": {"ja": "フリーハンド領域に不正な座標があります", "en": "The freehand outline contains invalid coordinates."},
    "separate.error.region_too_small": {"ja": "フリーハンド領域が小さすぎます", "en": "The freehand region is too small."},
    "separate.error.source_out_of_range": {"ja": "分割元パーツが範囲外です", "en": "The source part is no longer available."},
    "separate.error.invalid_face_map": {"ja": "面ID画像は2次元の整数配列で指定してください", "en": "The 3D face map is invalid. Refresh the view and try again."},
    "separate.error.no_surface": {"ja": "囲んだ範囲にモデルの面がありません", "en": "The outline does not contain any model surface."},
    "separate.error.no_active_part": {"ja": "囲んだ範囲に現在の編集パーツがありません。編集パーツを確認してください", "en": "The outline does not contain the active part. Check the selected edit part."},
    "separate.error.connected_shell": {"ja": "現在のパーツは1つにつながっています。第一版のフリーハンド分割は、浮遊している独立形状を閉じたまま切り出す場合に使用できます", "en": "This part is one connected shell. In version 0.8, freehand separation safely extracts only detached closed shapes."},
    "separate.error.insufficient_coverage": {"ja": "独立形状を十分に囲めませんでした。最も近い形状の囲み率は {coverage:.1f}% です。対象の輪郭より少し外側を一周してください", "en": "The detached shape was not fully enclosed. Best coverage was {coverage:.1f}%. Trace once just outside its outline."},
    "separate.error.whole_part": {"ja": "編集パーツ全体が選ばれました。分けたい独立形状だけを囲んでください", "en": "The whole active part was selected. Enclose only the detached shape."},
    "separate.error.selected_open": {"ja": "選択形状が閉じていないため、安全な印刷パーツへ分離できません", "en": "The selected shape is open and cannot become a safe print part."},
    "separate.error.remaining_open": {"ja": "分割後の残り形状が閉じないため、安全のため分割を中止しました", "en": "The remaining shape would be open, so separation was cancelled."},
    "separate.error.mesh_changed": {"ja": "ラッソ選択後に形状が変わったため分割できません", "en": "The mesh changed after selection. Draw the outline again."},
    "separate.error.source_missing": {"ja": "分割元パーツがなくなりました", "en": "The source part no longer exists."},
    "separate.error.source_changed": {"ja": "分割元パーツが選択時と一致しません", "en": "The source part changed after selection. Draw the outline again."},
    "separate.error.invalid_faces": {"ja": "分割対象面が不正です", "en": "The selected faces are invalid."},
    "separate.error.faces_changed": {"ja": "分割対象面が別パーツへ変更されています", "en": "Some selected faces moved to another part. Draw the outline again."},
    "paint.error_status": {"ja": "マニュアル修正エラー: {message}", "en": "Manual editing error: {message}"},
    "dialog.paint_apply_error": {"ja": "マニュアル修正を適用できません", "en": "Could Not Apply Manual Editing"},
    "preview.open_manual": {"ja": "クリックしてマニュアル修正", "en": "Click to Open Manual Editing"},
    "state.opening_manual": {"ja": "マニュアル修正を開いています…", "en": "Opening Manual Editing…"},
}


def normalize_language(value: object) -> str:
    language = str(value or "").strip().lower().replace("_", "-")
    if language.startswith("ja"):
        return "ja"
    if language.startswith("en"):
        return "en"
    return DEFAULT_LANGUAGE


def language_from_display_name(value: object) -> str:
    text = str(value or "").strip()
    for code, label in LANGUAGE_DISPLAY_NAMES.items():
        if text == label:
            return code
    return normalize_language(text)


def system_default_language() -> str:
    """Use Japanese only for a Japanese OS locale; default globally to English."""

    try:
        locale_name = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        locale_name = ""
    normalized = str(locale_name).strip().lower().replace("_", "-")
    return "ja" if normalized.startswith("ja") or "japanese" in normalized else "en"


class Translator:
    def __init__(self, language: object = DEFAULT_LANGUAGE) -> None:
        self.language = normalize_language(language)
        self._reverse: dict[str, str] = {}
        for key, translations in CATALOG.items():
            for translated in translations.values():
                self._reverse.setdefault(translated, key)

    def set_language(self, language: object) -> str:
        self.language = normalize_language(language)
        return self.language

    def text(self, key: str, /, **values: object) -> str:
        translations = CATALOG.get(key)
        if translations is None:
            # A visible key is preferable to a blank control during development.
            template = key
        else:
            template = translations.get(self.language) or translations[DEFAULT_LANGUAGE]
        if not values:
            return template
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return template

    def key_for(self, displayed_text: object) -> str | None:
        return self._reverse.get(str(displayed_text))

    def translate_known(self, displayed_text: object) -> str:
        text = str(displayed_text)
        key = self.key_for(text)
        return self.text(key) if key is not None else text


def default_preferences_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "TripoSpectrumMapper" / "ui_preferences.json"


def load_language(path: Path | None = None) -> str:
    environment = os.environ.get("TRIPO_SPECTRUM_LANGUAGE")
    if environment:
        normalized = str(environment).strip().lower().replace("_", "-")
        if normalized.startswith(("ja", "en")):
            return normalize_language(environment)
    target = Path(path) if path is not None else default_preferences_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            saved = str(payload.get("language") or "").strip().lower()
            if saved.startswith(("ja", "en")):
                return normalize_language(saved)
    except (OSError, ValueError, TypeError):
        pass
    return system_default_language()


def save_language(language: object, path: Path | None = None) -> Path:
    target = Path(path) if path is not None else default_preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "language": normalize_language(language),
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


class TkLocalizer:
    """Capture and update Tk widget copy without rebuilding the live UI.

    Explicit translation keys remain the source of truth.  Capture simply maps
    the default Japanese text created by the legacy UI to those keys, which
    keeps this migration small and avoids replacing stateful widgets.
    """

    def __init__(self, translator: Translator) -> None:
        self.translator = translator
        self._widget_bindings: list[tuple[Any, str]] = []
        self._notebook_bindings: list[tuple[Any, str, str]] = []
        self._tree_bindings: list[tuple[Any, str, str]] = []
        self._seen: set[tuple[str, int, str]] = set()

    @staticmethod
    def _walk(root: Any) -> Iterable[Any]:
        pending = [root]
        while pending:
            widget = pending.pop()
            yield widget
            try:
                pending.extend(widget.winfo_children())
            except Exception:
                continue

    def capture(self, root: Any) -> None:
        # Tk imports stay local so the pure translation/persistence layer can
        # be unit-tested on systems without an active display.
        from tkinter import ttk

        for widget in self._walk(root):
            try:
                if "text" in widget.keys():
                    key = self.translator.key_for(widget.cget("text"))
                    token = ("widget", id(widget), "text")
                    if key is not None and token not in self._seen:
                        self._widget_bindings.append((widget, key))
                        self._seen.add(token)
            except Exception:
                pass
            if isinstance(widget, ttk.Notebook):
                for tab_id in widget.tabs():
                    try:
                        key = self.translator.key_for(widget.tab(tab_id, "text"))
                    except Exception:
                        continue
                    token = ("notebook", id(widget), str(tab_id))
                    if key is not None and token not in self._seen:
                        self._notebook_bindings.append((widget, str(tab_id), key))
                        self._seen.add(token)
            if isinstance(widget, ttk.Treeview):
                columns = ("#0",) + tuple(str(value) for value in widget["columns"])
                for column in columns:
                    try:
                        key = self.translator.key_for(widget.heading(column, "text"))
                    except Exception:
                        continue
                    token = ("tree", id(widget), column)
                    if key is not None and token not in self._seen:
                        self._tree_bindings.append((widget, column, key))
                        self._seen.add(token)

    def apply(self) -> None:
        for widget, key in tuple(self._widget_bindings):
            try:
                widget.configure(text=self.translator.text(key))
            except Exception:
                pass
        for notebook, tab_id, key in tuple(self._notebook_bindings):
            try:
                notebook.tab(tab_id, text=self.translator.text(key))
            except Exception:
                pass
        for tree, column, key in tuple(self._tree_bindings):
            try:
                tree.heading(column, text=self.translator.text(key))
            except Exception:
                pass
