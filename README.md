# SSBUMP+ v0.6

Herramienta experimental en Python/Tkinter que convierte Normal Maps a pesos
SSBump para Source Engine. Carga también un Height Map, permite revisar ambas
entradas y el resultado, y exporta TGA RGB de 24 bits a resolución nativa. Una
máscara de reflejos opcional agrega alfa de 8 bits para obtener TGA RGBA de
32 bits, conservando los RGB.

**Esta revisión de v0.6 incorpora autosombreado direccional experimental.**
Integra 16–300 direcciones del hemisferio sobre los tres canales de SSBump.
La calidad inicial es 64 muestras; 3 conserva exactamente el trazado anterior.
El cálculo está contrastado con rayos individuales independientes y geometrías
conocidas. Falta evaluar la iluminación del material dentro de L4D2. La vista
muestra canales RGB, no una simulación de iluminación. Es una aproximación
propia, no una reproducción exacta del generador de Valve.

## Objetivo y alcance

SSBUMP+ se centra en generar una textura SSBump para Source, especialmente
L4D2, a partir de Normal y Height/Displacement. Su salida termina en el TGA:

- Conservar los tres pesos direccionales RGB calculados a resolución nativa,
  con 8 bits por canal, sin convertirlos nuevamente en una normal XYZ ni
  aplicarles corrección gamma.
- Conservar una máscara de reflejos opcional como alfa independiente, sin
  que sus valores alteren los pesos RGB.
- Entregar TGA RGB de 24 bits o RGBA de 32 bits para convertir manualmente
  con VTFEdit++ y probar el material en L4D2.

La conversión a VTF y sus mipmaps pertenecen a ese paso externo. La exportación
VTF directa queda fuera del alcance y de los avances previstos de SSBUMP+.

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
   primero quitá el Height y la máscara de reflejos, si estaban cargados.
3. Elegí **Pesos normalizados** o **Pesos sin normalizar**. El modo normalizado
   conserva por defecto el cambio de la versión local 0.5.
4. Si corresponde a tu convención de normales, activá **Invertir canal verde
   (Y)**. Para Normal DX en este flujo hacia Source, dejalo desactivado. Sólo
   cambia la normal Y; no invierte ni modifica el Height Map.
5. Para usar el Height activá **Autosombreado direccional (experimental)**.
   Por defecto está apagado y conserva exactamente la conversión anterior.
   No es suficiente con cargar el mapa: hay que activar esta opción.
6. Configurá **Altura**, **Alcance**, **Intensidad**, **Muestras** y bordes
   según la tabla siguiente. Empezá por 32 / 64 / 75% / 64 muestras y compará con
   autosombreado apagado. La altura física del material no se obtiene del PNG.
   Para conservar reflejos de otro material, cargá su máscara gris con
   **Máscara de reflejos**. Debe coincidir en tamaño; no uses Height o AO como
   sustitutos. Blanco permite el cubemap, negro lo bloquea. La máscara sólo
   se escribe en alfa y no altera los cálculos de sombra o los RGB.
7. **Generar SSBump** inicia el cálculo en segundo plano y bloquea temporalmente
   los controles de entrada y configuración para evitar resultados mezclados.
   La barra indica progreso. **Cancelar** interrumpe el cálculo y descarta una
   salida incompleta; después podés ajustar y generar de nuevo.
8. Revisá los tres paneles. Las vistas se reducen como máximo a 200×200; la
   textura cargada y el TGA conservan la resolución original.
9. **Guardar TGA** sugiere `_ssbump_normalized.tga` o `_ssbump_raw.tga`. Si se
   generó con autosombreado, agrega `_shadow_64samples` (según calidad; 3 mantiene
   el sufijo antiguo `_shadow`). Con máscara agrega `_mask`. El diálogo
   pide confirmación para reemplazar una salida existente. Se impide guardar
   encima de cualquiera de las entradas cargadas.
10. **Comparar referencia** exige igual resolución e informa error absoluto
   medio, error máximo y porcentaje de píxeles RGB idénticos. Estas métricas
   miden diferencias de archivos, no calidad visual; excluyen alfa. La vista
   también ignora alfa: en este material representa reflejos, no transparencia.

| Control | Significado | Rango / valor inicial |
|---|---|---|
| Altura | Amplitud entre negro y blanco, medida en texeles horizontales | 0–256 / 32 |
| Alcance | Distancia horizontal máxima para buscar un obstáculo | Entero 1–256 / 64 |
| Intensidad | Atenuación de un canal bloqueado; 100% puede llevarlo a cero | 0–100% / 75% |
| Muestras | Direcciones angulares integradas por texel; 3 = método anterior | 3, 16, 32, 64, 128, 256 o 300 / 64 |
| Repetir Height en bordes | Buscar obstáculos también en las copias vecinas de una textura repetida | Activado |

Un texel es un píxel del mapa. Se supone que los texeles son cuadrados. Si
duplicás la resolución y querés conservar la misma escala relativa del relieve,
duplicá altura y alcance dentro de los límites admitidos. Intensidad controla
oscurecimiento, no suavidad de los bordes de sombra. Sin repetición, el exterior
del mapa se considera abierto, sin obstáculos.

Cambiar una entrada, el modo, Y o cualquier parámetro invalida la salida y deshabilita
guardar/comparar hasta regenerarla. Cancelar un diálogo o cargar un archivo
inválido conserva las entradas válidas y la salida actual. La generación usa
las imágenes cargadas en memoria: un cambio externo del archivo en disco no
modifica silenciosamente la entrada mostrada.

La interfaz exporta TGA RGB de 24 bits o, con máscara, RGBA de 32 bits. El alfa
no contiene displacement. La conversión manual en VTFEdit++ y la evaluación
del material en Hammer++/L4D2 son pasos externos.

### Reflejos y VTFEdit++

Para comparar con `brick_broken_3`, se extrajo con VTFLib++ el alfa de
`brick_broken_normal2.vtf` a `brick_broken_reflection_mask.png`. Sus valores
decodificados van de 0 a 42 sobre 255: copiar sólo el tinte y dejar un alfa
blanco aumentaría mucho los reflejos. Cargá ese PNG como máscara independiente.

Importá el TGA en VTFEdit++ con versión **7.4**, formato con alfa **BGRA8888**
para esta comparación sin pérdida, mipmaps activados y flag **SSBump**.
Desactivá **Normal map**, la renormalización de normales, **sRGB**,
**Correct gamma**, **Dilate** y **Strip alpha channel**. Dilate rellena los RGB
en zonas con alfa cero, lo que no corresponde a una máscara de reflejos; Strip
alpha channel elimina esa máscara. Las opciones se describen en el
[diálogo de importación](https://github.com/ficool2/VTFLib/blob/65ddfa5ab08725ce5a5b7fc88d88c4a748f67fba/VTFEdit/qt/VtfOptionsDialog.cpp#L550-L562).
No generes un normal nuevo desde este TGA. DXT5 puede probarse después, pero
introduce pérdidas y dificulta comparar los cálculos. RGBA8888 también conserva
alfa; BGR888/RGB888 lo descartan. Un TGA puede parecer transparente en un visor
general: comprobá RGB y alfa por separado.

**Comprobá los mipmaps del VTF cuando uses máscara de reflejos.** El filtro
genérico de la VTFLib++ instalada, utilizada por VTFEdit++, pondera RGB por alfa
al redimensionar. Esa operación interpreta alfa como opacidad; con una máscara
de reflejos puede cambiar los pesos RGB de los niveles reducidos. Se observó y
reprodujo este caso; su fundamento está en la llamada con canal alfa 3 de
[CVTFFile::Resize](https://github.com/ficool2/VTFLib/blob/65ddfa5ab08725ce5a5b7fc88d88c4a748f67fba/VTFLib/VTFFile.cpp#L5029-L5038).

Un TGA correcto conserva los RGB y el alfa calculados por SSBUMP+, pero no
garantiza que la conversión externa mantenga la independencia de esos datos en
los mipmaps ni que el material se vea mejor en el juego. Los ajustes anteriores
no resuelven por sí solos esa ponderación por alfa. No se ha verificado una
opción de VTFEdit++ que la desactive en esta instalación; esa parte del flujo
externo queda pendiente de validación. Inspeccioná RGB y alfa por separado,
incluidos los niveles reducidos, y compará el material dentro de L4D2 bajo
condiciones controladas.

El material usa los mismos parámetros del normal de referencia:

```text
"LightmappedGeneric"
{
    "$basetexture" "custom/brick_broken_base"
    "$bumpmap" "custom/brick_broken_bump"
    "$ssbump" "1"
    "$envmap" "env_cubemap"
    "$normalmapalphaenvmapmask" "1"
    "$envmaptint" "[0.15 0.15 0.15]"
    "$surfaceprop" "brick"
}
```

Esto iguala textura de color, cubemap, tinte y máscara. La orientación de las
reflexiones puede diferir: el shader reconstruye una normal aproximada desde
SSBump. El mapa del juego debe tener cubemaps válidos; no se generan desde esta
aplicación. No agregues `$translucent` por el hecho de tener alfa.

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
- Máscara: imagen gris independiente con la misma lectura 8/16 bits o float y
  escala absoluta que Height. No se extrae automáticamente el alfa de un Normal
  RGBA ni se interpreta un ARM. Para usar un alfa existente, primero extraelo
  a un archivo gris. Tampoco se importa VTF directamente en esta aplicación.
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
        -> image_to_normals -> normal_to_weights
        -> visibilidad del Height opcional -> normal_to_ssbump
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
  cálculo local 0.5; `normalize_weights=False` recupera el otro modo. Sólo si
  `self_shadow=True`, el Height interviene en el resultado y pasa a ser obligatorio.
- `main.py`: `SSBumpApp`, diálogos, vistas y estados. NumPy se ejecuta en un
  trabajador. Sólo el hilo principal actualiza Tk mediante `after`. Los
  controles impiden dos conversiones simultáneas. Una cola transporta el progreso
  al hilo de Tk; un `threading.Event` permite cancelar entre franjas de cálculo.
- `save_ssbump_tga`: escribe un temporal junto al destino y reemplaza el archivo
  al terminar. Un fallo de codificación no trunca una salida anterior. Se
  informan errores de carga, permisos, formato y memoria.
- `tests/`: pruebas de cálculos, compatibilidad 0.5, archivos y estados de UI.

### Autosombreado implementado

`ShadowSettings` es una configuración inmutable, validada también en el
conversor: no se confía en que los límites de los campos de Tk sean suficientes.
Se rechazan parámetros no numéricos, NaN/infinito, booleanos como números,
alcances fraccionarios y valores fuera de rango. Los decimales de la interfaz
admiten punto o coma.

`compute_directional_visibility(height_map, settings)` recibe `(H, W)` en
`[0, 1]` y devuelve `float32 (H, W, 3)` en `[0, 1]`: visibilidad angular por canal.
No modifica el Height ni deriva normales nuevas de él. `sample_count=3` devuelve
los 0/1 del trazado anterior de cada dirección central de `BUMP_BASIS`.

Para 16–300 muestras, `_hemisphere_quadrature` construye una rejilla regular de
azimuts y niveles de Z: `z=(nivel+0.5)/niveles`, con azimut en el centro de cada
sector. Es uniforme en ángulo sólido; ninguna muestra toca exactamente el
horizonte o el cénit. Se elige el divisor más cercano a la raíz cuadrada como
número de elevaciones: 64 = 8 azimuts × 8 elevaciones; 300 = 20 × 15.

Cada muestra `d` aporta a cada base `B` el peso `z * max(dot(d,B),0)`. Z pondera
el coseno del plano del Height. La visibilidad final es la suma de pesos de
rayos libres dividida por la suma de todos los pesos **del mismo canal**.
Una superficie no ocluida da exactamente `(1,1,1)` y recupera los RGB base.
El Normal conserva su papel en los pesos originales; la integración de
visibilidad se calcula sobre el hemisferio del plano del Height.

El modo de 3 rayos usa directamente cada `B = (bx, by, bz)` y
`p = sqrt(bx² + by²)`. A distancia horizontal `d`, compara:

```text
posición de muestra = (x + d*bx/p, y + d*by/p)
altura del rayo     = Height[y,x] * altura + d*bz/p + 0.0001
obstáculo          = Height interpolado en la muestra * altura
bloqueado          = obstáculo > altura del rayo
```

X crece a la derecha y Y hacia abajo, coherente con el flujo DX. Se toma una
muestra por texel de distancia horizontal, con interpolación bilineal para las
direcciones oblicuas. La tolerancia de 0,0001 texeles evita autointersecciones
numéricas. El alcance es finito; un obstáculo más lejano no participa.

El modo múltiple calcula el horizonte por azimut: el máximo de
`((Height_muestra - Height_origen)*altura - 0.0001)/distancia`. Una elevación
está bloqueada si su pendiente es menor que ese horizonte. Este máximo permite
resolver todas las elevaciones reutilizando las lecturas de altura. Una tabla
de sumas acumuladas integra las elevaciones visibles, evitando repetir su trazado.
La prueba escalar traza todos los rayos por separado para verificar esta equivalencia.

La memoria temporal se limita a franjas de 128 filas; se conserva un horizonte
por vez. El alcance se limita además por la amplitud del relieve y la pendiente
mínima muestreada. No se redimensionan las entradas para acelerar el cálculo.

La visibilidad se aplica a los pesos float, antes de cuantizar:

```python
visibility = compute_directional_visibility(height_map, settings)
weights *= 1.0 - settings.strength * (1.0 - visibility)
pixels = np.rint(weights * 255.0).astype(np.uint8)
```

**No se normaliza después de aplicar las sombras.** Por ejemplo, una normal
plana tiene RGB `(85,85,85)`. Si un muro bloquea sólo el primer rayo y la
intensidad es 100%, queda `(0,85,85)`, no `(0,128,128)`. Se conserva la pérdida
de contribución del canal bloqueado. Este ejemplo corresponde a 3 rayos; con
múltiples muestras un canal normalmente conserva una visibilidad intermedia,
porque sólo parte de su distribución angular está ocluida.

Uso desde Python:

```python
settings = ShadowSettings(
    height_scale=32, max_distance=64, strength=0.75, wrap_edges=True, sample_count=64,
)
pixels = normal_to_ssbump(
    normals, normalize_weights=True, height_map=heights,
    self_shadow=True, shadow_settings=settings,
)
```

Con autosombreado apagado, intensidad cero o altura cero se conservan exactamente
los píxeles anteriores. Activarlo sin Height o con dimensiones distintas produce
`ValueError`. Cancelar produce `concurrent.futures.CancelledError`; la interfaz
lo trata como cancelación normal, sin guardar ni mostrar una salida parcial.

Referencia del fundamento de multiplicar oclusión por canal:
[Chris Green / Valve, Efficient Self-Shadowed Radiosity Normal Mapping (2007)](https://cdn.akamai.steamstatic.com/apps/valve/2007/SIGGRAPH2007_EfficientSelfShadowedRadiosityNormalMapping.pdf).
La integración angular sigue este fundamento, con una cuadratura y optimización
propias. Elegir 300 muestras no la convierte en el generador exacto de Valve.
No incluye su filtrado bilateral ni un modelo geométrico de varias capas.

### Alfa de reflejos

`load_reflection_mask` y `load_height_map` comparten la lectura escalar y sus
validaciones. En `normal_to_ssbump(..., reflection_mask=mask)`, la máscara debe
ser `(H,W)`, real, finita y `[0,1]`, con el tamaño del normal. Tras calcular los
RGB, se agrega `round(mask*255)` como cuarto canal, sin mezclarlo con los pesos.
Sin máscara se conserva la salida RGB anterior. `save_ssbump_tga` acepta ambos
modos y protege también la ruta de la máscara.

El uso del alfa como máscara de cubemap está en
[LightmappedGeneric de Valve](https://github.com/ValveSoftware/source-sdk-2013/blob/master/src/materialsystem/stdshaders/lightmappedgeneric_ps2_3_x.h).
Al usar bump, el shader de referencia descarta una máscara `$envmapmask` externa;
por eso se conserva el alfa en la propia textura y se activa
`$normalmapalphaenvmapmask`. No se usa el Height como alfa del resultado.

### Cómo podría agregarse AO después

AO es una atenuación escalar por píxel y no representa altura ni dirección.
Una ampliación posterior podría agregar su propia carga/vista, exigir igual
resolución y valores finitos `[0, 1]`, y ofrecer una intensidad independiente.
Después de la sombra direccional y antes de convertir a 8 bits:

```python
# Propuesta futura: este código NO está conectado al conversor actual.
ao_factor = (1.0 - ao_strength) + ao_strength * ao
weights *= ao_factor[..., None]
```

Blanco no cambia los pesos; negro atenúa por igual los tres canales. No se debe
renormalizar después. Habría que probar AO blanco, negro, intensidad cero,
dimensiones inválidas y evitar oscurecer dos veces si el albedo o el SSBump ya
incorporan oclusión. Un ARM debe separar su canal AO; no debe convertirse entero
a gris ni usarse como Height. **Esta revisión no incorpora carga ni cálculo de AO.**

## Pruebas

Desde `C:\ssbump-generator`:

```powershell
.\venv\Scripts\python.exe -u -m unittest discover -v
.\venv\Scripts\python.exe -m py_compile main.py converter.py tests\test_converter.py tests\test_app.py tests\test_shadows.py tests\test_sampling.py
git diff --check
```

Las pruebas crean imágenes en temporales y los limpian. Incluyen una pareja
**real de 2048×2048**, ambos modos y exportación/reapertura del TGA a resolución
nativa. Cubren fórmulas analíticas, inversión Y, compatibilidad local 0.5,
normales inválidas, alturas de 8/16 bits y float, archivos ausentes/corruptos,
resoluciones incompatibles, cabeceras demasiado grandes y guardado seguro.

La prueba `test_tga_bytes_preserve_channels_alpha_and_orientation` inspecciona
la cabecera y decodifica los bytes del TGA sin usar Pillow: verifica 24/32 bits,
orden de canales y orientación. Comprueba RGB intacto incluso con alfa cero y
valores pequeños de máscara, además de reabrir el archivo con Pillow.

`test_shadows.py` contrasta el trazado vectorizado con una referencia escalar
independiente, y comprueba superficies planas, paredes a derecha/izquierda y
arriba/abajo, pozos, repetición de bordes, escala, alcance, intensidad y ausencia
de normalización posterior. Incluye otro par PNG real de 2048×2048 con un muro,
autosombreado en ambos modos y exportación/reapertura del TGA. También prueba
progreso y cancelación antes y durante el cálculo.

Las pruebas de interfaz crean Tk sin mostrar ventanas y sustituyen los
diálogos. Cubren ambos órdenes de carga, cancelación, invalidación de salida,
cambios de modo/Y, conversión en segundo plano, errores, comparación y guardado.
Incluyen controles de sombra, rechazo de parámetros inválidos, una conversión
real con sombra, nombres de exportación y descarte de resultados al cancelar.
`test_sampling.py` contrasta horizontes con rayos individuales para 16, 64 y 300
muestras, bordes abiertos/repetidos, sombras rasantes omitidas por 3 rayos,
visibilidad intermedia, convención DX, progreso y cancelación. Prueba alfa de
valores pequeños, validación de máscara y exportación RGBA sin alterar RGB.
El caso real 2048×2048 recorre ambos modos con 64 muestras y máscara RGBA.
Si no hay Tk/display se omiten esos casos y se informa `skipped`; los cálculos
siguen probándose.

Verificación manual:

1. Cargar una pareja 2048×2048, generar y guardar: deben verse tres imágenes y
   el TGA debe medir 2048×2048.
2. Cambiar modo o Y: debe desaparecer la salida hasta regenerar.
3. Cargar un Height de otro tamaño o un archivo corrupto: mensaje de error y
   conservación de entradas/salida válidas.
4. Con autosombreado apagado, generar con y sin Height: los RGB deben coincidir.
   Después activarlo con un Height que tenga relieve: deben atenuarse canales
   donde se detecten obstáculos. Altura cero e intensidad cero deben recuperar
   exactamente la salida base. Un Height plano no debe producir sombras.
5. Comparar una exportación contra sí misma: errores 0 y 100% de coincidencia.
   Una referencia de otra resolución debe rechazarse.
6. Guardar sobre una entrada TGA: se debe rechazar sin modificarla.
7. Evaluar el material por separado en L4D2; la vista RGB y la comparación de
   archivos no validan su iluminación dentro del juego.
8. Probar cancelar y volver a generar, editar un parámetro para invalidar la
   salida, y activar autosombreado sin Height para comprobar el mensaje de error.
9. Comparar 3 / 64 / 300 muestras con los mismos parámetros. Más muestras
   mejora la cobertura angular; no implica oscurecer siempre más cada píxel.
10. Cargar una máscara con grises bajos, generar y guardar: los RGB deben
    verse normalmente en la aplicación y el TGA debe conservar esa máscara en
    alfa. Quitar/cambiar máscara invalida el resultado. Un tamaño distinto debe
    dar error sin perder las entradas válidas.

## Limitaciones y mejoras pendientes

El trazado está implementado y validado numéricamente; falta evaluación visual
en L4D2. Es una integración angular discreta sobre un Height, con alcance finito.
No modela penumbra, geometría con salientes/cuevas, múltiples capas ni obstáculos
menores que el paso de muestreo. Una altura excesiva puede producir sombras
exageradas. La escala no está calibrada automáticamente con la del Normal Map.

El muestreo conserva el paso horizontal de un texel: no garantiza detectar
obstáculos más finos. La rejilla puede producir sesgo angular visible a baja
calidad. No simula el tamaño de una fuente de luz ni la penumbra geométrica.
La normal reconstruida de SSBump puede modificar las reflexiones aun con la
misma máscara/tinte. Las entradas Normal/Height deben corresponder y su escala
no se calibra automáticamente. AO externo sigue pendiente.

Opcional: más azimuts o muestreo adaptativo, filtrado del Height con control de
detalle, visor 3D/zoom y AO independiente.
Carga, guardado y comparación siguen siendo síncronos; la generación es la
operación enviada al trabajador. Más alcance y resolución requieren más tiempo;
la cancelación se comprueba entre franjas y no espera a terminar toda la textura.
