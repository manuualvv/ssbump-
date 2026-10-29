from concurrent.futures import CancelledError
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

import numpy as np
from PIL import Image

from converter import (
    BUMP_BASIS, ShadowSettings, compute_directional_visibility,
    load_height_map, load_normal_map, load_reflection_mask, normal_to_ssbump, save_ssbump_tga,
)


def scalar_visibility(heights, settings):
    """Referencia lenta: rayos y bilineal escalares, sin usar el muestreador real."""
    height, width = heights.shape
    result = np.ones((height, width, 3), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            for channel, basis in enumerate(BUMP_BASIS):
                planar = float(np.linalg.norm(basis[:2]))
                dx, dy = float(basis[0]) / planar, float(basis[1]) / planar
                slope = float(basis[2] / np.float32(planar))
                for distance in range(1, settings.max_distance + 1):
                    sx, sy = x + dx * distance, y + dy * distance
                    if not settings.wrap_edges and not (0 <= sx <= width - 1 and 0 <= sy <= height - 1):
                        continue
                    x0, y0 = math.floor(sx), math.floor(sy)
                    fx, fy = sx - x0, sy - y0
                    if settings.wrap_edges:
                        ax, bx = x0 % width, (x0 + 1) % width
                        ay, by = y0 % height, (y0 + 1) % height
                    else:
                        ax, bx = max(0, x0), min(width - 1, x0 + 1)
                        ay, by = max(0, y0), min(height - 1, y0 + 1)
                    sampled = (
                        float(heights[ay, ax]) * (1 - fx) * (1 - fy)
                        + float(heights[ay, bx]) * fx * (1 - fy)
                        + float(heights[by, ax]) * (1 - fx) * fy
                        + float(heights[by, bx]) * fx * fy
                    )
                    ray = float(heights[y, x]) * settings.height_scale + distance * slope + 1e-4
                    if sampled * settings.height_scale > ray:
                        result[y, x, channel] = 0
                        break
    return result


def three_ray_settings(*args, **kwargs):
    return ShadowSettings(*args, sample_count=3, **kwargs)


class DirectionalShadowTests(unittest.TestCase):
    def test_flat_surfaces_and_zero_scale_have_full_visibility(self):
        for value in (0.0, 0.4, 1.0):
            for wrap in (False, True):
                with self.subTest(value=value, wrap=wrap):
                    visibility = compute_directional_visibility(
                        np.full((7, 11), value, dtype=np.float32),
                        three_ray_settings(wrap_edges=wrap),
                    )
                    np.testing.assert_array_equal(visibility, np.ones((7, 11, 3)))
                    self.assertEqual(visibility.dtype, np.float32)
        heights = np.random.default_rng(7).random((7, 11), dtype=np.float32)
        np.testing.assert_array_equal(
            compute_directional_visibility(heights, three_ray_settings(height_scale=0)),
            np.ones((7, 11, 3)),
        )

    def test_wall_to_right_blocks_red_and_wall_to_left_blocks_other_channels(self):
        heights = np.zeros((15, 17), dtype=np.float32)
        heights[:, 8] = 1
        visibility = compute_directional_visibility(
            heights, three_ray_settings(height_scale=8, max_distance=7, wrap_edges=False)
        )
        np.testing.assert_array_equal(visibility[7, 5], [0, 1, 1])
        np.testing.assert_array_equal(visibility[7, 11], [1, 0, 0])
        np.testing.assert_array_equal(visibility[7, 8], [1, 1, 1])

    def test_dx_y_points_down_and_distinguishes_green_from_blue(self):
        heights = np.zeros((17, 17), dtype=np.float32)
        heights[8, :] = 1
        visibility = compute_directional_visibility(
            heights, three_ray_settings(height_scale=8, max_distance=7, wrap_edges=False)
        )
        np.testing.assert_array_equal(visibility[5, 8], [1, 0, 1])
        np.testing.assert_array_equal(visibility[11, 8], [1, 1, 0])

    def test_periodic_edges_see_neighbor_tile_and_open_edges_do_not(self):
        heights = np.zeros((13, 15), dtype=np.float32)
        heights[:, 0] = 1
        wrapped = compute_directional_visibility(
            heights, three_ray_settings(height_scale=8, max_distance=3, wrap_edges=True)
        )
        opened = compute_directional_visibility(
            heights, three_ray_settings(height_scale=8, max_distance=3, wrap_edges=False)
        )
        self.assertEqual(wrapped[6, -1, 0], 0)
        self.assertEqual(opened[6, -1, 0], 1)

    def test_height_amplitude_and_search_distance_change_occlusion(self):
        heights = np.zeros((11, 21), dtype=np.float32)
        heights[:, 12] = 1
        low = compute_directional_visibility(
            heights, three_ray_settings(height_scale=1, max_distance=10, wrap_edges=False)
        )
        short = compute_directional_visibility(
            heights, three_ray_settings(height_scale=16, max_distance=3, wrap_edges=False)
        )
        tall = compute_directional_visibility(
            heights, three_ray_settings(height_scale=16, max_distance=10, wrap_edges=False)
        )
        self.assertEqual(low[5, 4, 0], 1)
        self.assertEqual(short[5, 4, 0], 1)
        self.assertEqual(tall[5, 4, 0], 0)

    def test_bilinear_rays_match_independent_scalar_reference(self):
        heights = np.random.default_rng(113).uniform(0.1, 0.9, (7, 9)).astype(np.float32)
        original = heights.copy()
        heights.setflags(write=False)
        for wrap in (True, False):
            with self.subTest(wrap=wrap):
                settings = three_ray_settings(height_scale=6, max_distance=5, wrap_edges=wrap)
                actual = compute_directional_visibility(heights, settings)
                np.testing.assert_array_equal(actual, scalar_visibility(heights, settings))
        np.testing.assert_array_equal(heights, original)

    def test_offsets_and_equivalent_height_scales_preserve_geometry(self):
        heights = np.random.default_rng(9).uniform(0.1, 0.5, (7, 9)).astype(np.float32)
        settings = three_ray_settings(height_scale=8, max_distance=7)
        expected = compute_directional_visibility(heights, settings)
        np.testing.assert_array_equal(
            compute_directional_visibility(heights + 0.25, settings), expected
        )
        np.testing.assert_array_equal(
            compute_directional_visibility(
                heights / 2, three_ray_settings(height_scale=16, max_distance=7)
            ), expected,
        )

    def test_shadow_strength_and_no_normalization_after_occlusion(self):
        heights = np.zeros((15, 17), dtype=np.float32)
        heights[:, 8] = 1
        normals = np.zeros((15, 17, 3), dtype=np.float32)
        normals[:, :, 2] = 1
        for normalized in (True, False):
            settings = three_ray_settings(height_scale=8, max_distance=7, strength=1, wrap_edges=False)
            pixels = normal_to_ssbump(
                normals, normalized, height_map=heights,
                self_shadow=True, shadow_settings=settings,
            )
            np.testing.assert_array_equal(pixels[7, 5], [0, 85, 85])
            partial = normal_to_ssbump(
                normals, normalized, height_map=heights, self_shadow=True,
                shadow_settings=three_ray_settings(8, 7, 0.6, False),
            )
            np.testing.assert_array_equal(partial[7, 5], [34, 85, 85])
        # Pozo cerrado: ni siquiera el modo normalizado debe volver a iluminarlo.
        basin = np.ones((9, 9), dtype=np.float32)
        basin[4, 4] = 0
        pixels = normal_to_ssbump(
            normals[:9, :9], height_map=basin, self_shadow=True,
            shadow_settings=three_ray_settings(8, 7, 1, False),
        )
        np.testing.assert_array_equal(pixels[4, 4], [0, 0, 0])

    def test_shadow_disabled_zero_strength_and_zero_height_preserve_exact_pixels(self):
        rng = np.random.default_rng(4)
        normals = rng.normal(size=(7, 9, 3)).astype(np.float32)
        normals /= np.linalg.norm(normals, axis=2, keepdims=True)
        heights = rng.random((7, 9), dtype=np.float32)
        for normalized in (True, False):
            expected = normal_to_ssbump(normals, normalized)
            for settings in (three_ray_settings(strength=0), three_ray_settings(height_scale=0)):
                np.testing.assert_array_equal(
                    normal_to_ssbump(
                        normals, normalized, height_map=heights,
                        self_shadow=True, shadow_settings=settings,
                    ), expected,
                )
            np.testing.assert_array_equal(
                normal_to_ssbump(normals, normalized, height_map=heights), expected
            )
            shaded = normal_to_ssbump(normals, normalized, height_map=heights, self_shadow=True)
            self.assertTrue(np.all(shaded <= expected))

    def test_invalid_settings_and_missing_height_fail_explicitly(self):
        invalid = (
            {"height_scale": -1}, {"height_scale": 257}, {"height_scale": np.inf},
            {"height_scale": np.nan}, {"height_scale": True}, {"height_scale": "32"},
            {"strength": -0.1}, {"strength": 1.1}, {"strength": np.nan},
            {"strength": False}, {"max_distance": 0}, {"max_distance": 257},
            {"max_distance": 2.5}, {"max_distance": True}, {"wrap_edges": "yes"},
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    three_ray_settings(**values)
        normals = np.array([[[0, 0, 1]]], dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "Height Map"):
            normal_to_ssbump(normals, self_shadow=True)
        with self.assertRaises(ValueError):
            normal_to_ssbump(normals, self_shadow="yes")
        with self.assertRaises(ValueError):
            compute_directional_visibility([[0]], settings={})
        with self.assertRaises(ValueError):
            compute_directional_visibility([[0]], progress_callback=3)

    def test_progress_is_monotonic_and_cancellation_interrupts_work(self):
        heights = np.zeros((11, 21), dtype=np.float32)
        heights[:, 12] = 1
        progress = []
        compute_directional_visibility(heights, progress_callback=progress.append)
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 1)
        self.assertEqual(progress, sorted(progress))
        event = Event()
        event.set()
        with self.assertRaises(CancelledError):
            compute_directional_visibility(heights, cancel_event=event)
        event.clear()

        def cancel_after_some_work(fraction):
            if fraction > 0.2:
                event.set()

        with self.assertRaises(CancelledError):
            compute_directional_visibility(
                heights, cancel_event=event, progress_callback=cancel_after_some_work
            )
        self.assertTrue(event.is_set())
        event.clear()
        with self.assertRaises(CancelledError):
            compute_directional_visibility(
                np.zeros((2, 3)), cancel_event=event,
                progress_callback=lambda _: event.set(),
            )


class HighResolutionShadowTests(unittest.TestCase):
    def test_2048_png_pair_both_modes_with_directional_occlusion_and_tga_export(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normal_path, height_path = directory / "normal.png", directory / "height.png"
            Image.new("RGB", (2048, 2048), (128, 128, 255)).save(normal_path)
            heights_16 = np.zeros((2048, 2048), dtype=np.uint16)
            heights_16[:, 1024] = 65535
            Image.fromarray(heights_16).save(height_path)
            mask_path = directory / "mask.png"
            mask_bytes = np.broadcast_to(
                (np.arange(2048) % 43).astype(np.uint8), (2048, 2048),
            )
            Image.fromarray(mask_bytes).save(mask_path)
            normals, heights = load_normal_map(normal_path), load_height_map(height_path)
            mask = load_reflection_mask(mask_path)
            for normalized in (True, False):
                with self.subTest(normalized=normalized):
                    base = normal_to_ssbump(normals, normalized)
                    pixels = normal_to_ssbump(
                        normals, normalized, height_map=heights, self_shadow=True,
                        shadow_settings=ShadowSettings(16, 8, 1, False),
                        reflection_mask=mask,
                    )
                    self.assertEqual(pixels.shape, (2048, 2048, 4))
                    self.assertGreater(pixels[1024, 1020, 0], 0)
                    self.assertLess(pixels[1024, 1020, 0], base[1024, 1020, 0])
                    np.testing.assert_array_equal(pixels[1024, 1024, :3], base[1024, 1024])
                    np.testing.assert_array_equal(pixels[:, :, 3], mask_bytes)
                    path = directory / f"shadow_{normalized}.tga"
                    save_ssbump_tga(Image.fromarray(pixels), path)
                    with Image.open(path) as saved:
                        self.assertEqual(saved.size, (2048, 2048))
                        self.assertEqual(saved.mode, "RGBA")
                        np.testing.assert_array_equal(np.asarray(saved), pixels)


if __name__ == "__main__":
    unittest.main()
