from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image as PillowImage

from spectrum_mapper.gui import MapperApp, _geometry_key
from spectrum_mapper.i18n import Translator
from spectrum_mapper.models import AppSettings, GeometrySettings
from spectrum_mapper.paint import encode_manual_overrides, mesh_fingerprint
from spectrum_mapper.project_bundle import (
    ProjectLoadResult,
    inspect_project_path,
    save_project_bundle_in_parent,
)

# Reuse the small, exact PreparedGeometry fixture exercised by the independent
# bundle codec tests.  Keeping one geometry source avoids a GUI test silently
# using a different face-fingerprint contract than the codec itself.
from test_project_bundle import prepared_geometry


class FakeVar:
    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class InlineExecutor:
    """Run a submitted worker now while preserving the GUI queue boundary."""

    @staticmethod
    def submit(function):
        function()
        return SimpleNamespace()


def immediate_submit(_label, function, done, *, on_error=None) -> bool:
    """Execute a MapperApp worker boundary synchronously in unit fixtures."""

    try:
        value = function()
    except Exception as exc:
        if callable(on_error):
            return bool(on_error(exc, ""))
        raise
    done(value)
    return True


def manual_project_payload(
    settings: AppSettings,
    fingerprint: str,
    overrides: np.ndarray,
    *,
    obj_path: Path,
) -> dict[str, object]:
    return {
        "schema": "obj-adjuster.project.v12",
        "settings": settings.to_dict(),
        "obj_path": str(obj_path.resolve()),
        "reference_path": r"C:\private\reference.png",
        "parts": [],
        "manual_paint": encode_manual_overrides(overrides, fingerprint),
        # Public r25 deliberately retires these geometry-changing records.
        "manual_parts": {
            "mesh_fingerprint": "legacy-parts",
            "payload": "must not survive",
        },
        "manual_joint": {
            "base_mesh_fingerprint": "legacy-joint",
            "payload": "must not survive",
        },
    }


def bare_save_app(
    source: Path,
    prepared,
    settings: AppSettings,
    overrides: np.ndarray,
) -> MapperApp:
    app = MapperApp.__new__(MapperApp)
    app.root = object()
    app.i18n = Translator("ja")
    app.paint_editor = None
    app.busy = False
    app.settings = settings
    app.obj_path = source
    app.reference_path = None
    app.prepared = prepared
    app.asset = prepared.source
    app.prepared_key = _geometry_key(settings.geometry)
    app.manual_overrides = overrides.copy()
    app.manual_fingerprint = mesh_fingerprint(prepared.final)
    app.pending_manual_payload = None
    app.manual_part_partition = {"legacy": "must be omitted"}
    app.pending_manual_part_partition = None
    app.manual_joint_record = {"legacy": "must be omitted"}
    app.pending_manual_joint_record = None
    app.status_var = FakeVar("")
    app._variables_to_settings = Mock(return_value=settings)
    app._validated_manual_overrides = Mock(
        return_value=(True, overrides.copy())
    )
    app._developer_features_enabled_committed = False
    app._submit_main = immediate_submit
    return app


def bare_load_app() -> MapperApp:
    app = MapperApp.__new__(MapperApp)
    app.root = object()
    app.i18n = Translator("ja")
    app.paint_editor = None
    app.busy = False
    app.settings = AppSettings()
    app.active_part_key = None
    app._developer_features_enabled_committed = False
    app._auto_recommend_after_geometry = False
    app._project_obj_recovery_pending = False
    app._cancel_eyedropper = Mock()
    app._note_mix_input_change = Mock()
    app._settings_to_variables = Mock()
    app._refresh_palette_widgets = Mock()
    app._clear_mix_optimization_undo = Mock()
    app._update_face_count_status = Mock()
    app._refresh_part_selector = Mock()
    app._draw_comparison_canvas = Mock()
    app._process_geometry = Mock(return_value=True)
    app.part_recommendations = {}
    app.manual_overrides = None
    app.manual_fingerprint = None
    app.pending_manual_payload = None
    app.manual_part_partition = None
    app.pending_manual_part_partition = None
    app.manual_joint_record = None
    app.pending_manual_joint_record = None
    app.reference_image = None
    app.reference_path = None
    app.reference_name_var = FakeVar("なし")
    app.ref_name_var = app.reference_name_var
    app.obj_path = None
    app.obj_name_var = FakeVar("未選択")
    app.asset = None
    app.prepared = None
    app.prepared_key = None
    app.preview_colors = None
    app.source_render = None
    app.target_render = None
    app._manual_high_face_warning_key = None
    app.status_var = FakeVar("")
    app._submit_main = immediate_submit
    app._refresh_black_free_gradient_widgets = Mock()
    app._update_assembly_status = Mock()
    app._schedule_preview = Mock()
    return app


class ProjectBundleGuiContractTests(unittest.TestCase):
    """Executable contract for the r25 GUI wiring.

    These tests intentionally call the public MapperApp commands.  The codec
    tests cover filesystem safety; this suite prevents a later toolbar change
    from reverting to standalone JSON or from rebuilding exact saved face IDs.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "hero.obj"
        self.source.write_bytes(
            b"o body\n"
            b"v 0 0 0 255 0 0\n"
            b"v 1 0 0 0 255 0\n"
            b"v 0 1 0 0 0 255\n"
            b"f 1 2 3\n"
        )
        self.prepared = prepared_geometry(self.source)
        self.settings = AppSettings(
            geometry=GeometrySettings(
                target_faces=450_000,
                preview_faces=80_000,
                adjust_face_count=False,
                up_axis="Y",
                min_component_faces=25,
                preserve_parts=True,
            )
        )
        self.geometry_key = _geometry_key(self.settings.geometry)
        self.fingerprint = mesh_fingerprint(self.prepared.final)
        self.overrides = np.asarray([3], dtype=np.int8)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_toolbar_save_uses_parent_folder_and_writes_exact_portable_bundle(self) -> None:
        app = bare_save_app(
            self.source, self.prepared, self.settings, self.overrides
        )
        destination_parent = self.root / "projects"
        destination_parent.mkdir()

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                return_value=str(destination_parent),
            ) as choose_folder,
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                side_effect=AssertionError(
                    "r25 project save must select a parent folder, not a JSON filename"
                ),
            ),
        ):
            app._save_project()

        choose_folder.assert_called_once()
        folder = destination_parent / "hero_project"
        self.assertTrue((folder / "source.obj").is_file())
        self.assertTrue((folder / "project.json").is_file())
        self.assertTrue((folder / "prepared_geometry.npz").is_file())
        wrapper = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        self.assertNotIn("obj_path", wrapper["project"])
        self.assertNotIn("reference_path", wrapper["project"])
        self.assertNotIn("manual_parts", wrapper["project"])
        self.assertNotIn("manual_joint", wrapper["project"])
        self.assertNotIn(str(self.source.parent), json.dumps(wrapper))
        self.assertEqual(
            wrapper["restore_contract"]["expected_mesh_fingerprints"],
            {"manual_paint": self.fingerprint},
        )
        self.assertIn("hero_project", app.status_var.get())

    def test_toolbar_save_refuses_existing_project_folder_without_modifying_it(self) -> None:
        app = bare_save_app(
            self.source, self.prepared, self.settings, self.overrides
        )
        destination_parent = self.root / "projects"
        destination_parent.mkdir()
        existing = destination_parent / "hero_project"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("user-owned", encoding="utf-8")

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                return_value=str(destination_parent),
            ),
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
            patch(
                "spectrum_mapper.gui.filedialog.asksaveasfilename",
                side_effect=AssertionError(
                    "r25 project save must not use the legacy JSON dialog"
                ),
            ),
        ):
            app._save_project()

        self.assertEqual(marker.read_text(encoding="utf-8"), "user-owned")
        self.assertFalse((existing / "project.json").exists())
        showerror.assert_called_once()
        self.assertIn("already exists", str(showerror.call_args.args[1]))

    def _make_exact_bundle(self, *, reference_image: Path | None = None) -> Path:
        payload = manual_project_payload(
            self.settings,
            self.fingerprint,
            self.overrides,
            obj_path=self.source,
        )
        saved = save_project_bundle_in_parent(
            self.root,
            self.source,
            payload,
            project_folder_name="exact_project",
            prepared_geometry=self.prepared,
            prepared_geometry_key=self.geometry_key,
            reference_image=reference_image,
        )
        return saved.folder

    def test_bundle_load_uses_bundled_source_and_exact_snapshot_without_obj_picker(self) -> None:
        folder = self._make_exact_bundle()
        app = bare_load_app()

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                side_effect=AssertionError(
                    "A valid portable bundle must never ask for its source OBJ"
                ),
            ) as obj_picker,
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
            patch("spectrum_mapper.gui.messagebox.showwarning"),
        ):
            app._load_project_path(folder)

        obj_picker.assert_not_called()
        showerror.assert_not_called()
        self.assertEqual(app.obj_path, folder / "source.obj")
        self.assertEqual(app.asset.path, folder / "source.obj")
        self.assertEqual(app.prepared_key, self.geometry_key)
        self.assertEqual(mesh_fingerprint(app.prepared.final), self.fingerprint)
        np.testing.assert_array_equal(app.manual_overrides, self.overrides)
        self.assertEqual(app.manual_fingerprint, self.fingerprint)
        # Re-running fTetWild/mesh cleaning could change face order; exact
        # snapshot restoration must bypass the ordinary geometry worker.
        app._process_geometry.assert_not_called()
        self.assertIsNone(app.pending_manual_part_partition)
        self.assertIsNone(app.pending_manual_joint_record)

    def test_bundle_load_installs_its_relative_reference_copy(self) -> None:
        reference = self.root / "private-original.png"
        PillowImage.new("RGB", (3, 2), (12, 34, 56)).save(reference)
        folder = self._make_exact_bundle(reference_image=reference)
        reference.unlink()
        app = bare_load_app()

        with (
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
            patch("spectrum_mapper.gui.messagebox.showwarning"),
        ):
            app._load_project_path(folder)

        showerror.assert_not_called()
        self.assertEqual(app.reference_path, folder / "reference.png")
        self.assertEqual(app.reference_image.mode, "RGBA")
        self.assertEqual(app.reference_image.size, (3, 2))
        self.assertNotIn(str(self.root), str(app.reference_path.name))

    def test_project_load_command_chooses_folder_as_primary_route(self) -> None:
        app = bare_load_app()
        folder = self._make_exact_bundle()
        app._load_project_path = Mock()

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                return_value=str(folder),
            ) as choose_folder,
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                side_effect=AssertionError("Folder selection is the primary r25 route"),
            ),
        ):
            app._load_project()

        choose_folder.assert_called_once()
        app._load_project_path.assert_called_once_with(folder)

    def test_legacy_project_command_chooses_json_without_folder_dialog(self) -> None:
        app = bare_load_app()
        legacy_json = self.root / "legacy.json"
        legacy_json.write_text(
            json.dumps({"schema": "obj-adjuster.project.v11", "settings": {}}),
            encoding="utf-8",
        )
        app._load_project_path = Mock()

        with (
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                return_value=str(legacy_json),
            ) as choose_json,
            patch(
                "spectrum_mapper.gui.filedialog.askdirectory",
                side_effect=AssertionError(
                    "The legacy menu item must use a JSON file picker"
                ),
            ),
        ):
            app._load_legacy_project()

        choose_json.assert_called_once()
        app._load_project_path.assert_called_once_with(legacy_json)

    def test_toolbar_project_menu_exposes_both_routes_and_localizes(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        app = None
        try:
            with (
                patch("spectrum_mapper.gui.load_language", return_value="ja"),
                patch.object(
                    MapperApp,
                    "_load_persistent_settings",
                    return_value=AppSettings(),
                ),
            ):
                app = MapperApp(root)
            self.assertIsInstance(app.project_load_button, ttk.Menubutton)
            self.assertEqual(app.project_load_menu.type(0), "command")
            self.assertEqual(app.project_load_menu.type(1), "separator")
            self.assertEqual(app.project_load_menu.type(2), "command")
            self.assertIn(
                "推奨", app.project_load_menu.entrycget(0, "label")
            )
            self.assertIn(
                "JSON", app.project_load_menu.entrycget(2, "label")
            )

            app.set_language("en", persist=False)
            self.assertEqual(app.project_load_button.cget("text"), "Load Project")
            self.assertEqual(
                app.project_load_menu.entrycget(0, "label"),
                "Open Project Folder (Recommended)",
            )
            self.assertEqual(
                app.project_load_menu.entrycget(2, "label"),
                "Open Legacy JSON…",
            )
        finally:
            if app is not None:
                app.app_closing = True
                try:
                    if app.poll_after_id is not None:
                        root.after_cancel(app.poll_after_id)
                except tk.TclError:
                    pass
                app.main_executor.shutdown(wait=True, cancel_futures=True)
                app.preview_executor.shutdown(wait=True, cancel_futures=True)
            try:
                root.update_idletasks()
            except tk.TclError:
                pass
            root.destroy()

    def test_legacy_json_requests_source_and_never_follows_saved_absolute_path(self) -> None:
        legacy_source = self.root / "legacy source.obj"
        legacy_source.write_bytes(self.source.read_bytes())
        legacy_json = self.root / "legacy.json"
        payload = manual_project_payload(
            self.settings,
            self.fingerprint,
            self.overrides,
            obj_path=legacy_source,
        )
        legacy_json.write_text(json.dumps(payload), encoding="utf-8")
        app = bare_load_app()

        # Cancel the explicit recovery picker.  The existing legacy source is
        # intentionally not opened just because its old absolute path exists.
        with (
            patch(
                "spectrum_mapper.gui.filedialog.askopenfilename",
                return_value="",
            ) as choose_source,
            patch("spectrum_mapper.gui.messagebox.showwarning"),
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
        ):
            app._load_project_path(legacy_json)

        choose_source.assert_called_once()
        showerror.assert_not_called()
        self.assertIsNone(app.obj_path)
        self.assertIsNone(app.prepared)
        self.assertIsNone(app.manual_overrides)
        app._process_geometry.assert_not_called()
        self.assertTrue(app._project_obj_recovery_pending)
        # Retired geometry payloads must not become invisible pending actions.
        self.assertIsNone(app.pending_manual_part_partition)
        self.assertIsNone(app.pending_manual_joint_record)

    def test_tampered_bundled_obj_fails_closed_without_geometry_or_paint(self) -> None:
        folder = self._make_exact_bundle()
        (folder / "source.obj").write_bytes(b"tampered")
        app = bare_load_app()

        with (
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
            patch("spectrum_mapper.gui.filedialog.askopenfilename") as obj_picker,
        ):
            app._load_project_path(folder)

        showerror.assert_called_once()
        self.assertIn("bundled file", str(showerror.call_args.args[1]).lower())
        obj_picker.assert_not_called()
        self.assertIsNone(app.obj_path)
        self.assertIsNone(app.prepared)
        self.assertIsNone(app.manual_overrides)
        app._process_geometry.assert_not_called()

    def test_snapshot_geometry_key_mismatch_fails_closed_instead_of_rebuilding(self) -> None:
        folder = self._make_exact_bundle()
        project_json = folder / "project.json"
        wrapper = json.loads(project_json.read_text(encoding="utf-8"))
        wrapper["project"]["settings"]["geometry"]["mirror_x"] = True
        project_json.write_text(json.dumps(wrapper), encoding="utf-8")
        # The bundle member hashes remain valid; only the snapshot/settings
        # contract is now inconsistent.
        inspected = inspect_project_path(folder)
        self.assertIsNotNone(inspected.prepared_geometry_snapshot)

        app = bare_load_app()
        with (
            patch("spectrum_mapper.gui.messagebox.showerror") as showerror,
            patch("spectrum_mapper.gui.filedialog.askopenfilename") as obj_picker,
        ):
            app._load_project_path(folder)

        showerror.assert_called_once()
        self.assertIn("geometry settings differ", str(showerror.call_args.args[1]).lower())
        obj_picker.assert_not_called()
        self.assertIsNone(app.prepared)
        self.assertIsNone(app.manual_overrides)
        app._process_geometry.assert_not_called()

    def test_corrupt_manual_payload_preserves_current_state_and_polling(self) -> None:
        folder = self._make_exact_bundle()
        project_json = folder / "project.json"
        wrapper = json.loads(project_json.read_text(encoding="utf-8"))
        wrapper["project"]["manual_paint"]["data"] = "%%%not-base64%%%"
        project_json.write_text(json.dumps(wrapper), encoding="utf-8")

        app = bare_load_app()
        old_settings = app.settings
        old_prepared = self.prepared
        old_overrides = np.asarray([1], dtype=np.int8)
        old_reference = self.root / "current-reference.png"
        app.obj_path = self.source
        app.asset = old_prepared.source
        app.prepared = old_prepared
        app.prepared_key = self.geometry_key
        app.manual_overrides = old_overrides
        app.manual_fingerprint = self.fingerprint
        app.reference_path = old_reference
        app.reference_image = object()

        # Exercise the real asynchronous queue contract.  The inline executor
        # only makes the worker deterministic; validation still finishes via
        # MapperApp._poll_queue on the main/UI side.
        app.root = Mock()
        app.root.winfo_exists.return_value = True
        app.root.after.return_value = "poll-after-id"
        app.work_queue = queue.Queue()
        app.main_executor = InlineExecutor()
        app.progress = {"value": 0}
        app.export_button = Mock()
        app.app_closing = False
        app.poll_after_id = None
        app._submit_main = MapperApp._submit_main.__get__(app, MapperApp)
        app._refresh_color_depth_widgets = Mock()
        app._refresh_surface_shell_widgets = Mock()
        app._refresh_developer_feature_visibility = Mock()

        with patch("spectrum_mapper.gui.messagebox.showerror") as showerror:
            app._load_project_path(folder)
            self.assertTrue(app.busy)
            app._poll_queue()

        showerror.assert_called_once()
        self.assertIn("破損", str(showerror.call_args.args[1]))
        self.assertFalse(app.busy)
        self.assertEqual(app.poll_after_id, "poll-after-id")
        app.root.after.assert_called_once()
        self.assertIs(app.settings, old_settings)
        self.assertEqual(app.obj_path, self.source)
        self.assertIs(app.prepared, old_prepared)
        self.assertIs(app.manual_overrides, old_overrides)
        self.assertEqual(app.reference_path, old_reference)
        app._process_geometry.assert_not_called()

    def test_poll_survives_main_done_callback_exception(self) -> None:
        app = bare_load_app()
        app.root = Mock()
        app.root.winfo_exists.return_value = True
        app.root.after.return_value = "next-poll"
        app.work_queue = queue.Queue()
        app.progress = {"value": 0}
        app.export_button = Mock()
        app.app_closing = False
        app.poll_after_id = None
        app.busy = True
        app._refresh_color_depth_widgets = Mock()
        app._refresh_surface_shell_widgets = Mock()
        app._refresh_developer_feature_visibility = Mock()
        handled = Mock(return_value=True)

        def broken_done(_value) -> None:
            raise RuntimeError("broken UI callback")

        app.work_queue.put(
            ("main_done", (broken_done, object(), handled))
        )
        with patch("spectrum_mapper.gui.messagebox.showerror") as showerror:
            app._poll_queue()

        self.assertFalse(app.busy)
        handled.assert_called_once()
        self.assertIn("broken UI callback", handled.call_args.args[1])
        showerror.assert_not_called()
        self.assertEqual(app.poll_after_id, "next-poll")
        app.root.after.assert_called_once()

    def test_load_dispatches_hash_image_and_snapshot_validation_to_worker(self) -> None:
        reference = self.root / "reference.png"
        PillowImage.new("RGB", (2, 2), (24, 48, 96)).save(reference)
        folder = self._make_exact_bundle(reference_image=reference)
        app = bare_load_app()
        main_thread_id = threading.get_ident()
        calls: dict[str, object] = {}
        inspect_threads: list[int] = []
        image_threads: list[int] = []
        snapshot_threads: list[int] = []

        def capture_submit(label, function, done, *, on_error=None) -> bool:
            calls.update(
                label=label,
                function=function,
                done=done,
                on_error=on_error,
            )
            return True

        app._submit_main = capture_submit
        real_inspect = inspect_project_path
        real_image_open = PillowImage.open
        real_snapshot_load = ProjectLoadResult.load_exact_prepared_geometry

        def observed_inspect(selected):
            inspect_threads.append(threading.get_ident())
            return real_inspect(selected)

        def observed_image_open(selected, *args, **kwargs):
            image_threads.append(threading.get_ident())
            return real_image_open(selected, *args, **kwargs)

        def observed_snapshot_load(load_result, *args, **kwargs):
            snapshot_threads.append(threading.get_ident())
            return real_snapshot_load(load_result, *args, **kwargs)

        with (
            patch("spectrum_mapper.gui.inspect_project_path", observed_inspect),
            patch("spectrum_mapper.gui.Image.open", observed_image_open),
            patch.object(
                ProjectLoadResult,
                "load_exact_prepared_geometry",
                observed_snapshot_load,
            ),
        ):
            app._load_project_path(folder)
            self.assertIn("function", calls)
            self.assertEqual(inspect_threads, [])
            self.assertEqual(image_threads, [])
            self.assertEqual(snapshot_threads, [])
            with ThreadPoolExecutor(max_workers=1) as executor:
                validated_load = executor.submit(calls["function"]).result()

        self.assertEqual(validated_load[0], "exact")
        self.assertTrue(inspect_threads)
        self.assertTrue(image_threads)
        self.assertTrue(snapshot_threads)
        self.assertTrue(all(value != main_thread_id for value in inspect_threads))
        self.assertTrue(all(value != main_thread_id for value in image_threads))
        self.assertTrue(all(value != main_thread_id for value in snapshot_threads))
        # Read-only validation must not install any project state until the UI
        # callback consumes the fully validated worker result.
        self.assertIsNone(app.obj_path)
        self.assertIsNone(app.prepared)
        self.assertIsNone(app.manual_overrides)


if __name__ == "__main__":
    unittest.main()
