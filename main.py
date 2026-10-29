from pathlib import Path
from concurrent.futures import CancelledError, ThreadPoolExecutor
from queue import Empty, SimpleQueue
from threading import Event
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk

from converter import (
    MAX_HEIGHT_SCALE,
    MAX_SHADOW_DISTANCE,
    SHADOW_SAMPLE_COUNTS,
    ShadowSettings,
    image_to_normals,
    load_height_map,
    load_reflection_mask,
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
        self.mask_path = None
        self.mask_values = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ssbump")
        self._future = None
        self._poll_id = None
        self._closed = False
        self._cancel_event = None
        self._progress_queue = SimpleQueue()
        self._job_self_shadow = False
        self._job_normalized = True
        self._job_sample_count = None
        self._result_shadowed = False
        self._result_sample_count = None

        self.flip_green = tk.BooleanVar(master=root, value=False)
        self.normalize_weights = tk.BooleanVar(master=root, value=True)
        self.self_shadow = tk.BooleanVar(master=root, value=False)
        self.height_scale = tk.StringVar(master=root, value="32")
        self.shadow_distance = tk.StringVar(master=root, value="64")
        self.shadow_strength = tk.StringVar(master=root, value="75")
        self.shadow_samples = tk.StringVar(master=root, value="64")
        self.wrap_edges = tk.BooleanVar(master=root, value=True)
        self.progress = tk.DoubleVar(master=root, value=0.0)
        self.status = tk.StringVar(master=root, value="Seleccioná un Normal Map")
        self.info = tk.StringVar(master=root, value="Ninguna textura cargada")
        self.height_info = tk.StringVar(master=root, value="Height Map: opcional, sin cargar")
        self.mask_info = tk.StringVar(master=root, value="Máscara de reflejos: opcional, sin cargar")

        self.build_interface()
        for variable in (
            self.height_scale, self.shadow_distance, self.shadow_strength, self.shadow_samples,
        ):
            variable.trace_add("write", self._on_shadow_setting_changed)
        self._update_shadow_controls()
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
        self.mask_open_button = ttk.Button(
            inputs, text="Máscara de reflejos", command=self.open_reflection_mask,
        )
        self.mask_open_button.pack(side="left", padx=(16, 8))
        self.mask_clear_button = ttk.Button(
            inputs, text="Quitar máscara", command=self.clear_reflection_mask, state="disabled",
        )
        self.mask_clear_button.pack(side="left")

        ttk.Label(
            container,
            textvariable=self.info, wraplength=900
        ).pack(anchor="w", pady=(8, 2))
        ttk.Label(container, textvariable=self.height_info, wraplength=900).pack(anchor="w")
        ttk.Label(container, textvariable=self.mask_info, wraplength=900).pack(anchor="w")

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

        shadow_options = ttk.Frame(container)
        shadow_options.pack(fill="x", pady=(6, 2))
        self.shadow_button = ttk.Checkbutton(
            shadow_options, text="Autosombreado direccional (experimental)",
            variable=self.self_shadow, command=self.shadow_option_changed,
        )
        self.shadow_button.pack(side="left", padx=(0, 15))
        self.wrap_button = ttk.Checkbutton(
            shadow_options, text="Repetir Height en bordes", variable=self.wrap_edges,
            command=self.invalidate_result,
        )
        self.wrap_button.pack(side="left")

        shadow_fields = ttk.Frame(container)
        shadow_fields.pack(fill="x")
        self.shadow_fields = []
        for label, variable, minimum, maximum, increment in (
            ("Altura (texeles)", self.height_scale, 0, MAX_HEIGHT_SCALE, 4),
            ("Alcance (texeles)", self.shadow_distance, 1, MAX_SHADOW_DISTANCE, 8),
            ("Intensidad (%)", self.shadow_strength, 0, 100, 5),
        ):
            ttk.Label(shadow_fields, text=label).pack(side="left", padx=(0, 5))
            field = ttk.Spinbox(
                shadow_fields, from_=minimum, to=maximum, increment=increment,
                textvariable=variable, width=7,
            )
            field.pack(side="left", padx=(0, 16))
            self.shadow_fields.append(field)
        ttk.Label(shadow_fields, text="Muestras").pack(side="left", padx=(0, 5))
        self.samples_field = ttk.Combobox(
            shadow_fields, textvariable=self.shadow_samples, width=5,
            values=SHADOW_SAMPLE_COUNTS, state="readonly",
        )
        self.samples_field.pack(side="left")
        self.shadow_fields.append(self.samples_field)
        ttk.Label(
            container,
            text="El autosombreado requiere un Height Map. La altura controla el relieve; "
                 "3 muestras conserva el método anterior; 64 es la calidad inicial.",
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

        self.cancel_button = ttk.Button(
            actions, text="Cancelar", command=self.cancel_generation, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=5)

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

        ttk.Progressbar(
            container, variable=self.progress, maximum=100
        ).pack(fill="x", pady=(0, 3))

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
        # Alfa controla reflejos en Source, no transparencia en esta vista.
        preview = image.convert("RGB")
        preview.thumbnail(
            (200, 200),
            Image.Resampling.LANCZOS
        )

        photo = ImageTk.PhotoImage(preview, master=self.root)

        label.configure(image=photo, text="")
        label.image = photo

    def invalidate_result(self):
        # Una entrada o configuración nueva requiere regenerar la salida.
        self.ssbump_image = None
        self._result_shadowed = False
        self._result_sample_count = None
        self.progress.set(0.0)
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
            expected = self._other_input_size("normal")
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
            expected = self._other_input_size("height")
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
            self.status.set("Height Map cargado. Podés generar con autosombreado activado o desactivado.")
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

    def _other_input_size(self, replacing):
        """Exige coincidencia entre entradas, permitiendo reemplazar la única cargada."""
        sizes = (
            ("normal", self.original_image.size if self.original_image is not None else None),
            ("height", self.height_image.size if self.height_image is not None else None),
            ("mask", self.mask_values.shape[::-1] if self.mask_values is not None else None),
        )
        return next((size for name, size in sizes if name != replacing and size is not None), None)

    def open_reflection_mask(self):
        if self._future is not None:
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Seleccionar máscara de reflejos en gris",
            filetypes=[("Imágenes", "*.png *.tga *.bmp *.tif *.tiff"),
                       ("Todos los archivos", "*.*")],
        )
        if not path:
            return
        try:
            mask = load_reflection_mask(path, expected_size=self._other_input_size("mask"))
            self.mask_path = Path(path)
            self.mask_values = mask
            self.mask_info.set(
                f"Reflejos: {self.mask_path.name} | {mask.shape[1]} x {mask.shape[0]} | alfa de salida"
            )
            self.invalidate_result()
            self.mask_clear_button.configure(state="normal")
            self.status.set("Máscara cargada: se exportará en alfa, sin modificar los RGB.")
        except IMAGE_ERRORS as error:
            messagebox.showerror("Error de máscara de reflejos", str(error), parent=self.root)

    def clear_reflection_mask(self):
        if self._future is not None:
            return
        self.mask_path = None
        self.mask_values = None
        self.mask_info.set("Máscara de reflejos: opcional, sin cargar")
        self.mask_clear_button.configure(state="disabled")
        self.invalidate_result()

    @staticmethod
    def _convert(
        image, flip_green, normalize_weights, heights, self_shadow=False,
        settings=None, cancel_event=None, progress_callback=None,
        reflection_mask=None,
    ):
        # Este método no toca Tkinter; usa las entradas ya cargadas.
        normals = image_to_normals(image, flip_green=flip_green)
        return normal_to_ssbump(
            normals, normalize_weights, height_map=heights, self_shadow=self_shadow,
            shadow_settings=settings, cancel_event=cancel_event,
            progress_callback=progress_callback,
            reflection_mask=reflection_mask,
        )

    def _set_shadow_controls_enabled(self, enabled):
        for control in (*self.shadow_fields, self.wrap_button):
            state = "readonly" if control is self.samples_field else "normal"
            control.configure(state=state if enabled else "disabled")

    def _update_shadow_controls(self):
        self._set_shadow_controls_enabled(self.self_shadow.get() and self._future is None)

    def shadow_option_changed(self):
        self.invalidate_result()
        self._update_shadow_controls()

    def _on_shadow_setting_changed(self, *_):
        if not self._closed and self._future is None:
            self.invalidate_result()

    def _read_shadow_settings(self):
        try:
            height_scale = float(self.height_scale.get().replace(",", "."))
            distance = int(self.shadow_distance.get())
            strength = float(self.shadow_strength.get().replace(",", ".")) / 100
            samples = int(self.shadow_samples.get())
        except ValueError as error:
            raise ValueError(
                "Revisá los parámetros: altura e intensidad deben ser números; "
                "el alcance y las muestras deben ser enteros."
            ) from error
        return ShadowSettings(
            height_scale=height_scale, max_distance=distance, strength=strength,
            wrap_edges=self.wrap_edges.get(), sample_count=samples,
        )

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for control in (
            self.normal_open_button, self.height_open_button,
            self.mask_open_button,
            self.flip_green_button, self.normalized_button, self.raw_button,
            self.shadow_button,
        ):
            control.configure(state=state)
        self._set_shadow_controls_enabled(self.self_shadow.get() and not busy)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.height_clear_button.configure(
            state="normal" if not busy and self.height_values is not None else "disabled"
        )
        self.mask_clear_button.configure(
            state="normal" if not busy and self.mask_values is not None else "disabled"
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
        try:
            enabled = self.self_shadow.get()
            settings = self._read_shadow_settings() if enabled else None
            if enabled and self.height_values is None:
                raise ValueError("Cargá un Height Map para activar el autosombreado.")
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Configuración inválida", str(error), parent=self.root)
            return
        self.invalidate_result()
        self._job_self_shadow = enabled
        self._job_normalized = self.normalize_weights.get()
        self._job_sample_count = settings.sample_count if settings is not None else None
        self._cancel_event = Event()
        self._progress_queue = SimpleQueue()
        self.status.set("Procesando textura...")
        self._set_busy(True)
        try:
            self._future = self._executor.submit(
                self._convert, self.original_image, self.flip_green.get(),
                self._job_normalized, self.height_values, enabled, settings,
                self._cancel_event, self._progress_queue.put,
                self.mask_values,
            )
            self._poll_id = self.root.after(50, self._poll_conversion)
        except Exception as error:
            self._future = None
            self._set_busy(False)
            self.status.set("No se pudo iniciar la conversión.")
            messagebox.showerror("Error de conversión", str(error), parent=self.root)

    def cancel_generation(self):
        if self._future is None:
            return
        self._cancel_event.set()
        self._future.cancel()
        self.cancel_button.configure(state="disabled")
        self.status.set("Cancelando conversión...")

    def _poll_conversion(self):
        self._poll_id = None
        if self._closed or self._future is None:
            return
        try:
            while True:
                fraction = self._progress_queue.get_nowait()
                self.progress.set(fraction * 100)
                if self._job_self_shadow and not self._cancel_event.is_set():
                    self.status.set(f"Calculando autosombreado... {fraction:.0%}")
        except Empty:
            pass
        if not self._future.done():
            self._poll_id = self.root.after(50, self._poll_conversion)
            return
        future = self._future
        self._future = None
        try:
            pixels = future.result()
            if self._cancel_event.is_set():
                raise CancelledError()
            self.ssbump_image = Image.fromarray(pixels)
            self._result_shadowed = self._job_self_shadow
            self._result_sample_count = self._job_sample_count
            self.show_preview(self.ssbump_image, self.ssbump_preview)
            mode = "normalizados" if self._job_normalized else "sin normalizar"
            shadow = (
                f"Autosombreado experimental: {self._job_sample_count} muestras"
                if self._result_shadowed else "Sin autosombreado"
            )
            mask = " Máscara de reflejos incluida en alfa." if self.ssbump_image.mode == "RGBA" else ""
            self.progress.set(100.0)
            self.status.set(f"SSBump generado: pesos {mode}. {shadow}.{mask}")
        except CancelledError:
            self.invalidate_result()
            self.status.set("Conversión cancelada. Podés ajustar y volver a generar.")
        except Exception as error:
            # Límite de la tarea: también informa fallos inesperados del trabajador.
            self.invalidate_result()
            self.status.set("Falló la conversión; no hay una salida para guardar.")
            messagebox.showerror("Error de conversión", str(error), parent=self.root)
        finally:
            self._set_busy(False)

    def on_close(self):
        if self._closed:
            return
        self._closed = True
        if self._cancel_event is not None:
            self._cancel_event.set()
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
        if self._result_shadowed:
            mode += "_shadow"
            if self._result_sample_count != 3:
                mode += f"_{self._result_sample_count}samples"
        if self.ssbump_image.mode == "RGBA":
            mode += "_mask"
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
                protected_paths=(self.input_path, self.height_path, self.mask_path)
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
                self.ssbump_image.convert("RGB"), dtype=np.int16
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
                "Valores calculados sobre RGB de 0 a 255; alfa no incluido.",
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
