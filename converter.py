from pathlib import Path
import numpy as np
from PIL import Image

def load_normal_map(path: str, flip_green: bool = False) -> np.ndarray:
    """
    Carga un Normal Map y devuelve un array
    de vectores normales unitarios

    Shape: (height, width, 3)s
    Dtype: float32
    """

    image_path = Path(path)

    if not image_path.is_file():
        raise FileNotFoundError(
            f"No se encontró la textura: {image_path}"
        )
    
    # Leer imagen y garantizar tres canales RGB
    with Image.open(image_path) as image:
        pixels = np.asarray(
            image.convert("RGB"), dtype=np.float32
        )
    
    # Convertir rango [0, 255] a [-1, 1]
    normals = (pixels / 255.0) * 2.0 - 1.0

    # Invertir Y para cambiar entre convenciones
    # DirectX y OpenGL cuando sea necesario
    if flip_green:
        normals[:, :, 1] *= -1.0
    
    # Calcular longitud de cada vector
    lengths = np.linalg.norm(
        normals, axis=2, keepdims=True
    )

    # Evitar division por cero
    lengths = np.maximum(lengths, 1e-8)

    # Convertir a vectores unitarios
    normals = normals / lengths

    return normals

# Vectores de referencia del shader de Source
BUMP_BASIS = np.array(
    [
        [ 0.81649661,  0.0,         0.57735026],
        [-0.40824834,  0.70710677,  0.57735026],
        [-0.40824822, -0.70710683,  0.57735026],
    ],
    dtype=np.float32,
)

def normal_to_ssbump(normals: np.ndarray) -> np.ndarray:
    """
    Convierte normales unitarias XYZ en canales RGB SSbump
    Entrada -> (height, width, 3), float32
    Salida -> (height, width, 3), uint8
    """
    if normals.ndim != 3 or normals.shape[2] != 3:
        raise ValueError(
            "Se esperaba un array (height, width, 3)"
        )
    
    # Producto escalar con los tres vectores base
    dots = normals @ BUMP_BASIS.T

    # Limitar resultados al intervalo [0, 1]
    dots = np.clip(dots, 0.0, 1.0)

    # Elevar al cuadrado cada contribución
    weights = np.square(dots)

    # Convertir a imagen RGB de 8 bits
    pixels = np.rint(weights * 255.0).astype(
        np.uint8
    )

    return pixels
