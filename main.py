import numpy as np

from converter import load_normal_map

def main():
    print("SSBUMP+ v0.2")
    print("--------------")

    path = "output/test_normal.png"

    normals = load_normal_map(path)

    print(f"Dimensiones: {normals.shape}")
    print(f"Tipo de datos: {normals.dtype}")

    # Inspeccionar el píxel central
    height, width, _ = normals.shape
    center = normals[height // 2, width // 2]

    print(f"Normal central: {center}")
    print(f"Longitud: {np.linalg.norm(center):.6f}")

    # Verificar que todos los vectores sean unitarios
    lengths = np.linalg.norm(normals, axis=2)

    assert np.allclose(lengths, 1.0, atol=1e-5)

    print("Validación completada correctamente.")

if __name__ == "__main__":
    main()