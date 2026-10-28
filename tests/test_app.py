from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
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


if __name__ == "__main__":
    unittest.main()
