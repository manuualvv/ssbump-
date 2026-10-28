from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from converter import (
    BUMP_BASIS,
    MAX_TEXTURE_PIXELS,
    compute_directional_visibility,
    image_to_normals,
    load_height_map,
    load_normal_map,
    load_rgb_image,
    normal_to_ssbump,
    normal_to_weights,
    save_ssbump_tga,
    validate_height_map,
    validate_texture_size,
)


class CalculationTests(unittest.TestCase):
    def test_flat_normal_has_three_equal_channels(self):
        normals = np.array([[[0, 0, 1]]], dtype=np.float32)
        for normalized in (False, True):
            with self.subTest(normalized=normalized):
                np.testing.assert_array_equal(
                    normal_to_ssbump(normals, normalized), [[[85, 85, 85]]]
                )

    def test_tangent_normal_distinguishes_the_two_modes(self):
        normals = np.array([[[1, 0, 0]]], dtype=np.float32)
        np.testing.assert_allclose(
            normal_to_weights(normals, False), [[[2 / 3, 0, 0]]], atol=1e-6
        )
        np.testing.assert_array_equal(normal_to_ssbump(normals, False), [[[170, 0, 0]]])
        np.testing.assert_array_equal(normal_to_ssbump(normals, True), [[[255, 0, 0]]])

    def test_back_facing_normal_stays_black_without_nan(self):
        normals = np.array([[[0, 0, -1]]], dtype=np.float32)
        for normalized in (False, True):
            np.testing.assert_array_equal(normal_to_ssbump(normals, normalized), [[[0, 0, 0]]])

    def test_default_preserves_local_v05_calculation(self):
        rng = np.random.default_rng(42)
        normals = rng.normal(size=(17, 23, 3)).astype(np.float32)
        normals /= np.linalg.norm(normals, axis=2, keepdims=True)
        # Fórmula independiente que usaba converter.py local antes del cambio.
        weights = np.square(np.clip(normals @ BUMP_BASIS.T, 0.0, 1.0))
        expected_raw = np.rint(weights * 255.0).astype(np.uint8)
        weights = weights / np.maximum(weights.sum(axis=2, keepdims=True), 1e-8)
        expected_normalized = np.rint(weights * 255.0).astype(np.uint8)
        original = normals.copy()
        np.testing.assert_array_equal(normal_to_ssbump(normals), expected_normalized)
        np.testing.assert_array_equal(normal_to_ssbump(normals, False), expected_raw)
        np.testing.assert_array_equal(normals, original)
        sums = normal_to_weights(normals).sum(axis=2)
        # Las tres proyecciones negativas se recortan a cero: píxel negro.
        np.testing.assert_allclose(sums[sums > 0], 1.0, atol=1e-6)
        self.assertEqual(normal_to_ssbump(normals).dtype, np.uint8)

    def test_invalid_normals_and_options_are_rejected(self):
        invalid = (
            np.zeros((2, 2)), np.zeros((2, 2, 4)), np.empty((0, 2, 3)),
            np.zeros((1, 1, 3)), np.full((1, 1, 3), np.nan),
            np.full((1, 1, 3), np.inf), np.array([[[0, 0, 2]]]),
            np.array([[['a', 'b', 'c']]]), np.ones((1, 1, 3), dtype=complex),
        )
        for normals in invalid:
            with self.subTest(shape=normals.shape, dtype=normals.dtype):
                with self.assertRaises(ValueError):
                    normal_to_ssbump(normals)
        with self.assertRaises(ValueError):
            normal_to_ssbump(np.array([[[0, 0, 1]]]), normalize_weights="False")

    def test_height_map_is_validated_but_does_not_fake_shadows(self):
        normals = np.array([[[1, 0, 0], [0, 0, 1]]], dtype=np.float32)
        heights = np.array([[0, 1]], dtype=np.float32)
        for normalized in (False, True):
            np.testing.assert_array_equal(
                normal_to_ssbump(normals, normalized, height_map=heights),
                normal_to_ssbump(normals, normalized),
            )
        with self.assertRaisesRegex(ValueError, "coincidir"):
            normal_to_ssbump(normals, height_map=np.zeros((2, 1)))
        with self.assertRaisesRegex(NotImplementedError, "no está implementado"):
            compute_directional_visibility(heights)

    def test_invalid_heights_are_rejected(self):
        for heights in (
            np.zeros((2, 2, 3)), np.empty((0, 2)), [[-0.1]], [[1.1]],
            [[np.nan]], [[np.inf]], [[1j]], [["x"]],
        ):
            with self.subTest(heights=str(heights)):
                with self.assertRaises(ValueError):
                    validate_height_map(heights)

    def test_size_limits_accept_2k_4k_and_small_non_square_textures(self):
        for size in ((2048, 2048), (4096, 4096), (2048, 3072), (3, 2)):
            validate_texture_size(size)
        for size in ((0, 1), (-1, 2), (2.5, 3), (True, 3), (MAX_TEXTURE_PIXELS + 1, 1)):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    validate_texture_size(size)


class ImageIOTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_normal_decode_unit_length_and_flip_only_y(self):
        path = self.directory / "normal.png"
        image = Image.new("RGB", (3, 2), (180, 90, 255))
        image.save(path)
        normals = load_normal_map(path)
        flipped = load_normal_map(path, flip_green=True)
        np.testing.assert_allclose(np.linalg.norm(normals, axis=2), 1.0, atol=1e-6)
        np.testing.assert_array_equal(normals[:, :, [0, 2]], flipped[:, :, [0, 2]])
        np.testing.assert_array_equal(normals[:, :, 1], -flipped[:, :, 1])
        np.testing.assert_array_equal(image_to_normals(image), normals)
        self.assertEqual(normals.dtype, np.float32)
        with self.assertRaises(ValueError):
            image_to_normals(image, flip_green="yes")

    def test_height_8_bit_preserves_absolute_scale(self):
        path = self.directory / "height.png"
        Image.fromarray(np.array([[64, 128, 255]], dtype=np.uint8)).save(path)
        heights = load_height_map(path)
        np.testing.assert_allclose(heights, [[64 / 255, 128 / 255, 1]], atol=1e-7)
        self.assertEqual(heights.dtype, np.float32)

    def test_height_16_bit_png_and_tiff_preserve_precision(self):
        values = np.array([[0, 1, 32768, 65535]], dtype=np.uint16)
        for extension in ("png", "tiff"):
            path = self.directory / f"height.{extension}"
            Image.fromarray(values).save(path)
            with self.subTest(extension=extension):
                heights = load_height_map(path)
                np.testing.assert_allclose(heights, values / 65535.0, atol=1e-7)
                self.assertGreater(heights[0, 1], 0)

    def test_rgb_height_uses_luminance_and_float_tiff_requires_unit_range(self):
        path = self.directory / "height.png"
        Image.new("RGB", (2, 1), (64, 64, 64)).save(path)
        np.testing.assert_allclose(load_height_map(path), 64 / 255, atol=1e-7)
        path = self.directory / "height.tiff"
        Image.fromarray(np.array([[0.2, 0.7]], dtype=np.float32)).save(path)
        np.testing.assert_allclose(load_height_map(path), [[0.2, 0.7]], atol=1e-7)
        for value in (np.nan, np.inf, -1.0, 2.0):
            Image.fromarray(np.array([[value]], dtype=np.float32)).save(path)
            with self.assertRaises(ValueError):
                load_height_map(path)

    def test_missing_corrupt_and_mismatched_files(self):
        missing = self.directory / "missing.png"
        corrupt = self.directory / "corrupt.png"
        corrupt.write_bytes(b"not an image")
        for loader in (load_height_map, load_normal_map):
            with self.subTest(loader=loader.__name__):
                with self.assertRaises(FileNotFoundError):
                    loader(missing)
                with self.assertRaises(OSError):
                    loader(corrupt)
        valid = self.directory / "height.png"
        Image.new("L", (3, 2)).save(valid)
        with self.assertRaisesRegex(ValueError, "coincidir"):
            load_height_map(valid, expected_size=(2, 3))
        with self.assertRaisesRegex(ValueError, "coincidir"):
            load_rgb_image(valid, expected_size=(2, 3))

    def test_oversized_header_is_rejected_before_pixel_conversion(self):
        path = self.directory / "large.png"
        path.touch()
        for loader in (load_rgb_image, load_height_map):
            with patch("converter.Image.open") as open_image:
                image = open_image.return_value.__enter__.return_value
                image.size = (MAX_TEXTURE_PIXELS + 1, 1)
                with self.assertRaisesRegex(ValueError, "límite"):
                    loader(path)
                image.convert.assert_not_called()

    def test_tga_export_round_trip_and_source_protection(self):
        path = self.directory / "output.tga"
        image = Image.new("RGB", (3, 2), (85, 64, 20))
        save_ssbump_tga(image, path)
        with Image.open(path) as saved:
            self.assertEqual(saved.size, image.size)
            self.assertEqual(saved.mode, "RGB")
            np.testing.assert_array_equal(np.asarray(saved), np.asarray(image))
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "entrada"):
            save_ssbump_tga(image, path, protected_paths=(path,))
        with self.assertRaisesRegex(ValueError, "extensión"):
            save_ssbump_tga(image, path.with_suffix(".png"))
        self.assertEqual(path.read_bytes(), original)

    def test_failed_export_preserves_previous_file_and_cleans_temporary_data(self):
        path = self.directory / "output.tga"
        path.write_bytes(b"previous output")
        image = Image.new("RGB", (2, 2))
        with patch.object(Image.Image, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_ssbump_tga(image, path)
        self.assertEqual(path.read_bytes(), b"previous output")
        self.assertEqual(list(self.directory.iterdir()), [path])
        with self.assertRaises(OSError):
            save_ssbump_tga(image, self.directory / "missing" / "output.tga")

    def test_real_2048_pair_both_modes_and_native_resolution_export(self):
        normal_path = self.directory / "normal_2048.png"
        height_path = self.directory / "height_2048.png"
        Image.new("RGB", (2048, 2048), (255, 128, 128)).save(normal_path)
        Image.new("L", (2048, 2048), 128).save(height_path)
        normals = load_normal_map(normal_path)
        heights = load_height_map(height_path, expected_size=(2048, 2048))
        for normalized in (False, True):
            with self.subTest(normalized=normalized):
                pixels = normal_to_ssbump(normals, normalized, height_map=heights)
                self.assertEqual(pixels.shape, (2048, 2048, 3))
                expected = (255, 0, 0) if normalized else (171, 0, 0)
                np.testing.assert_array_equal(pixels[0, 0], expected)
                np.testing.assert_array_equal(pixels[-1, -1], expected)
                path = self.directory / f"output_{normalized}.tga"
                save_ssbump_tga(Image.fromarray(pixels), path)
                with Image.open(path) as saved:
                    self.assertEqual(saved.size, (2048, 2048))
                    self.assertEqual(saved.getpixel((1024, 1024)), expected)


if __name__ == "__main__":
    unittest.main()
