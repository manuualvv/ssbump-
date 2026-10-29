from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from main import SSBumpApp


class AppTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk no está disponible: {error}")
        self.root.withdraw()
        self.app = SSBumpApp(self.root)
        self.addCleanup(self.app.on_close)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.normal_path = self.directory / "normal.png"
        self.height_path = self.directory / "height.png"
        Image.new("RGB", (3, 2), (255, 128, 128)).save(self.normal_path)
        Image.new("L", (3, 2), 128).save(self.height_path)

    def open_normal(self, path=None):
        with patch("main.filedialog.askopenfilename", return_value=str(path or self.normal_path)):
            self.app.open_image()

    def open_height(self, path=None):
        with patch("main.filedialog.askopenfilename", return_value=str(path or self.height_path)):
            self.app.open_height_image()

    def open_mask(self, path):
        with patch("main.filedialog.askopenfilename", return_value=str(path)):
            self.app.open_reflection_mask()

    def wait_for_conversion(self):
        deadline = time.monotonic() + 10
        while self.app._future is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.assertIsNone(self.app._future, "La conversión no finalizó en 10 segundos")

    def test_initial_state_and_height_can_be_loaded_first(self):
        self.assertTrue(self.app.generate_button.instate(["disabled"]))
        self.assertTrue(self.app.normalize_weights.get())
        self.open_height()
        self.assertIsNotNone(self.app.height_values)
        self.assertIsNotNone(self.app.height_preview.image)
        self.assertTrue(self.app.generate_button.instate(["disabled"]))
        self.open_normal()
        self.assertIsNotNone(self.app.normal_preview.image)
        self.assertTrue(self.app.generate_button.instate(["!disabled"]))

    def test_successful_conversion_in_both_modes_uses_loaded_snapshot(self):
        self.open_normal()
        self.open_height()
        # Eliminar el archivo demuestra que se procesa la entrada mostrada en memoria.
        self.normal_path.unlink()
        for normalized in (True, False):
            self.app.normalize_weights.set(normalized)
            self.app.invalidate_result()
            with patch("main.messagebox.showerror") as showerror:
                self.app.generate_ssbump()
                self.assertTrue(self.app.normal_open_button.instate(["disabled"]))
                self.assertTrue(self.app.raw_button.instate(["disabled"]))
                self.wait_for_conversion()
                showerror.assert_not_called()
            self.assertIsNotNone(self.app.ssbump_preview.image)
            self.assertTrue(self.app.save_button.instate(["!disabled"]))
            expected = (255, 0, 0) if normalized else (171, 0, 0)
            self.assertEqual(self.app.ssbump_image.getpixel((0, 0)), expected)

    def test_mismatched_height_preserves_current_inputs_and_result(self):
        self.open_normal()
        self.open_height()
        self.app.ssbump_image = Image.new("RGB", (3, 2))
        previous_height = self.app.height_values
        previous_result = self.app.ssbump_image
        wrong = self.directory / "wrong.png"
        Image.new("L", (2, 3)).save(wrong)
        with patch("main.messagebox.showerror") as showerror:
            self.open_height(wrong)
            showerror.assert_called_once()
        self.assertIs(self.app.height_values, previous_height)
        self.assertIs(self.app.ssbump_image, previous_result)
        self.assertEqual(self.app.height_path, self.height_path)

    def test_mismatched_normal_when_height_was_loaded_first(self):
        self.open_height()
        wrong = self.directory / "wrong.png"
        Image.new("RGB", (2, 3)).save(wrong)
        with patch("main.messagebox.showerror") as showerror:
            self.open_normal(wrong)
            showerror.assert_called_once()
        self.assertIsNone(self.app.original_image)
        self.assertTrue(self.app.generate_button.instate(["disabled"]))

    def test_cancel_and_corrupt_file_preserve_current_input(self):
        self.open_normal()
        original = self.app.original_image
        with patch("main.filedialog.askopenfilename", return_value=""):
            self.app.open_image()
            self.app.open_height_image()
        corrupt = self.directory / "bad.png"
        corrupt.write_bytes(b"broken")
        with patch("main.messagebox.showerror") as showerror:
            self.open_normal(corrupt)
            self.open_height(corrupt)
            self.assertEqual(showerror.call_count, 2)
        self.assertIs(self.app.original_image, original)
        self.assertIsNone(self.app.height_values)

    def test_mode_y_and_height_changes_invalidate_output(self):
        self.open_normal()
        self.open_height()
        for action in (self.app.raw_button.invoke, self.app.flip_green_button.invoke,
                       self.app.clear_height_image):
            self.app.ssbump_image = Image.new("RGB", (3, 2))
            self.app._set_busy(False)
            action()
            self.assertIsNone(self.app.ssbump_image)
            self.assertTrue(self.app.save_button.instate(["disabled"]))
            self.assertTrue(self.app.compare_button.instate(["disabled"]))
        self.assertIsNone(self.app.height_values)

    def test_worker_failure_shows_error_and_restores_controls(self):
        self.open_normal()
        failed = Future()
        failed.set_exception(MemoryError("Sin memoria para la textura"))
        with patch.object(self.app._executor, "submit", return_value=failed):
            with patch("main.messagebox.showerror") as showerror:
                self.app.generate_ssbump()
                self.wait_for_conversion()
                showerror.assert_called_once()
        self.assertIsNone(self.app.ssbump_image)
        self.assertTrue(self.app.generate_button.instate(["!disabled"]))
        self.assertTrue(self.app.save_button.instate(["disabled"]))

    def test_second_conversion_is_blocked_while_busy(self):
        self.open_normal()
        pending = Future()
        with patch.object(self.app._executor, "submit", return_value=pending) as submit:
            self.app.generate_ssbump()
            self.app.generate_ssbump()
            submit.assert_called_once()
            self.assertTrue(self.app.generate_button.instate(["disabled"]))
        pending.set_result(np.full((2, 3, 3), 85, dtype=np.uint8))
        self.wait_for_conversion()

    def test_reference_comparison_reports_exact_match_and_rejects_wrong_size(self):
        self.app.ssbump_image = Image.new("RGB", (3, 2), (85, 85, 85))
        reference = self.directory / "reference.tga"
        self.app.ssbump_image.save(reference)
        with patch("main.filedialog.askopenfilename", return_value=str(reference)):
            with patch("main.messagebox.showinfo") as info:
                self.app.compare_reference()
                self.assertIn("100.00%", info.call_args.args[1])
            Image.new("RGB", (2, 3)).save(reference)
            with patch("main.messagebox.showerror") as error:
                self.app.compare_reference()
                error.assert_called_once()

    def test_save_protects_loaded_input(self):
        path = self.directory / "normal.tga"
        Image.new("RGB", (3, 2), (128, 128, 255)).save(path)
        self.open_normal(path)
        self.app.ssbump_image = Image.new("RGB", (3, 2))
        before = path.read_bytes()
        with patch("main.filedialog.asksaveasfilename", return_value=str(path)):
            with patch("main.messagebox.showerror") as showerror:
                self.app.save_image()
                showerror.assert_called_once()
        self.assertEqual(path.read_bytes(), before)

    def test_shadow_controls_start_disabled_and_require_height_to_generate(self):
        self.open_normal()
        self.assertFalse(self.app.self_shadow.get())
        self.assertTrue(all(field.instate(["disabled"]) for field in self.app.shadow_fields))
        self.app.shadow_button.invoke()
        self.assertTrue(all(field.instate(["!disabled"]) for field in self.app.shadow_fields))
        with patch.object(self.app._executor, "submit") as submit:
            with patch("main.messagebox.showerror") as error:
                self.app.generate_ssbump()
                error.assert_called_once()
                self.assertIn("Height Map", error.call_args.args[1])
            submit.assert_not_called()
        self.assertIsNone(self.app._future)

    def test_shadow_numeric_values_are_validated_before_starting_worker(self):
        self.open_normal()
        self.open_height()
        self.app.shadow_button.invoke()
        cases = (
            (self.app.height_scale, "nan"), (self.app.height_scale, "-1"),
            (self.app.height_scale, "abc"), (self.app.shadow_distance, "2.5"),
            (self.app.shadow_distance, "0"), (self.app.shadow_strength, "101"),
            (self.app.shadow_samples, "63"), (self.app.shadow_samples, "64.0"),
        )
        for variable, invalid in cases:
            previous = variable.get()
            variable.set(invalid)
            with self.subTest(invalid=invalid):
                with patch("main.messagebox.showerror") as error:
                    with patch.object(self.app._executor, "submit") as submit:
                        self.app.generate_ssbump()
                        submit.assert_not_called()
                        error.assert_called_once()
            variable.set(previous)
        self.app.height_scale.set("8,5")
        self.app.shadow_strength.set("50,0")
        settings = self.app._read_shadow_settings()
        self.assertEqual(settings.height_scale, 8.5)
        self.assertEqual(settings.strength, 0.5)
        self.assertEqual(settings.sample_count, 64)
        self.assertTrue(self.app.samples_field.instate(["readonly"]))

    def test_real_shadow_worker_updates_result_progress_and_export_name(self):
        Image.new("RGB", (17, 15), (128, 128, 255)).save(self.normal_path)
        heights = np.zeros((15, 17), dtype=np.uint16)
        heights[:, 8] = 65535
        Image.fromarray(heights).save(self.height_path)
        self.open_normal()
        self.open_height()
        self.app.shadow_button.invoke()
        self.app.height_scale.set("8")
        self.app.shadow_distance.set("7")
        self.app.shadow_strength.set("100")
        self.app.shadow_samples.set("3")
        self.app.wrap_edges.set(False)
        with patch("main.messagebox.showerror") as error:
            self.app.generate_ssbump()
            self.assertTrue(self.app.shadow_button.instate(["disabled"]))
            self.assertTrue(all(field.instate(["disabled"]) for field in self.app.shadow_fields))
            self.wait_for_conversion()
            error.assert_not_called()
        self.assertEqual(self.app.ssbump_image.getpixel((5, 7))[0], 0)
        self.assertTrue(self.app._result_shadowed)
        self.assertEqual(self.app.progress.get(), 100)
        self.assertTrue(all(field.instate(["!disabled"]) for field in self.app.shadow_fields))
        output = self.directory / "result.tga"
        with patch("main.filedialog.asksaveasfilename", return_value=str(output)) as dialog:
            with patch("main.messagebox.showinfo"):
                self.app.save_image()
            self.assertTrue(dialog.call_args.kwargs["initialfile"].endswith("_normalized_shadow.tga"))
        with Image.open(output) as image:
            self.assertEqual(image.size, (17, 15))
            self.assertEqual(image.getpixel((5, 7))[0], 0)

    def test_every_shadow_setting_invalidates_previous_output(self):
        self.open_normal()
        self.open_height()
        self.app.shadow_button.invoke()
        for change in (
            lambda: self.app.height_scale.set("16"),
            lambda: self.app.shadow_distance.set("32"),
            lambda: self.app.shadow_strength.set("50"),
            lambda: self.app.shadow_samples.set("128"),
            self.app.wrap_button.invoke, self.app.shadow_button.invoke,
        ):
            self.app.ssbump_image = Image.new("RGB", (3, 2))
            self.app._result_shadowed = True
            self.app.progress.set(100)
            self.app._set_busy(False)
            change()
            self.assertIsNone(self.app.ssbump_image)
            self.assertFalse(self.app._result_shadowed)
            self.assertEqual(self.app.progress.get(), 0)
            self.assertTrue(self.app.save_button.instate(["disabled"]))

    def test_cancel_discards_late_result_and_restores_controls_without_error_dialog(self):
        self.open_normal()
        pending = Future()
        pending.set_running_or_notify_cancel()
        with patch.object(self.app._executor, "submit", return_value=pending):
            self.app.generate_ssbump()
        self.app._progress_queue.put(0.3)
        self.root.after_cancel(self.app._poll_id)
        self.app._poll_conversion()
        self.assertEqual(self.app.progress.get(), 30)
        self.app.cancel_generation()
        self.assertTrue(self.app._cancel_event.is_set())
        self.assertTrue(self.app.cancel_button.instate(["disabled"]))
        pending.set_result(np.full((2, 3, 3), 85, dtype=np.uint8))
        with patch("main.messagebox.showerror") as error:
            self.wait_for_conversion()
            error.assert_not_called()
        self.assertIsNone(self.app.ssbump_image)
        self.assertIn("cancelada", self.app.status.get())
        self.assertTrue(self.app.generate_button.instate(["!disabled"]))
        self.assertTrue(self.app.save_button.instate(["disabled"]))

    def test_closing_signals_cancellation_and_can_be_called_twice(self):
        event = Event()
        self.app._cancel_event = event
        self.app.on_close()
        self.assertTrue(event.is_set())
        self.app.on_close()

    def test_mask_can_be_loaded_first_and_failed_inputs_preserve_state(self):
        mask_path = self.directory / "mask.png"
        Image.new("L", (3, 2), 15).save(mask_path)
        self.open_mask(mask_path)
        wrong = self.directory / "wrong.png"
        Image.new("RGB", (2, 3)).save(wrong)
        with patch("main.messagebox.showerror") as error:
            self.open_normal(wrong)
            self.open_height(wrong)
            self.assertEqual(error.call_count, 2)
        self.assertIsNone(self.app.original_image)
        self.assertIsNone(self.app.height_values)
        self.open_normal()
        self.open_height()
        previous = self.app.mask_values
        self.app.ssbump_image = Image.new("RGBA", (3, 2))
        result = self.app.ssbump_image
        with patch("main.messagebox.showerror") as error:
            self.open_mask(wrong)
            error.assert_called_once()
        self.assertIs(self.app.mask_values, previous)
        self.assertIs(self.app.ssbump_image, result)
        with patch("main.filedialog.askopenfilename", return_value=""):
            self.app.open_reflection_mask()
        self.assertIs(self.app.ssbump_image, result)
        self.app.clear_reflection_mask()
        self.assertIsNone(self.app.mask_values)
        self.assertIsNone(self.app.ssbump_image)

    def test_rgba_worker_preview_export_and_rgb_comparison(self):
        self.open_normal()
        self.open_height()
        mask_path = self.directory / "mask.png"
        alpha = np.array([[0, 1, 15], [32, 40, 42]], dtype=np.uint8)
        Image.fromarray(alpha).save(mask_path)
        self.open_mask(mask_path)
        mask_path.unlink()  # Se usa la máscara cargada, igual que normal/altura.
        self.app.shadow_button.invoke()
        self.app.generate_ssbump()
        self.assertTrue(self.app.mask_open_button.instate(["disabled"]))
        self.assertTrue(self.app.mask_clear_button.instate(["disabled"]))
        self.wait_for_conversion()
        self.assertEqual(self.app.ssbump_image.mode, "RGBA")
        np.testing.assert_array_equal(np.asarray(self.app.ssbump_image)[:, :, 3], alpha)
        self.assertIn("64 muestras", self.app.status.get())
        self.assertIn("alfa", self.app.status.get())
        photo = self.app.ssbump_preview.image
        self.assertFalse(self.root.tk.call(str(photo), "transparency", "get", 0, 0))
        output = self.directory / "result.tga"
        with patch("main.filedialog.asksaveasfilename", return_value=str(output)) as dialog:
            with patch("main.messagebox.showinfo"):
                self.app.save_image()
        self.assertTrue(dialog.call_args.kwargs["initialfile"].endswith("_shadow_64samples_mask.tga"))
        with Image.open(output) as saved:
            np.testing.assert_array_equal(np.asarray(saved)[:, :, 3], alpha)
        reference = self.directory / "reference.png"
        self.app.ssbump_image.convert("RGB").save(reference)
        with patch("main.filedialog.askopenfilename", return_value=str(reference)):
            with patch("main.messagebox.showinfo") as info:
                self.app.compare_reference()
                self.assertIn("100.00%", info.call_args.args[1])
                self.assertIn("alfa no incluido", info.call_args.args[1])

    def test_export_cannot_overwrite_loaded_reflection_mask(self):
        self.open_normal()
        mask_path = self.directory / "mask.tga"
        Image.new("L", (3, 2), 20).save(mask_path)
        self.open_mask(mask_path)
        before = mask_path.read_bytes()
        self.app.ssbump_image = Image.new("RGBA", (3, 2))
        with patch("main.filedialog.asksaveasfilename", return_value=str(mask_path)):
            with patch("main.messagebox.showerror") as error:
                self.app.save_image()
                error.assert_called_once()
        self.assertEqual(mask_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
