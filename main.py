from pathlib import Path
import numpy as np
from PIL import Image

def main():
    print("SSBUMP+ v0.0.1")
    print("--------------")

    width = 2048
    height = 2048

    # Crear textura RGB de prueba
    pixels = np.zeros((height, width, 3), dtype=np.uint8)

    pixels[:, :, 0] = 128
    pixels[:, :, 1] = 128
    pixels[:, :, 2] = 255

    image = Image.fromarray(pixels, mode="RGB")

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    outputh_path = output_dir / "test_normal.png"
    image.save(outputh_path)

    print(f"Resolución: {width}x{height}")
    print(f"Archivo generado: {outputh_path}")
    print("Prueba finalizada correctamente.")

if __name__ == "__main__":
    main()