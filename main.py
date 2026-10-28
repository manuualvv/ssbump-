from pathlib import Path
import numpy as np
from PIL import Image

from converter import load_normal_map, normal_to_ssbump

def main():
    print("SSBUMP+ v0.3")
    print("--------------")

    input_path = Path("output/test_normal.png")
    output_path = Path("output/test_ssbump.tga")

    # 1. Leer y normalizar el Normal Map
    normals = load_normal_map(str(input_path))

    print(f"Resolución: {normals.shape[1]}x{normals.shape[0]}")
    print(f"Tipo de normales: {normals.dtype}")
    
    # Verificar que todos los vectores sean unitarios
    lengths = np.linalg.norm(normals, axis=2)

    assert np.allclose(lengths, 1.0, atol=1e-5)

    print("Validación completada correctamente.")
    
    # 2. Transformar normales a canales SSBump
    ssbump_pixels = normal_to_ssbump(normals)

    # 3. Guardar la texturra como TGA RGB
    output_path.parent.mkdir(
        parents=True, exist_ok=True
    )

    image = Image.fromarray(ssbump_pixels)
    image.save(output_path)

    # 4. Inspeccionar el pixel central
    height, width, _ = ssbump_pixels.shape
    center = ssbump_pixels[height // 2, width // 2]

    print(f"SSBump central: {center}")
    print(f"Formato: {ssbump_pixels.dtype}")
    print(f"Archivo generado: {output_path}")

    # 5. Verificar que cada canal esté cerca de 85
    assert np.all(
        np.abs(center.astype(np.int16) - 85 ) <= 2
    )

    print("Conversión completada")

if __name__ == "__main__":
    main()