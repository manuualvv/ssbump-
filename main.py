from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk

from converter import (
    image_to_normals,
    load_height_map,
    load_rgb_image,
    normal_to_ssbump,
    save_ssbump_tga,
)

IMAGE_ERRORS = (OSError, ValueError, MemoryError, Image.DecompressionBombError)

class SSBumpApp:

    def __init__(self, root):
        self.root = root
        self.root.title("SSBUMP+ v0.6")
        self.root.geometry("1080x760")
        self.root.minsize(960, 720)

        self.input_path = None
        self.original_image = None
        self.ssbump_image = None
        self.height_path = None
        self.height_values = None
        self.height_image = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ssbump")
        self._future = None
        self._poll_id = None
        self._closed = False

        self.flip_green = tk.BooleanVar(master=root, value=False)
        self.normalize_weights = tk.BooleanVar(master=root, value=True)
        self.status = tk.StringVar(master=root, value="Seleccioná un Normal Map")
        self.info = tk.StringVar(master=root, value="Ninguna textura cargada")
        self.height_info = tk.StringVar(master=root, value="Height Map: opcional, sin cargar")

        self.build_interface()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
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
            text="Normal Map + Height Map opcional -> SSBump",
        ).pack(anchor="w", pady=(0, 15))

        inputs = ttk.Frame(container)
        inputs.pack(fill="x")
        self.normal_open_button = ttk.Button(
            inputs,
            text="Abrir Normal Map",
            command=self.open_image
        )
        self.normal_open_button.pack(side="left", padx=(0, 8))
        self.height_open_button = ttk.Button(
            inputs, text="Abrir Height Map", command=self.open_height_image
        )
        self.height_open_button.pack(side="left", padx=(0, 8))
        self.height_clear_button = ttk.Button(
            inputs, text="Quitar Height Map", command=self.clear_height_image,
            state="disabled"
        )
        self.height_clear_button.pack(side="left")

        ttk.Label(
            container,
            textvariable=self.info, wraplength=900
        ).pack(anchor="w", pady=(8, 2))
        ttk.Label(container, textvariable=self.height_info, wraplength=900).pack(anchor="w")

        # Control para invertir el canal verde
        self.flip_green_button = ttk.Checkbutton(
            container,
            text="Invertir canal verde (Y)",
            variable=self.flip_green,
            command=self.invalidate_result
        )
        self.flip_green_button.pack(anchor="w", pady=5)

        modes = ttk.Frame(container)
        modes.pack(fill="x")
        self.normalized_button = ttk.Radiobutton(
            modes, text="Pesos normalizados", variable=self.normalize_weights,
            value=True, command=self.invalidate_result
        )
        self.normalized_button.pack(side="left", padx=(0, 20))
        self.raw_button = ttk.Radiobutton(
            modes, text="Pesos sin normalizar", variable=self.normalize_weights,
            value=False, command=self.invalidate_result
        )
        self.raw_button.pack(side="left")
        ttk.Label(
            container,
            text="El Height Map se visualiza y valida. El autosombreado direccional "
                 "todavía no está implementado y no modifica el resultado.",
            wraplength=900,
        ).pack(anchor="w", pady=(8, 0))

        # Zona de vistas previas
        previews = ttk.Frame(container)
        previews.pack(fill="both", expand=True, pady=15)

        normal_panel = ttk.LabelFrame(
            previews,
            text="Normal Map original",
            padding=10
        )
        height_panel = ttk.LabelFrame(
            previews, text="Height Map", padding=10
        )
        result_panel = ttk.LabelFrame(
            previews,
            text="SSBump generado",
            padding=10
        )
        previews.rowconfigure(0, weight=1)
        for column, panel in enumerate((normal_panel, height_panel, result_panel)):
            previews.columnconfigure(column, weight=1, uniform="maps")
            panel.grid(row=0, column=column, sticky="nsew", padx=5)

        self.normal_preview = ttk.Label(
            normal_panel,
            text="Sin imagen",
            anchor="center"
        )
        self.normal_preview.pack(expand=True)

        self.height_preview = ttk.Label(
            height_panel, text="Sin imagen", anchor="center"
        )
        self.height_preview.pack(expand=True)

        self.ssbump_preview = ttk.Label(
            result_panel,
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
            wraplength=900
        ).pack(anchor="w", pady=10)

    def show_preview(self, image, label):
        if image is None:
            label.configure(image="", text="Sin imagen")
            label.image = None
            return
        
        # Crear una copia reducida para la interfaz
        preview = image.copy()
        preview.thumbnail(
            (260, 260),
            Image.Resampling.LANCZOS
        )

        photo = ImageTk.PhotoImage(preview, master=self.root)

        label.configure(image=photo, text="")
        label.image = photo

    def invalidate_result(self):
        # Una entrada o configuración nueva requiere regenerar la salida.
        self.ssbump_image = None
        self.show_preview(None, self.ssbump_preview)
        self.save_button.configure(state="disabled")
        self.compare_button.configure(state="disabled")

        if self.input_path is not None:
            self.status.set("Configuración modificada. Regenerá el SSBump")

    def open_image(self):
        if self._future is not None:
            return
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
            expected = self.height_image.size if self.height_image is not None else None
            original = load_rgb_image(path, expected_size=expected)
            self.show_preview(original, self.normal_preview)
            
            self.input_path = Path(path)
            self.original_image = original

            self.invalidate_result()
            width, height = original.size

            self.info.set(
                f"{self.input_path.name} | "
                f"{width} x {height} | RGB"
            )

            self.generate_button.configure(state="normal")
            self.status.set("Imagen cargada correctamente")
        
        except IMAGE_ERRORS as error:
            messagebox.showerror(
                "Error",
                str(error),
                parent=self.root
            )
    
    def open_height_image(self):
        if self._future is not None:
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Seleccionar Height Map",
            filetypes=[("Imágenes", "*.png *.tga *.bmp *.tif *.tiff"),
                       ("Todos los archivos", "*.*")]
        )
        if not path:
            return
        try:
            expected = self.original_image.size if self.original_image is not None else None
            heights = load_height_map(path, expected_size=expected)
            preview = Image.fromarray(np.rint(heights * 255.0).astype(np.uint8))
            self.show_preview(preview, self.height_preview)
            self.height_path = Path(path)
            self.height_values = heights
            self.height_image = preview
            self.height_info.set(
                f"Height: {self.height_path.name} | {preview.width} x {preview.height}"
            )
            self.invalidate_result()
            self.height_clear_button.configure(state="normal")
            self.status.set("Height Map cargado. El autosombreado sigue pendiente.")
        except IMAGE_ERRORS as error:
            messagebox.showerror("Error de Height Map", str(error), parent=self.root)

    def clear_height_image(self):
        if self._future is not None:
            return
        self.height_path = None
        self.height_values = None
        self.height_image = None
        self.height_info.set("Height Map: opcional, sin cargar")
        self.show_preview(None, self.height_preview)
        self.height_clear_button.configure(state="disabled")
        self.invalidate_result()

    @staticmethod
    def _convert(image, flip_green, normalize_weights, heights):
        # Este método no toca Tkinter; usa las entradas ya cargadas.
        normals = image_to_normals(image, flip_green=flip_green)
        return normal_to_ssbump(normals, normalize_weights, height_map=heights)

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for control in (
            self.normal_open_button, self.height_open_button,
            self.flip_green_button, self.normalized_button, self.raw_button,
        ):
            control.configure(state=state)
        self.height_clear_button.configure(
            state="normal" if not busy and self.height_values is not None else "disabled"
        )
        self.generate_button.configure(
            state="normal" if not busy and self.original_image is not None else "disabled"
        )
        output_state = "normal" if not busy and self.ssbump_image is not None else "disabled"
        self.save_button.configure(state=output_state)
        self.compare_button.configure(state=output_state)

    def generate_ssbump(self):
        if self.original_image is None or self._future is not None:
            return
        self.invalidate_result()
        self.status.set("Procesando textura...")
        self._set_busy(True)
        try:
            self._future = self._executor.submit(
                self._convert, self.original_image, self.flip_green.get(),
                self.normalize_weights.get(), self.height_values
            )
            self._poll_id = self.root.after(50, self._poll_conversion)
        except Exception as error:
            self._future = None
            self._set_busy(False)
            self.status.set("No se pudo iniciar la conversión.")
            messagebox.showerror("Error de conversión", str(error), parent=self.root)

    def _poll_conversion(self):
        self._poll_id = None
        if self._closed or self._future is None:
            return
        if not self._future.done():
            self._poll_id = self.root.after(50, self._poll_conversion)
            return
        future = self._future
        self._future = None
        try:
            self.ssbump_image = Image.fromarray(future.result())
            self.show_preview(self.ssbump_image, self.ssbump_preview)
            mode = "normalizados" if self.normalize_weights.get() else "sin normalizar"
            self.status.set(f"SSBump generado: pesos {mode}. Sin autosombreado.")
        except Exception as error:
            # Límite de la tarea: también informa fallos inesperados del trabajador.
            self.invalidate_result()
            self.status.set("Falló la conversión; no hay una salida para guardar.")
            messagebox.showerror("Error de conversión", str(error), parent=self.root)
        finally:
            self._set_busy(False)

    def on_close(self):
        self._closed = True
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()
    
    def save_image(self):
        if self.ssbump_image is None:
            return
        
        output_dir = Path(__file__).resolve().parent / "output"
        try:
            output_dir.mkdir(exist_ok=True)
        except OSError as error:
            messagebox.showerror("Error de exportación", str(error), parent=self.root)
            return

        mode = "normalized" if self.normalize_weights.get() else "raw"
        filename = self.input_path.stem + f"_ssbump_{mode}.tga"

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
            save_ssbump_tga(
                self.ssbump_image, path,
                protected_paths=(self.input_path, self.height_path)
            )
            self.status.set(f"Archivo guardado: {path}")

            messagebox.showinfo(
                "SSBUMP+",
                "Textura exportada correctamente.",
                parent=self.root
            )

        except IMAGE_ERRORS as error:
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
            reference = load_rgb_image(path, expected_size=self.ssbump_image.size)

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

        except IMAGE_ERRORS as error:
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
