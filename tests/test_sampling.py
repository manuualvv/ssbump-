"""Cuadratura hemisférica frente a rayos individuales y alfa de reflejos."""
from concurrent.futures import CancelledError
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

import numpy as np
from PIL import Image

from converter import (
    BUMP_BASIS, SHADOW_SAMPLE_COUNTS, ShadowSettings,
    compute_directional_visibility, load_reflection_mask,
    normal_to_ssbump, save_ssbump_tga,
)


def scalar_hemisphere_visibility(heights, settings):
    """Traza cada rayo por separado: no usa horizontes ni funciones del conversor."""
    levels = max(n for n in range(1, math.isqrt(settings.sample_count) + 1)
                 if settings.sample_count % n == 0)
    azimuths = settings.sample_count // levels
    height, width = heights.shape
    result = np.zeros((height, width, 3), dtype=np.float64)
    denominator = np.zeros(3, dtype=np.float64)
    for azimuth in range(azimuths):
        angle = (azimuth + 0.5) * 2 * math.pi / azimuths
        dx, dy = math.cos(angle), math.sin(angle)
        for level in range(levels):
            z = (level + 0.5) / levels
            planar = math.sqrt(1 - z * z)
            direction = np.array([dx * planar, dy * planar, z])
            weights = np.maximum(BUMP_BASIS @ direction, 0) * z
            denominator += weights
            for y in range(height):
                for x in range(width):
                    visible = True
                    for distance in range(1, settings.max_distance + 1):
                        sx, sy = x + dx * distance, y + dy * distance
                        if not settings.wrap_edges and not (0 <= sx <= width - 1 and 0 <= sy <= height - 1):
                            continue
                        left, top = math.floor(sx), math.floor(sy)
                        fx, fy = sx - left, sy - top
                        sample = 0.0
                        for ox, wx in ((0, 1 - fx), (1, fx)):
                            for oy, wy in ((0, 1 - fy), (1, fy)):
                                ix, iy = left + ox, top + oy
                                if settings.wrap_edges:
                                    ix, iy = ix % width, iy % height
                                else:
                                    ix = min(width - 1, max(0, ix))
                                    iy = min(height - 1, max(0, iy))
                                sample += float(heights[iy, ix]) * wx * wy
                        ray_height = (
                            float(heights[y, x]) * settings.height_scale
                            + distance * z / planar + 1e-4
                        )
                        if sample * settings.height_scale > ray_height:
                            visible = False
                            break
                    if visible:
                        result[y, x] += weights
    return result / denominator


class HemisphereSamplingTests(unittest.TestCase):
    def test_horizons_match_independent_individual_rays(self):
        heights = np.random.default_rng(51).uniform(0.1, 0.9, (5, 7)).astype(np.float32)
        original = heights.copy()
        heights.setflags(write=False)
        for count in (16, 64, 300):
            for wrap in (False, True):
                with self.subTest(count=count, wrap=wrap):
                    settings = ShadowSettings(5, 4, 1, wrap, count)
                    expected = scalar_hemisphere_visibility(heights, settings)
                    actual = compute_directional_visibility(heights, settings)
                    np.testing.assert_allclose(actual, expected, atol=3e-7, rtol=0)
                    self.assertEqual(actual.dtype, np.float32)
                    self.assertTrue(np.all((actual >= 0) & (actual <= 1)))
        np.testing.assert_array_equal(heights, original)

    def test_grazing_occlusion_missed_by_three_central_rays_is_detected(self):
        heights = np.zeros((21, 29), dtype=np.float32)
        heights[:, 18] = 1
        old = compute_directional_visibility(heights, ShadowSettings(2, 12, 1, False, 3))
        new = compute_directional_visibility(heights, ShadowSettings(2, 12, 1, False, 64))
        np.testing.assert_array_equal(old[10, 10], [1, 1, 1])
        self.assertLess(new[10, 10, 0], 1)
        self.assertLess(new[10, 10, 0], new[10, 10, 1])
        self.assertGreater(new[10, 10, 0], 0)

    def test_wall_returns_partial_directional_visibility_and_keeps_unoccluded_pixels_exact(self):
        heights = np.zeros((15, 17), dtype=np.float32)
        heights[:, 8] = 1
        for count in SHADOW_SAMPLE_COUNTS[1:]:
            with self.subTest(count=count):
                visibility = compute_directional_visibility(
                    heights, ShadowSettings(8, 7, 1, False, count),
                )
                self.assertTrue(np.any((visibility > 0) & (visibility < 1)))
                self.assertLess(visibility[7, 5, 0], visibility[7, 5, 1])
                self.assertLess(visibility[7, 11, 1], visibility[7, 11, 0])
                np.testing.assert_array_equal(visibility[:, 8], np.ones((15, 3)))

    def test_all_qualities_preserve_flat_base_pixels_and_do_not_renormalize_shadows(self):
        rng = np.random.default_rng(8)
        normals = rng.normal(size=(7, 9, 3)).astype(np.float32)
        normals /= np.linalg.norm(normals, axis=2, keepdims=True)
        flat = np.full((7, 9), 0.4, dtype=np.float32)
        heights = rng.random((7, 9), dtype=np.float32)
        for normalized in (False, True):
            base = normal_to_ssbump(normals, normalized)
            for count in SHADOW_SAMPLE_COUNTS:
                with self.subTest(normalized=normalized, count=count):
                    settings = ShadowSettings(8, 5, 1, True, count)
                    np.testing.assert_array_equal(normal_to_ssbump(
                        normals, normalized, height_map=flat, self_shadow=True,
                        shadow_settings=settings,
                    ), base)
                    shaded = normal_to_ssbump(
                        normals, normalized, height_map=heights, self_shadow=True,
                        shadow_settings=settings,
                    )
                    self.assertTrue(np.all(shaded <= base))
                    self.assertLess(int(shaded.sum()), int(base.sum()))

    def test_invalid_quality_is_rejected_and_default_is_64(self):
        self.assertEqual(ShadowSettings().sample_count, 64)
        for count in (0, 4, 63, 301, 64.0, True, np.bool_(True), "64", None):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    ShadowSettings(sample_count=count)

    def test_dx_y_and_mirrored_walls_exchange_green_and_blue(self):
        heights = np.zeros((17, 17), dtype=np.float32)
        heights[8, :] = 1
        for count in (16, 64, 300):
            visibility = compute_directional_visibility(
                heights, ShadowSettings(8, 7, 1, False, count),
            )
            self.assertLess(visibility[5, 8, 1], visibility[5, 8, 2])
            self.assertLess(visibility[11, 8, 2], visibility[11, 8, 1])
            np.testing.assert_allclose(
                visibility[5, 8], visibility[11, 8, [0, 2, 1]], atol=3e-7, rtol=0,
            )

    def test_each_quality_reports_progress_and_obeys_cancellation(self):
        heights = np.zeros((9, 11), dtype=np.float32)
        heights[:, 5] = 1
        for count in (3, 64, 300):
            settings = ShadowSettings(4, 5, 1, True, count)
            progress = []
            compute_directional_visibility(heights, settings, progress_callback=progress.append)
            self.assertEqual((progress[0], progress[-1]), (0, 1))
            self.assertEqual(progress, sorted(progress))
            event = Event()

            def cancel(fraction):
                if fraction > 0.15:
                    event.set()

            with self.assertRaises(CancelledError):
                compute_directional_visibility(
                    heights, settings, cancel_event=event, progress_callback=cancel,
                )


class ReflectionMaskTests(unittest.TestCase):
    def test_alpha_round_trip_preserves_rgb_and_small_mask_values(self):
        normals = np.zeros((2, 3, 3), dtype=np.float32)
        normals[:, :, 2] = 1
        alpha = np.array([[0, 1, 15], [32, 42, 255]], dtype=np.uint8)
        for normalized in (False, True):
            rgb = normal_to_ssbump(normals, normalized)
            rgba = normal_to_ssbump(normals, normalized, reflection_mask=alpha / 255)
            np.testing.assert_array_equal(rgba[:, :, :3], rgb)
            np.testing.assert_array_equal(rgba[:, :, 3], alpha)
            with TemporaryDirectory() as temporary:
                path = Path(temporary) / "masked.tga"
                save_ssbump_tga(Image.fromarray(rgba), path)
                self.assertEqual(path.read_bytes()[16], 32)
                with Image.open(path) as saved:
                    self.assertEqual(saved.mode, "RGBA")
                    np.testing.assert_array_equal(np.asarray(saved), rgba)

    def test_mask_loading_keeps_absolute_scale_and_rejects_size_or_invalid_values(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mask.png"
            Image.fromarray(np.array([[0, 6553, 65535]], dtype=np.uint16)).save(path)
            actual = load_reflection_mask(path, (3, 1))
            np.testing.assert_allclose(actual, [[0, 6553 / 65535, 1]], atol=1e-7)
            with self.assertRaises(ValueError):
                load_reflection_mask(path, (1, 3))
        normals = np.array([[[0, 0, 1]]], dtype=np.float32)
        for mask in ([[np.nan]], [[np.inf]], [[-1]], [[1.1]], [[[1]]], [[1, 1]], [[True]], [[1j]]):
            with self.subTest(mask=mask):
                with self.assertRaises(ValueError):
                    normal_to_ssbump(normals, reflection_mask=mask)


if __name__ == "__main__":
    unittest.main()
