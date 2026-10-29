from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import CancelledError
from dataclasses import dataclass
import math
from numbers import Integral, Real

import numpy as np
from PIL import Image

MAX_TEXTURE_PIXELS = 4096 * 4096
MAX_SHADOW_DISTANCE = 256
MAX_HEIGHT_SCALE = 256.0
SHADOW_SAMPLE_COUNTS = (3, 16, 32, 64, 128, 256, 300)
_SHADOW_TILE_ROWS = 128
_SHADOW_BIAS = 1e-4  # Texeles: tolerancia para no intersectar la propia superficie.


@dataclass(frozen=True)
class ShadowSettings:
    """Geometría, intensidad y calidad del muestreo direccional."""

    height_scale: float = 32.0
    max_distance: int = 64
    strength: float = 0.75
    wrap_edges: bool = True
    sample_count: int = 64

    def __post_init__(self):
        for name, value, maximum in (
            ("La altura", self.height_scale, MAX_HEIGHT_SCALE),
            ("La intensidad", self.strength, 1.0),
        ):
            if (
                isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not math.isfinite(value) or not 0 <= value <= maximum
            ):
                raise ValueError(f"{name} debe ser un número finito entre 0 y {maximum}.")
        if (
            isinstance(self.max_distance, (bool, np.bool_))
            or not isinstance(self.max_distance, Integral)
            or not 1 <= self.max_distance <= MAX_SHADOW_DISTANCE
        ):
            raise ValueError(
                f"El alcance debe ser un entero entre 1 y {MAX_SHADOW_DISTANCE} texeles."
            )
        if not isinstance(self.wrap_edges, (bool, np.bool_)):
            raise ValueError("Repetir bordes debe ser un valor booleano.")
        if (
            isinstance(self.sample_count, (bool, np.bool_))
            or not isinstance(self.sample_count, Integral)
            or self.sample_count not in SHADOW_SAMPLE_COUNTS
        ):
            raise ValueError(f"Las muestras deben ser una de {SHADOW_SAMPLE_COUNTS}.")


def _get_shadow_settings(settings):
    if settings is None:
        return ShadowSettings()
    if not isinstance(settings, ShadowSettings):
        raise ValueError("Se esperaba una configuración ShadowSettings.")
    return settings


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("Conversión cancelada.")


def validate_texture_size(size, expected_size=None):
    """Valida dimensiones sin redimensionar ni cargar los píxeles."""
    if len(size) != 2 or any(
        not isinstance(value, (int, np.integer)) or isinstance(value, bool)
        or value <= 0 for value in size
    ):
        raise ValueError("La textura debe tener ancho y alto enteros positivos.")

    width, height = size
    if width * height > MAX_TEXTURE_PIXELS:
        raise ValueError(
            f"La textura supera el límite de {MAX_TEXTURE_PIXELS:,} píxeles "
            "(por ejemplo, 4096 x 4096)."
        )
    if expected_size is not None and tuple(size) != tuple(expected_size):
        raise ValueError(
            f"La resolución debe coincidir: {size[0]} x {size[1]} recibido; "
            f"{expected_size[0]} x {expected_size[1]} esperado."
        )


def load_rgb_image(path, expected_size=None):
    """Devuelve una copia RGB independiente del archivo, validando su cabecera."""
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(f"No se encontró la textura: {image_path}")

    with Image.open(image_path) as image:
        validate_texture_size(image.size, expected_size)
        return image.convert("RGB")


def image_to_normals(image, flip_green=False):
    """Decodifica RGB [0, 255] a normales XYZ unitarias float32 (H, W, 3).

    Trabaja sobre la imagen ya cargada para que la conversión corresponda
    exactamente a la entrada mostrada, aunque el archivo cambie en disco.
    """
    validate_texture_size(image.size)
    if not isinstance(flip_green, (bool, np.bool_)):
        raise ValueError("Invertir Y debe ser un valor booleano.")

    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    normals = (pixels / 255.0) * 2.0 - 1.0
    if flip_green:
        normals[:, :, 1] *= -1.0

    lengths = np.linalg.norm(normals, axis=2, keepdims=True)
    normals /= np.maximum(lengths, 1e-8)
    return normals


def load_normal_map(path: str, flip_green: bool = False) -> np.ndarray:
    """Carga un Normal Map y devuelve normales unitarias (H, W, 3)."""
    with load_rgb_image(path) as image:
        return image_to_normals(image, flip_green)


def _validate_scalar_map(values, expected_size, label):
    """Validación común de altura y máscara; no modifica los datos originales."""
    heights = np.asarray(values)
    if heights.ndim != 2:
        raise ValueError(f"{label} debe ser un array (height, width).")
    validate_texture_size((heights.shape[1], heights.shape[0]), expected_size)
    if not np.issubdtype(heights.dtype, np.number) or np.iscomplexobj(heights):
        raise ValueError(f"{label} debe contener números reales.")
    if not np.isfinite(heights).all() or np.any(heights < 0) or np.any(heights > 1):
        raise ValueError(f"{label}: los valores deben ser finitos y estar entre 0 y 1.")
    return heights.astype(np.float32, copy=False)


def validate_height_map(height_map, expected_size=None):
    """Valida alturas escalares finitas [0, 1], sin modificar la entrada."""
    return _validate_scalar_map(height_map, expected_size, "El Height Map")


def _load_scalar_image(path, expected_size, label):
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(f"No se encontró la textura: {image_path}")

    with Image.open(image_path) as image:
        validate_texture_size(image.size, expected_size)
        if image.mode == "F":
            heights = np.asarray(image, dtype=np.float32)
        elif image.mode.startswith("I;16") or image.mode == "I":
            heights = np.asarray(image, dtype=np.float32) / 65535.0
        else:
            heights = np.asarray(image.convert("L"), dtype=np.float32) / 255.0

    return _validate_scalar_map(heights, expected_size, label)


def load_height_map(path, expected_size=None):
    """Alturas de 8/16 bits o float [0, 1]; RGB pasa a luminancia.

    Conserva la escala absoluta, sin estirar contraste. Negro es bajo, blanco
    alto. No calcula sombras ni nuevas normales.
    """
    return _load_scalar_image(path, expected_size, "El Height Map")


def load_reflection_mask(path, expected_size=None):
    """Máscara escalar: negro sin reflejo, blanco sin atenuar el cubemap.

    Se carga una imagen gris independiente, no el RGB de un normal ni un ARM.
    Usa la misma lectura lineal de 8/16 bits o float que las alturas.
    """
    return _load_scalar_image(path, expected_size, "La máscara de reflejos")


def _sample_height_rows(heights, offset_x, offset_y, start, stop, wrap_edges):
    """Muestreo bilineal de un desplazamiento constante, limitado a una franja.

    Convención DX: X crece hacia la derecha y Y hacia abajo en la imagen.
    Sin repetición, el exterior es abierto: ningún obstáculo fuera del mapa.
    """
    height, width = heights.shape
    ix, iy = math.floor(offset_x), math.floor(offset_y)
    # Escalares Python mantienen las operaciones sobre alturas en float32;
    # np.float64 promovería cada franja y duplicaría su memoria temporal.
    fx, fy = float(offset_x - ix), float(offset_y - iy)
    x0 = np.arange(width) + ix
    y0 = np.arange(start, stop) + iy
    x1, y1 = x0 + 1, y0 + 1
    if wrap_edges:
        x0, x1 = x0 % width, x1 % width
        y0, y1 = y0 % height, y1 % height
    else:
        valid_x = (x0 + fx >= 0) & (x0 + fx <= width - 1)
        valid_y = (y0 + fy >= 0) & (y0 + fy <= height - 1)
        x0, x1 = np.clip(x0, 0, width - 1), np.clip(x1, 0, width - 1)
        y0, y1 = np.clip(y0, 0, height - 1), np.clip(y1, 0, height - 1)

    top = heights[y0[:, None], x0] * (1 - fx) + heights[y0[:, None], x1] * fx
    bottom = heights[y1[:, None], x0] * (1 - fx) + heights[y1[:, None], x1] * fx
    sampled = top * (1 - fy) + bottom * fy
    if not wrap_edges:
        sampled = np.where(valid_y[:, None] & valid_x, sampled, np.float32(-np.inf))
    return sampled


def compute_directional_visibility(
    height_map, settings=None, *, cancel_event=None, progress_callback=None
):
    """Integra visibilidad del Height en los tres canales de BUMP_BASIS.

    Entrada: alturas (H, W) en [0, 1], negro bajo y blanco alto.
    Salida float32 (H, W, 3) en [0, 1]: fracción visible ponderada por canal.
    Distancia horizontal y amplitud se expresan en texeles; se asumen cuadrados.
    Se toma una muestra bilineal por texel hasta max_distance. Es una
    aproximación hemisférica propia; sample_count=3 recupera los rayos antiguos.
    progress_callback recibe una fracción [0, 1], sin llamadas a Tkinter.
    """
    heights = validate_height_map(height_map)
    settings = _get_shadow_settings(settings)
    if progress_callback is not None and not callable(progress_callback):
        raise ValueError("El indicador de progreso debe ser una función.")
    _check_cancel(cancel_event)
    if progress_callback is not None:
        progress_callback(0.0)
    height_range = float(heights.max()) - float(heights.min())
    if settings.height_scale == 0 or height_range == 0:
        if progress_callback is not None:
            progress_callback(1.0)
        _check_cancel(cancel_event)
        return np.ones((*heights.shape, 3), dtype=np.float32)

    if settings.sample_count == 3:
        return _compute_three_ray_visibility(heights, settings, cancel_event, progress_callback)
    return _compute_hemisphere_visibility(heights, settings, cancel_event, progress_callback)


def _compute_three_ray_visibility(heights, settings, cancel_event, progress_callback):
    """Modo anterior, conservado para comparar exactamente los tres rayos centrales."""
    visibility = np.ones((*heights.shape, 3), dtype=np.float32)
    height_range = float(heights.max()) - float(heights.min())

    # Un rayo que ya superó toda la amplitud del relieve no puede bloquearse.
    planar_lengths = np.linalg.norm(BUMP_BASIS[:, :2], axis=1)
    slopes = BUMP_BASIS[:, 2] / planar_lengths
    steps = min(
        settings.max_distance,
        math.ceil(height_range * settings.height_scale / float(slopes.min())),
    )
    maximum_height = float(heights.max())
    for channel, direction in enumerate(BUMP_BASIS):
        planar = float(planar_lengths[channel])
        unit_x, unit_y = float(direction[0]) / planar, float(direction[1]) / planar
        blocked = np.zeros(heights.shape, dtype=bool)
        for distance in range(1, steps + 1):
            rise = (distance * float(slopes[channel]) + _SHADOW_BIAS) / settings.height_scale
            for start in range(0, heights.shape[0], _SHADOW_TILE_ROWS):
                _check_cancel(cancel_event)
                stop = min(start + _SHADOW_TILE_ROWS, heights.shape[0])
                ray_height = heights[start:stop] + rise
                blocked_rows = blocked[start:stop]
                active = ~blocked_rows & (ray_height < maximum_height)
                if not active.any():
                    continue
                sampled = _sample_height_rows(
                    heights, distance * unit_x, distance * unit_y,
                    start, stop, settings.wrap_edges,
                )
                blocked_rows |= active & (sampled > ray_height)
            if progress_callback is not None:
                progress_callback((channel * steps + distance) / (3 * steps))
        visibility[:, :, channel] = ~blocked
    _check_cancel(cancel_event)
    return visibility


def _hemisphere_quadrature(sample_count):
    """Rejilla determinista de igual ángulo sólido: azimuts x niveles de Z.

    El peso de cada muestra es z * max(dot(dirección, base), 0), normalizado
    por canal. El coseno z pondera la irradiancia sobre el plano del Height.
    """
    elevations = math.isqrt(sample_count)
    while sample_count % elevations:
        elevations -= 1
    azimuths = sample_count // elevations
    z = (np.arange(elevations, dtype=np.float64) + 0.5) / elevations
    phi = (np.arange(azimuths, dtype=np.float64) + 0.5) * (2 * math.pi / azimuths)
    planar = np.sqrt(1 - z * z)
    unit_xy = np.column_stack((np.cos(phi), np.sin(phi)))
    directions = np.empty((azimuths, elevations, 3), dtype=np.float64)
    directions[:, :, :2] = unit_xy[:, None, :] * planar[None, :, None]
    directions[:, :, 2] = z
    kernels = np.maximum(directions @ BUMP_BASIS.T, 0) * z[None, :, None]
    kernels /= kernels.sum(axis=(0, 1), keepdims=True)
    return unit_xy, z / planar, kernels


def _compute_hemisphere_visibility(heights, settings, cancel_event, progress_callback):
    """Reutiliza un horizonte por azimut para resolver todas sus elevaciones.

    Es equivalente a trazar cada rayo de esta cuadratura con el mismo alcance
    y muestreo bilineal, pero no repite las lecturas del Height por elevación.
    """
    unit_xy, slopes, kernels = _hemisphere_quadrature(settings.sample_count)
    height_range = float(heights.max()) - float(heights.min())
    steps = min(
        settings.max_distance,
        math.ceil(height_range * settings.height_scale / float(slopes[0])),
    )
    visibility = np.zeros((*heights.shape, 3), dtype=np.float32)
    unobstructed = np.ones(heights.shape, dtype=bool)
    total_steps = len(unit_xy) * (steps + 1)
    for azimuth, (unit_x, unit_y) in enumerate(unit_xy):
        horizon = np.zeros(heights.shape, dtype=np.float32)
        for distance in range(1, steps + 1):
            for start in range(0, heights.shape[0], _SHADOW_TILE_ROWS):
                _check_cancel(cancel_event)
                stop = min(start + _SHADOW_TILE_ROWS, heights.shape[0])
                sampled = _sample_height_rows(
                    heights, distance * unit_x, distance * unit_y,
                    start, stop, settings.wrap_edges,
                )
                obstruction = (
                    (sampled - heights[start:stop]) * settings.height_scale - _SHADOW_BIAS
                ) / distance
                np.maximum(horizon[start:stop], obstruction, out=horizon[start:stop])
            if progress_callback is not None:
                progress_callback((azimuth * (steps + 1) + distance) / total_steps)

        # Suma de pesos de todas las elevaciones que superan el horizonte.
        visible_weights = np.vstack((
            np.cumsum(kernels[azimuth, ::-1], axis=0)[::-1], np.zeros((1, 3)),
        )).astype(np.float32)
        for start in range(0, heights.shape[0], _SHADOW_TILE_ROWS):
            _check_cancel(cancel_event)
            stop = min(start + _SHADOW_TILE_ROWS, heights.shape[0])
            indices = np.searchsorted(slopes, horizon[start:stop], side="left")
            visibility[start:stop] += visible_weights[indices]
            unobstructed[start:stop] &= horizon[start:stop] <= slopes[0]
        if progress_callback is not None:
            progress_callback((azimuth + 1) * (steps + 1) / total_steps)

    np.clip(visibility, 0, 1, out=visibility)
    # Evitar diferencias de un byte por acumulación en píxeles sin oclusión.
    visibility[unobstructed] = 1
    _check_cancel(cancel_event)
    return visibility

# Vectores de referencia del shader de Source
BUMP_BASIS = np.array(
    [
        [ 0.81649661,  0.0,         0.57735026],
        [-0.40824834,  0.70710677,  0.57735026],
        [-0.40824822, -0.70710683,  0.57735026],
    ],
    dtype=np.float32,
)

def normal_to_weights(normals, normalize_weights=True):
    """Proyecta normales unitarias a tres pesos float32 antes de cuantizar."""
    normals = np.asarray(normals)
    if normals.ndim != 3 or normals.shape[2] != 3:
        raise ValueError(
            "Se esperaba un array (height, width, 3)"
        )
    validate_texture_size((normals.shape[1], normals.shape[0]))
    if not np.issubdtype(normals.dtype, np.number) or np.iscomplexobj(normals):
        raise ValueError("Las normales deben contener números reales.")
    if not isinstance(normalize_weights, (bool, np.bool_)):
        raise ValueError("Normalizar pesos debe ser un valor booleano.")
    normals = normals.astype(np.float32, copy=False)
    if not np.isfinite(normals).all():
        raise ValueError("Las normales no pueden contener NaN ni infinito.")
    lengths = np.linalg.norm(normals, axis=2)
    if not np.allclose(lengths, 1.0, atol=1e-3, rtol=0.0):
        raise ValueError("Se requieren normales unitarias, sin vectores nulos.")

    # Productos escalares con los vectores Source.
    dots = normals @ BUMP_BASIS.T

    # Limitar al intervalo [0, 1].
    dots = np.clip(dots, 0.0, 1.0)

    # Calcular los pesos direccionales.
    weights = np.square(dots)

    # Mantener por defecto la normalización elegida en la versión local 0.5.
    if normalize_weights:
        total = np.sum(weights, axis=2, keepdims=True)
        weights /= np.maximum(total, 1e-8)
    return weights


def normal_to_ssbump(
    normals, normalize_weights=True, *, height_map=None, self_shadow=False,
    shadow_settings=None, cancel_event=None, progress_callback=None,
    reflection_mask=None,
):
    """RGB uint8; con reflection_mask, RGBA con la máscara en alfa.

    La normalización, si se solicita, ocurre ANTES de aplicar visibilidad.
    self_shadow=False conserva exactamente la conversión anterior.
    """
    if not isinstance(self_shadow, (bool, np.bool_)):
        raise ValueError("Activar autosombreado debe ser un valor booleano.")
    _check_cancel(cancel_event)
    weights = normal_to_weights(normals, normalize_weights)
    if reflection_mask is not None:
        reflection_mask = _validate_scalar_map(
            reflection_mask, (weights.shape[1], weights.shape[0]), "La máscara de reflejos"
        )
    if height_map is not None:
        height_map = validate_height_map(height_map, (weights.shape[1], weights.shape[0]))
    if self_shadow:
        if height_map is None:
            raise ValueError("Cargá un Height Map para activar el autosombreado.")
        settings = _get_shadow_settings(shadow_settings)
        if settings.strength > 0:
            visibility = compute_directional_visibility(
                height_map, settings, cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            weights *= 1.0 - settings.strength * (1.0 - visibility)
        elif progress_callback is not None:
            progress_callback(1.0)
        # No renormalizar: restaurar la suma borraría parte de las sombras.
    _check_cancel(cancel_event)

    # Exportar RGB de 8 bits.
    pixels = np.rint(weights * 255.0).astype(
        np.uint8
    )

    if reflection_mask is not None:
        alpha = np.rint(reflection_mask * 255.0).astype(np.uint8)
        pixels = np.dstack((pixels, alpha))
    _check_cancel(cancel_event)
    return pixels


def save_ssbump_tga(image, path, protected_paths=()):
    """Exporta RGB/RGBA atómicamente; alfa es máscara, no desplazamiento."""
    target = Path(path).resolve()
    if target.suffix.lower() != ".tga":
        raise ValueError("Usá la extensión .tga para guardar el SSBump.")
    if target in {Path(source).resolve() for source in protected_paths if source}:
        raise ValueError("La salida no puede sobrescribir un mapa de entrada.")
    validate_texture_size(image.size)
    if image.mode not in ("RGB", "RGBA"):
        raise ValueError("La salida SSBump debe ser una imagen RGB o RGBA.")
    # Un fallo de codificación no debe destruir una exportación anterior.
    with TemporaryDirectory(prefix=".ssbump-", dir=target.parent) as directory:
        temporary = Path(directory) / "result.tga"
        image.save(temporary, format="TGA")
        temporary.replace(target)
