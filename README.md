# SSBUMP+ v0.6

Herramienta experimental en Python/Tkinter que convierte Normal Maps a pesos
SSBump para Source Engine. Carga también un Height Map, permite revisar ambas
entradas y el resultado, y exporta TGA RGB de 8 bits a resolución nativa.

**El autosombreado direccional todavía no está implementado.** En v0.6 el Height
Map se carga, conserva y valida, pero no altera la salida. No se calculan rayos,
oclusión ambiental ni sombras. La vista del resultado muestra sus canales RGB,
no una simulación de iluminación de L4D2.

## Instalación y ejecución

Validado con Python 3.14.2, Tk 8.6, NumPy 2.5.4 y Pillow 13.0.0. Se mantienen las
versiones de `requirements.txt`; no se agregan dependencias.

En PowerShell:

```powershell
Set-Location C:\ssbump-generator
# Sólo si todavía no existe el entorno:
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

Si usás otro entorno, reemplazá `.\venv\Scripts\python.exe` por su ejecutable.
Tkinter debe estar incluido en Python; se comprueba con
`.\venv\Scripts\python.exe -m tkinter`. No hay migraciones, base de datos,
servidor, variables de entorno obligatorias ni acceso a la red durante el uso.

## Uso

1. **Abrir Normal Map** carga la textura y muestra su nombre y resolución.
2. **Abrir Height Map** es opcional y también puede usarse primero. Ambos mapas
   deben tener exactamente el mismo ancho y alto. No se escalan, recortan ni
   rotan automáticamente. Para cambiar a una pareja de otra resolución,
   primero elegí **Quitar Height Map**.
3. Elegí **Pesos normalizados** o **Pesos sin normalizar**. El modo normalizado
   conserva por defecto el cambio de la versión local 0.5.
4. Si corresponde a tu convención de normales, activá **Invertir canal verde
   (Y)**. Sólo cambia Y antes de calcular los pesos.
5. **Generar SSBump** inicia el cálculo en segundo plano y bloquea temporalmente
   los controles de entrada y configuración para evitar resultados mezclados.
6. Revisá los tres paneles. Las vistas se reducen como máximo a 260×260; la
   textura cargada y el TGA conservan la resolución original.
7. **Guardar TGA** sugiere `_ssbump_normalized.tga` o `_ssbump_raw.tga`. El diálogo
   pide confirmación para reemplazar una salida existente. Se impide guardar
   encima de cualquiera de las dos entradas cargadas.
8. **Comparar referencia** exige igual resolución e informa error absoluto
   medio, error máximo y porcentaje de píxeles RGB idénticos. Estas métricas
   miden diferencias de archivos, no calidad visual.

Cambiar una entrada, el modo o Y invalida la salida anterior y deshabilita
guardar/comparar hasta regenerarla. Cancelar un diálogo o cargar un archivo
inválido conserva las entradas válidas y la salida actual. La generación usa
las imágenes cargadas en memoria: un cambio externo del archivo en disco no
modifica silenciosamente la entrada mostrada.

La conversión a VTF, la configuración del material y su evaluación en
Hammer++/L4D2 siguen siendo pasos externos. La exportación no incluye alfa.

## Entradas, validaciones y límites

- Formatos ofrecidos: PNG, TGA, BMP y TIFF. Pillow decodifica el contenido real;
  cambiar la extensión no convierte un archivo inválido en imagen.
- Normal: RGB `[0, 255]` pasa a XYZ `[-1, 1]` y se lleva a longitud 1. RGBA
  descarta alfa; otros modos se convierten a RGB. No se aplica corrección gamma,
  inversión Z ni reconstrucción del azul. El mapa debe codificar normales.
- Height: grises de 8 bits se dividen por 255; un canal de 16 bits (`I;16` o
  enteros `I` en rango 0–65535) por 65535. TIFF float (`F`) debe estar en `[0, 1]`.
  RGB/RGBA se convierte a luminancia de 8 bits, descartando alfa. Se conserva
  precisión de 16 bits en memoria; sólo la vista se reduce a 8 bits. No se
  estira el contraste de cada imagen. Negro es 0 y blanco 1.
- Se admiten 2048×2048, 2048×3072, 4096×4096 y tamaños menores o rectangulares.
  No se exige mínimo de 2048 ni potencia de dos en esta herramienta.
- Límite: **16.777.216 píxeles por imagen**, definido en
  `converter.MAX_TEXTURE_PIXELS`. Se comprueba la cabecera antes de convertir
  los píxeles. Reduce el riesgo de agotar RAM, pero no garantiza memoria
  suficiente en toda máquina. Se mantienen las protecciones de Pillow contra
  imágenes descomprimidas excesivamente grandes.
- Las normales de la API deben ser arrays reales y finitos `(H, W, 3)`,
  unitarios con tolerancia absoluta 0,001. Alturas: `(H, W)`, reales y finitas
  en `[0, 1]`. Se rechazan formas vacías, resoluciones distintas, NaN e infinito.

## Cálculo y estructura

```text
Tkinter -> cargar/validar imágenes -> tres vistas
        -> seleccionar modo/Y -> trabajador de conversión
        -> image_to_normals -> normal_to_weights -> normal_to_ssbump
        -> recoger resultado en el hilo de Tk -> vista -> exportar TGA
```

Para cada normal unitaria y cada dirección de `BUMP_BASIS`:

```python
dots = np.clip(normals @ BUMP_BASIS.T, 0.0, 1.0)
weights = np.square(dots)
if normalize_weights:
    total = weights.sum(axis=2, keepdims=True)
    weights /= np.maximum(total, 1e-8)
pixels = np.rint(weights * 255.0).astype(np.uint8)
```

Los canales son contribuciones direccionales, no coordenadas XYZ. El modo sin
normalizar conserva los pesos cuadrados recortados. El normalizado divide por
su suma; antes de cuantizar, la suma es 1 cuando supera el epsilon. Si los tres
pesos son cero, la salida queda negra y no se divide por cero. El redondeo a
8 bits puede hacer que la suma RGB difiera ligeramente de 255.

Para `n=(1, 0, 0)`, el modo sin normalizar da `(170, 0, 0)` y el normalizado
`(255, 0, 0)`. Para `n=(0, 0, 1)`, ambos dan `(85, 85, 85)`. La diferencia de
intensidad no demuestra mayor calidad ni presencia de sombras.

- `converter.py`: cálculo e I/O sin Tk. `normal_to_ssbump(normals)` mantiene el
  cálculo local 0.5; `normalize_weights=False` recupera el otro modo. El
  argumento opcional `height_map` valida alturas y tamaño, sin alterar pesos.
- `main.py`: `SSBumpApp`, diálogos, vistas y estados. NumPy se ejecuta en un
  trabajador. Sólo el hilo principal actualiza Tk mediante `after`. Los
  controles impiden dos conversiones simultáneas desde la interfaz.
- `save_ssbump_tga`: escribe un temporal junto al destino y reemplaza el archivo
  al terminar. Un fallo de codificación no trunca una salida anterior. Se
  informan errores de carga, permisos, formato y memoria.
- `tests/`: pruebas de cálculos, compatibilidad 0.5, archivos y estados de UI.

### Extensión futura de autosombreado

`compute_directional_visibility(height_map)` define la entrada `(H, W)` en
`[0, 1]` y el futuro resultado `(H, W, 3)`: visibilidad `[0, 1]` por dirección de
`BUMP_BASIS`. **Actualmente valida y lanza `NotImplementedError`.** No se conecta
al cálculo ni a un botón que prometa sombras.

Antes de implementarla faltan escala física respecto del texel, orientación,
borde/repetición, alcance y muestreo de rayos. Se deben validar superficies
planas, paredes y huecos con resultados esperados y dentro del motor. No se
deberían renormalizar ciegamente los pesos después de aplicar visibilidad:
podría perderse el oscurecimiento calculado.

Referencia técnica de orientación frente a oclusión direccional:
[Chris Green / Valve, Efficient Self-Shadowed Radiosity Normal Mapping (2007)](https://cdn.akamai.steamstatic.com/apps/valve/2007/SIGGRAPH2007_EfficientSelfShadowedRadiosityNormalMapping.pdf).
Su algoritmo de trazado de rayos no está implementado aquí.

## Pruebas

Desde `C:\ssbump-generator`:

```powershell
.\venv\Scripts\python.exe -u -m unittest discover -v
.\venv\Scripts\python.exe -m py_compile main.py converter.py tests\test_converter.py tests\test_app.py
git diff --check
```

Las pruebas crean imágenes en temporales y los limpian. Incluyen una pareja
**real de 2048×2048**, ambos modos y exportación/reapertura del TGA a resolución
nativa. Cubren fórmulas analíticas, inversión Y, compatibilidad local 0.5,
normales inválidas, alturas de 8/16 bits y float, archivos ausentes/corruptos,
resoluciones incompatibles, cabeceras demasiado grandes y guardado seguro.

Las pruebas de interfaz crean Tk sin mostrar ventanas y sustituyen los
diálogos. Cubren ambos órdenes de carga, cancelación, invalidación de salida,
cambios de modo/Y, conversión en segundo plano, errores, comparación y guardado.
Si no hay Tk/display se omiten esos casos y se informa `skipped`; los cálculos
siguen probándose.

Verificación manual:

1. Cargar una pareja 2048×2048, generar y guardar: deben verse tres imágenes y
   el TGA debe medir 2048×2048.
2. Cambiar modo o Y: debe desaparecer la salida hasta regenerar.
3. Cargar un Height de otro tamaño o un archivo corrupto: mensaje de error y
   conservación de entradas/salida válidas.
4. Generar con y sin Height, sin cambiar normal/modo/Y: los RGB deben coincidir
   exactamente, porque el autosombreado está pendiente.
5. Comparar una exportación contra sí misma: errores 0 y 100% de coincidencia.
   Una referencia de otra resolución debe rechazarse.
6. Guardar sobre una entrada TGA: se debe rechazar sin modificarla.
7. Evaluar el material por separado en L4D2; la vista RGB y la comparación de
   archivos no validan su iluminación dentro del juego.

## Limitaciones y mejoras pendientes

Necesario para sombras reales: implementar y validar el algoritmo direccional;
no es parte de v0.6. No se ha comprobado esta versión dentro de L4D2.

Opcional: visor 3D/zoom, parámetros de escala/bordes cuando exista el algoritmo,
procesamiento por bloques para resoluciones mayores y exportación VTF directa.
Carga, guardado y comparación siguen siendo síncronos; la generación es la
operación enviada al trabajador.
