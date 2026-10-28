from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

MAX_TEXTURE_PIXELS = 4096 * 4096


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


def validate_height_map(height_map, expected_size=None):
    """Valida alturas escalares finitas [0, 1], sin modificar la entrada."""
    heights = np.asarray(height_map)
    if heights.ndim != 2:
        raise ValueError("El Height Map debe ser un array (height, width).")
    validate_texture_size((heights.shape[1], heights.shape[0]), expected_size)
    if not np.issubdtype(heights.dtype, np.number) or np.iscomplexobj(heights):
        raise ValueError("El Height Map debe contener números reales.")
    if not np.isfinite(heights).all() or np.any(heights < 0) or np.any(heights > 1):
        raise ValueError("Las alturas deben ser finitas y estar entre 0 y 1.")
    return heights.astype(np.float32, copy=False)


def load_height_map(path, expected_size=None):
    """Carga alturas de 8/16 bits o float [0, 1]; RGB se convierte a luminancia.

    Conserva la escala absoluta: no estira el contraste de cada imagen.
    Negro representa 0 y blanco 1. No calcula sombras ni nuevas normales.
    """
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

    return validate_height_map(heights, expected_size)


def compute_directional_visibility(height_map):
    """Punto de extensión para un FUTURO algoritmo de autosombreado.

    Entrada: alturas (H, W) en [0, 1]. El futuro resultado será (H, W, 3),
    visibilidad en [0, 1] para cada dirección de BUMP_BASIS. Aún faltan
    escala física, muestreo de rayos, bordes y validación en Source.
    Nunca se devuelve una visibilidad ficticia ni se llama desde la UI.
    """
    validate_height_map(height_map)
    raise NotImplementedError("El autosombreado direccional aún no está implementado.")

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


def normal_to_ssbump(normals, normalize_weights=True, *, height_map=None):
    """Devuelve RGB uint8 (H, W, 3) en cualquiera de los dos modos.

    Height Map opcional: se valida su resolución, pero NO modifica los pesos
    hasta que exista un algoritmo de autosombreado implementado y probado.
    """
    weights = normal_to_weights(normals, normalize_weights)
    if height_map is not None:
        validate_height_map(height_map, (weights.shape[1], weights.shape[0]))

    # Exportar RGB de 8 bits.
    pixels = np.rint(weights * 255.0).astype(
        np.uint8
    )

    return pixels


def save_ssbump_tga(image, path, protected_paths=()):
    """Exporta RGB mediante reemplazo atómico y protege las entradas cargadas."""
    target = Path(path).resolve()
    if target.suffix.lower() != ".tga":
        raise ValueError("Usá la extensión .tga para guardar el SSBump.")
    if target in {Path(source).resolve() for source in protected_paths if source}:
        raise ValueError("La salida no puede sobrescribir un mapa de entrada.")
    validate_texture_size(image.size)
    if image.mode != "RGB":
        raise ValueError("La salida SSBump debe ser una imagen RGB.")
    # Un fallo de codificación no debe destruir una exportación anterior.
    with TemporaryDirectory(prefix=".ssbump-", dir=target.parent) as directory:
        temporary = Path(directory) / "result.tga"
        image.save(temporary, format="TGA")
        temporary.replace(target)
