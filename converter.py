from pathlib import Path
import numpy as np
from PIL import Image

def load_normal_map(path: str, flip_green: bool = False) -> np.ndarray:
    """
    Carga un Normal Map y devuelve un array
    de vectores normales unitarios

    Shape: (height, width, 3)
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