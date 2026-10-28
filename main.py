from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk

from converter import load_normal_map, normal_to_ssbump

class SSBumpApp:

    def __init__(self, root):
        self.root = root
        self.root.title("SSBUMP+ v0.5")
        self.root.geometry("900x620")
        self.root.minsize(750, 550)

        self.input_path = None
        self.original_image = None
        self.ssbump_image = None

        self.flip_green = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Seleccioná un Normal Map")
        self.info = tk.StringVar(value="Ninguna textura cargada")

        self.build_interface()
    
    def build_interface(self):
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="SSBUMP+",
            font=("Segoe UI", 22, "bold")
        ).pack(anchor="w")

        ttk.Label(
            container,
            text="Normal Map -> Source Engine SSBump",
        ).pack(anchor="w", pady=(0, 15))

        # Botón para abrir imágenes
        ttk.Button(
            container,
            text="Abrir Normal Map",
            command=self.open_image
        ).pack(anchor="w")

        ttk.Label(
            container,
            textvariable=self.info
        ).pack(anchor="w", pady=10)

        # Control para invertir el canal verde
        ttk.Checkbutton(
            container,
            text="Invertir canal verde (Y)",
            variable=self.flip_green,
            command=self.invalidate_result
        ).pack(anchor="w", pady=5)

        # Zona de vistas previas
        previews = ttk.Frame(container)
        previews.pack(fill="both", expand=True, pady=15)

        left = ttk.LabelFrame(
            previews,
            text="Normal Map original",
            padding=10
        )
        left.pack(side="left", fill="both", expand=True, padx=5)

        right = ttk.LabelFrame(
            previews,
            text="SSBump generado",
            padding=10
        )
        right.pack(side="left", fill="both", expand=True, padx=5)

        self.normal_preview = ttk.Label(
            left,
            text="Sin imagen",
            anchor="center"
        )
        self.normal_preview.pack(expand=True)

        self.ssbump_preview = ttk.Label(
            right,
            text="Sin imagen",
            anchor="center"
        )
        self.ssbump_preview.pack(expand=True)

        # Botones de procesamiento
        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=10)

        self.generate_button = ttk.Button(
            actions,
            text="Generar SSBump",
            command=self.generate_ssbump,
            state="disabled"
        )
        self.generate_button.pack(side="left", padx=5)

        self.save_button = ttk.Button(
            actions,
            text="Guardar TGA",
            command=self.save_image,
            state="disabled"
        )
        self.save_button.pack(side="left", padx=5)

        self.compare_button = ttk.Button(
            actions,
            text="Comparar referencia",
            command=self.compare_reference,
            state="disabled"
        )
        self.compare_button.pack(side="left", padx=5)

        ttk.Label(
            container,
            textvariable=self.status,
            wraplength=800
        ).pack(anchor="w", pady=10)

    def show_preview(self, image, label):
        if image is None:
            label.configure(image="", text="Sin imagen")
            label.image = None
            return
        
        # Crear una copia reducida para la interfaz
        preview = image.copy()
        preview.thumbnail(
            (350, 350),
            Image.Resampling.LANCZOS
        )

        photo = ImageTk.PhotoImage(preview)

        label.configure(image=photo, text="")
        label.image = photo

    def invalidate_result(self):
        # Si cambia la orientación Y, invalidar el SSBump
        self.ssbump_image = None
        self.show_preview(None, self.ssbump_preview)
        self.save_button.configure(state="disabled")
        self.compare_button.configure(state="disabled")

        if self.input_path is not None:
            self.status.set("Configuración modificada. Regenerá el SSBump")

    def open_image(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Seleccionar Normal Map",
            filetypes=[
                (
                    "Imágenes",
                    "*.png *.tga *.bmp *.tif *.tiff"
                ),
                ("Todos los archivos", "*.*")
            ]
        )

        if not path:
            return
        
        try:
            with Image.open(path) as image:
                original = image.convert("RGB")
            
            self.input_path = Path(path)
            self.original_image = original

            self.invalidate_result()
            self.show_preview(
                self.original_image,
                self.normal_preview
            )

            width, height = original.size

            self.info.set(
                f"{self.input_path.name} | "
                f"{width} x {height} | RGB"
            )

            self.generate_button.configure(state="normal")
            self.status.set("Imagen cargada correctamente")
        
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Error",
                str(error),
                parent=self.root
            )
    
    def generate_ssbump(self):
        if self.input_path is None:
            return
        
        try:
            self.status.set("Procesando textura...")
            self.root.update_idletasks()

            normals = load_normal_map(
                str(self.input_path),
                flip_green=self.flip_green.get()
            )

            pixels = normal_to_ssbump(normals)

            self.ssbump_image = Image.fromarray(pixels)

            self.show_preview(
                self.ssbump_image,
                self.ssbump_preview
            )

            self.save_button.configure(state="normal")
            self.compare_button.configure(state="normal")

            self.status.set(
                "SSBump generado correctamente"
            )
        
        except (OSError, ValueError, MemoryError) as error:
            self.invalidate_result()

            messagebox.showerrror(
                "Error de conversión",
                str(error),
                parent=self.root
            )
    
    def save_image(self):
        if self.ssbump_image is None:
            return
        
        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(exist_ok=True)

        filename = self.input_path.stem + "_ssbump.tga"

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Guardar SSBump",
            initialdir=str(output_dir),
            initialfile=filename,
            defaultextension=".tga",
            filetypes=[("TGA", "*.tga")]
        )

        if not path:
            return

        try:
            self.ssbump_image.save(path, format="TGA")
            self.status.set(f"Archivo guardado: {path}")

            messagebox.showinfo(
                "SSBUMP+",
                "Textura exportada correctamente.",
                parent=self.root
            )

        except OSError as error:
            messagebox.showerror(
                "Error de exportación",
                str(error),
                parent=self.root
            )

    def compare_reference(self):
        if self.ssbump_image is None:
            return

        path = filedialog.askopenfilename(
            parent=self.root,
            title="Seleccionar SSBump de referencia",
            filetypes=[
                ("Imágenes", "*.tga *.png *.bmp *.tif *.tiff")
            ]
        )

        if not path:
            return

        try:
            with Image.open(path) as image:
                reference = image.convert("RGB")

            if reference.size != self.ssbump_image.size:
                raise ValueError(
                    "La referencia debe tener la misma resolución."
                )

            generated = np.asarray(
                self.ssbump_image, dtype=np.int16
            )
            reference_pixels = np.asarray(
                reference, dtype=np.int16
            )

            difference = np.abs(
                generated - reference_pixels
            )

            mae = float(difference.mean())
            max_error = int(difference.max())

            exact_pixels = np.all(
                difference == 0, axis=2
            )
            exact_percent = float(
                exact_pixels.mean() * 100
            )

            messagebox.showinfo(
                "Comparación de referencia",
                f"Error absoluto medio: {mae:.3f}\n"
                f"Error máximo: {max_error}\n"
                f"Píxeles idénticos: {exact_percent:.2f}%\n\n"
                "Valores calculados sobre RGB de 0 a 255.",
                parent=self.root
            )

        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Error de comparación",
                str(error),
                parent=self.root
            )

def main():
    root = tk.Tk()
    SSBumpApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()