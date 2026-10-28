from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image

from converter import load_normal_map, normal_to_ssbump

def main():
    print("SSBUMP+ v0.4")
    print("--------------")

    # Craer instancia de Tkinter
    root = tk.Tk()

    # Ocultar la ventana principal
    root.withdraw()

    try:
        # 1. Seleccionar un Normal Map
        input_path = filedialog.askopenfilename(
            parent=root,
            title="Seleccionar Normal Map",
            filetypes=[
                (
                    "Imágenes compatibles",
                    "*.png *.tga *.bmp *.tif *.tiff"
                ),
                ("Todos los archivos", "*.*")
            ]
        )

        # Comprobar si el usuario canceló
        if not input_path:
            print("Selección cancelada")
            return
        
        print(f"Imagen seleccionada: {input_path}")


        # 2. Leer y normalizar el Normal Map
        normals = load_normal_map(input_path)

        height, width, _ = normals.shape
        
        print(f"Resolución: {width}x{height}")

        # 3. Convertir a SSBump
        print("Procesando SSBump...")
        
        ssbump_pixels = normal_to_ssbump(normals)

        # 4. Preparar la carpeta de salida
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        # 5. Elegir dónde se guarda el archivo
        filename = Path(input_path).stem + "_ssbump.tga"

        output_path = filedialog.asksaveasfilename(
            parent=root,
            title="Guardar textura SSBump",
            initialdir=str(output_dir.resolve()),
            initialfile=filename,
            defaultextension=".tga",
            filetypes=[
                ("Textura TGA", "*.tga")
            ]
        )

        if not output_path:
            print("Guardado cancelado")

        # 6. Crear y exportar la imagen
        image = Image.fromarray(ssbump_pixels)
        image.save(output_path, format="TGA")

        print(f"Archivo generado: {output_path}")
        print("Conversión completada")

        messagebox.showinfo(
            "SSBump Generator",
            "Textura generada correctamente",
            parent=root
        )
    
    except (OSError, ValueError) as error:
        print(f"Error: {error}")

        messagebox.showerror(
            "Error de conversión",
            str(error),
            parent=root
        )
    
    finally:
        root.destroy()


if __name__ == "__main__":
    main()