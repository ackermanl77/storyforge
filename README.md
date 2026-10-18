# StoryForge Local

App de escritorio para escribir historias de ficcion largas (hasta 10
capitulos de hasta 10,000 palabras cada uno) a partir de un plot, personajes
y un setting que tu escribes. Genera el texto en ingles usando un modelo de
IA que corre **localmente en tu PC**, sin depender de internet ni de una API
externa una vez que tienes el modelo descargado.

Para una guia paso a paso de como usar cada pestana y cada funcion, ver
[GUIA_DE_USUARIO.md](GUIA_DE_USUARIO.md). Este README cubre instalacion,
rendimiento y limitaciones; para documentacion tecnica ver la seccion
correspondiente mas abajo.

## Que incluye

- Interfaz grafica (pestanas: Modelo, Plot, Personajes, Setting, Lorebook, **Esquema**, Capitulos).
- **Flujo "outline-first"**: en la pestana Esquema puedes generar de un jalon
  un beat sheet de todos los capitulos (titulo + eventos clave de cada uno) a
  partir del plot/personajes/setting, editarlo, y luego generar la prosa de
  cada capitulo en la pestana Capitulos siguiendo ese esquema. Esto mejora
  mucho la coherencia de una historia larga frente a improvisar capitulo por
  capitulo.
- **Tipo de escritura**: en la pestana Esquema puedes elegir un enfasis para
  toda la historia (Narrativa, Descriptiva, Creativa, Dialogo, Poetica,
  Accion rapida, o ninguno) que se le pide al modelo respetar tanto al
  generar el esquema como la prosa de cada capitulo, encima de las
  convenciones de formato de siempre.
- **Proposito de capitulo**: cada capitulo (no toda la historia) puede
  marcarse como Apertura, Escena climatica, Final, o Epilogo, para que el
  modelo sepa que rol narrativo cumple ese capitulo especifico.
- **Refinar un capitulo ya generado**: en vez de regenerarlo desde cero,
  puedes pedirle al modelo que lo reescriba segun una instruccion puntual
  ("hazlo mas oscuro", "acorta el dialogo del final").
- **Versiones anteriores por capitulo**: generar, continuar, refinar,
  reescribir una seleccion, reemplazar, reducir repeticion o restaurar
  guarda la version previa (hasta 20 por capitulo, con origen y fecha),
  recuperable desde un boton en cada capitulo.
- **Lorebook** (entradas que solo entran al prompt cuando se mencionan),
  **Nota del autor**, reescritura de una seleccion con clic derecho,
  **buscar y reemplazar** (en el capitulo y en todo el proyecto), modo
  enfoque, barra de estado con tokens/s, ETA, uso de contexto y "Detener".
- **Formato de chat** del modelo (plantilla del GGUF o Llama 3/ChatML/
  Mistral/Alpaca) y muestreo por tarea con semilla.
- **Expandir con IA / Importar desde archivo**: en Plot, Personajes y
  Setting, puedes pedirle al modelo que desarrolle una nota corta en un
  texto mas completo, o importar el contenido directo desde un archivo
  `.txt`.
- Limites de palabras validados: plot ≤ 50,000, personajes ≤ 10,000,
  setting ≤ 10,000, hasta 10 capitulos de hasta 10,000 palabras cada uno.
- Generacion de capitulos por secciones (para poder llegar a objetivos
  largos sin exceder lo que un modelo local puede escribir de un jalon).
- Convenciones de formato automaticas en el texto generado: narracion en
  tercera persona por defecto, pensamientos internos en *cursiva* y primera
  persona, dialogo con comillas.
- Reductor de repeticion de palabras (basado en WordNet, funciona offline
  una vez descargados sus datos).
- Guardar/abrir proyecto (.storyforge.json) y exportar la historia a Word
  (.docx, con portada y un capítulo por página), EPUB, Markdown o texto plano.
- **Prompt propio por capítulo**: cada capítulo puede generarse con un prompt
  escrito por ti entero (con marcadores como `{plot}` o `{anterior}`) en vez
  del prompt automático. Ver la guía de usuario.
- **StoryForge en el celular**: `StoryForge.exe --servidor` (o el acceso
  directo "StoryForge Local en el celular") sirve una página web en tu red
  local para escribir desde el navegador del celular mientras el modelo corre
  en la PC; se conecta escaneando un QR. Ver la guía de usuario.

## Historial de cambios

**Modelo en un servidor (2026-10-18):**
- Pestaña Modelo → "O usa un modelo en un servidor": escribe la dirección de LM Studio, Ollama,
  KoboldCpp, llama-server o el servidor de llama-cpp-python (en esta PC o en otra de la red) y pulsa
  Conectar. Sirve para usar un modelo más grande que el que cabe en tu GPU, en otra máquina. Todo lo
  demás (capítulos, continuar, reescribir, evitar clichés) funciona igual; lo único que no se puede
  en un servidor es forzar el largo mínimo de cada sección.

**Evitar clichés (2026-10-17):**
- Mientras se escribe un capítulo (y al Refinar o Reescribir), las frases hechas de una lista
  ("her heart skipped a beat", "nada volvería a ser igual"...) se cortan al aparecer y el modelo
  sigue de otra forma. Pestaña Plot: "Evitar clichés" y "Frases a evitar…" (las tuyas, "*" = 1 a 3
  palabras). Con el modelo 8B: de 4 clichés por capítulo a ninguno. Además se cortan los párrafos
  en que el modelo se sale de la historia para hablarte ("Please let me know…", "Note from the author").

**Generador de historias (2026-10-14):**
- Una página aparte, **/generador**, para escribir una historia de una vez sin proyecto ni
  capítulos: trama, personajes, ambientación, género, tema, punto de vista, tono y contexto
  adicional; propósito (historia completa, comienzo, capítulo, escena climática, final, epílogo),
  formato (prosa, guion de cine, obra de teatro, poesía), largo (~300 a ~6.000 palabras) y
  equilibrio de diálogo. La historia se escribe en inglés con el mismo motor de los capítulos
  (secciones, Detener, limpieza de texto filtrado) y se ve mientras se escribe.
- Resultados / Historial / Guardados: Copiar, ☆ Guardar, Descargar .txt, Regenerar y "Usar estos
  ajustes". Presets: cuatro ejemplos y los tuyos (Guardar preset / Borrar). Todo queda en
  `generador.json` de la carpeta de datos del usuario.
- Se abre con `StoryForge.exe --generador` o el acceso directo **"StoryForge - Generador de
  historias"** del instalador. Idea tomada del formulario de un generador de historias en línea
  (diseño propio).

**Ajustes de la historia y presets (2026-10-13):**
- En la pestaña Plot: **género, tema, tono, punto de vista** (texto libre con sugerencias) y el
  **equilibrio narración/diálogo**, que van al prompt de cada capítulo y del esquema como un bloque
  STORY SETTINGS (las sugerencias se traducen a instrucciones precisas en inglés). Sin ajustes, el
  prompt queda igual que antes.
- **Presets** que guardan esos ajustes y el tipo de escritura: siete incorporados (Thriller,
  Romance, Terror, Fantasía épica, Misterio policial, Ciencia ficción, Cuento infantil) y los
  tuyos (Guardar como… / Borrar), también elegibles desde el celular.
- Nuevos marcadores para el prompt propio: `{género}`, `{tema}`, `{tono}`, `{punto_de_vista}`.

**Reintentar la última sección y errores en español (2026-10-11):**
- **"Últ. sección"** junto a Reintentar: vuelve a escribir solo la última sección de la última
  ejecución (el motor recuerda dónde empezó, `engine.last_section_start`) y la suma como
  alternativa; lo anterior no se toca.
- **Errores en español**: los mensajes de Python, del sistema y de llama.cpp que llegaban en inglés
  ("No such file or directory", "Expecting value", "Failed to load model", "CUDA error: out of
  memory"...) se explican en español (`app/error_text.py`), con el texto original como detalle
  técnico cuando viene de llama.cpp. Los registros conservan el original.

**Capítulos más largos y limitaciones cerradas (2026-10-07/08):**
- **Los capítulos llegan cerca de su objetivo.** Con Llama 3 8B un capítulo de 3000 palabras salía
  con ~550: la primera sección recibía todo el esquema y escribía un final, y al continuar el modelo
  cerraba su respuesta enseguida. Ahora cada sección escribe solo su parte del esquema, el modelo no
  puede terminar una sección intermedia demasiado pronto y una respuesta vacía se reintenta. Con el
  mismo modelo: 3000 → 2612 palabras, 2000 → 1950.
- **"Versiones guardadas por capítulo"** (pestaña Plot), las **alternativas de Reintentar se guardan**
  con el proyecto, y los mensajes de error del motor salen de `app/strings_es.py`.
- **Firma de código** del `.exe`, el instalador y el desinstalador con `CODESIGN_THUMBPRINT`, y
  los instaladores publicados con cada release.

**Ronda B12/F9/K3/K4/T5 y CI (2026-10-02/03, versión 0.4.0):**
- **Reutilización del prefijo del prompt**: lo estable de la historia va
  primero y lo que cambia en cada sección (lorebook, largo restante, pistas,
  Nota del autor) al final, así llama.cpp reutiliza su caché KV entre
  secciones.
- **Orden de Tab explícito** (Tab / Shift+Tab) en cada panel y diálogo.
- **Ícono de la app** (exe, ventana e instalador) e **instalador por
  usuario** de Inno Setup (`installer/StoryForge.iss`, lo compila
  `build.bat` si encuentra Inno Setup 6).
- **Cobertura** de pruebas en CI, `build.bat` y `scripts/run_coverage.ps1`.
- La interfaz se dividió en módulos `app/ui_*.py` y todos sus textos están
  en `app/strings_es.py`.
- "Reducir repetición" ahora sí sustituye sinónimos (no encontraba WordNet
  cuando NLTK lo deja comprimido en `wordnet.zip`).
- CI más robusto en los runners de Windows (reintento del arranque de
  Tcl/Tk, límite de tiempo por prueba y por job).

**Ronda P2 del informe de mejoras (versión 0.4.0):**
- **Muestreo por tarea y semilla**: la prosa usa presets (Creativo /
  Equilibrado / Preciso / Personalizado, pestaña Modelo) y los resúmenes y el
  esquema usan temperaturas más bajas. Semilla vacía = aleatoria (se muestra
  la usada y "Usar la última" la fija para repetir un resultado).
- **Detener cualquier tarea**: barra de estado abajo con operación, tiempo,
  tokens/s, ETA, uso de contexto, "Ver prompt" (el texto exacto enviado) y
  "Detener" (también Esc). Detener un refinado o un resumen no cambia nada.
- **Modelos**: los modelos partidos en varios archivos aparecen una sola vez
  y los incompletos se marcan y no se cargan; se muestra arquitectura,
  contexto entrenado y cuantización; "Estimar VRAM" sugiere capas en GPU;
  opciones avanzadas (flash attention, lote, caché KV q8_0/q4_0); la app
  recuerda las opciones de cada modelo en esta PC y al abrir un proyecto
  preselecciona su modelo (o avisa si ya no está).
- **Vista previa con diferencias** antes de aplicar un refinado, "Aceptar y
  seguir refinando", **Reintentar** con alternativas (< >), versiones
  anteriores con origen y fecha (hasta 20).
- **Nota del autor** (de la historia y de cada capítulo) y **clic derecho
  sobre una selección**: Reescribir / Expandir / Describir / Acortar.
- **Buscar y reemplazar** (Ctrl+F en el capítulo, Ctrl+Shift+F en todo el
  proyecto), total de palabras y avance por capítulo, **modo enfoque** (F11).
- **Lorebook**: entradas activas/siempre incluidas/prioridad, escaneo de lo
  último escrito y de las entradas mencionadas por otras, y el motivo de
  cada coincidencia.
- **Proyecto**: título y autor, formato versionado, carga tolerante a
  archivos dañados con oferta de abrir la copia `.bak`, `*` y nombre de
  archivo en el título, solo pregunta si hay cambios sin guardar, y
  autoguardado cada minuto también fuera de las generaciones.
- **Interfaz en español correcto** (acentos, tuteo) y Preferencias (tema
  claro/oscuro/sistema, escala, fuente e interlineado del editor, carpeta
  de modelos fuera de OneDrive). Ayuda > Acerca de muestra la versión.
- **Build reproducible**: `build.bat` usa un entorno limpio `.build-venv`
  con versiones exactas; el .exe lleva versión; CI genera
  `StoryForge-<versión>-cpu.zip` / `-cuda13.zip` y publica un Release al
  subir un tag `v<versión>`.

**Mejoras prioritarias (P1) del informe de mejoras:**
- **Continuidad entre capítulos**: el contexto de capítulos anteriores ahora
  se arma del más reciente hacia atrás e incluye siempre el resumen y las
  últimas líneas del capítulo anterior (antes, desde el capítulo ~4, el
  capítulo inmediatamente anterior quedaba fuera).
- **Resúmenes visibles, editables y con aviso de desactualizado**
  ("Mostrar resumen", "Regenerar resumen"); al generar se ofrece regenerar
  los desactualizados; los capítulos largos se resumen por partes; un fallo
  al resumir se registra y se avisa.
- **Formato de chat** (pestaña Modelo): los prompts se envían con la
  plantilla del modelo (la del GGUF, o Llama 3/ChatML/Mistral/Alpaca
  deducida o elegida), con "Sin plantilla" para modelos base. Al continuar,
  la respuesta del modelo arranca pre-llenada con el final del capítulo.
- **Continuar / Continuar desde el cursor**, y un contexto de continuación
  que usa todo lo que quepa del capítulo, no solo las últimas 400 palabras.
- Las secciones cortadas por largo ya no parten oraciones en dos párrafos;
  un cierre natural cerca del objetivo termina el capítulo.
- **Esquema**: se entienden `**Chapter 1: ...**`, `### Chapter 1 - ...`,
  números en palabras y romanos; una respuesta sin formato da un error en
  vez de meterse entera en el capítulo 1; un esquema incompleto se avisa.
- **Editor**: deshacer/rehacer (Ctrl+Z/Ctrl+Y), atajos (Ctrl+N/O/S,
  Ctrl+Shift+S, Ctrl+Enter, Esc), un capítulo a la vez a pantalla completa,
  y el capítulo que se está generando queda en solo lectura.
- **Errores inesperados** (en callbacks de la interfaz o en hilos) se
  registran y se muestran; menú Ayuda > "Abrir carpeta de registros".
- **Pruebas**: ya no borran el autoguardado real (usan
  `STORYFORGE_USER_DATA_DIR` apuntando a una carpeta temporal).
- **CI**: dependencias fijadas (`requirements-build.txt`,
  `requirements-cuda.txt`) y dos builds, `cpu` y `cuda13`, desde los wheels
  precompilados de llama-cpp-python (antes CI compilaba una versión solo-CPU
  sin fijar versión).

**Correcciones de una revision de codigo:**
- **El esquema ya no se corta despues del capitulo 1**: generar esquema (y
  refinar/expandir con IA) usaba la misma secuencia de corte que la prosa
  (`"\n\nChapter"`), que el formato del esquema dispara justo al empezar
  "Chapter 2:".
- **Refinar ya no pierde el final de capitulos largos**: antes el capitulo
  se recortaba para caber en el contexto y la version "revisada" de ese
  recorte reemplazaba el capitulo entero. Ahora nunca se recorta: si no
  cabe, se refina por partes (grupos de parrafos) y se vuelve a unir.
- **`build.bat` ya no borra `StoryForge-App\models\`** (tus `.gguf`) en cada
  build, y se detiene con un error si falla pip, PyInstaller o la copia.
- **`.exe` empaquetado**: `models\` y `nltk_data\` se buscan junto a
  `StoryForge.exe` (antes se buscaban dentro de `_internal\`); el
  autoguardado va a `%APPDATA%\StoryForge\autosave\` y los errores a
  `%APPDATA%\StoryForge\storyforge.log`. Un autoguardado que falla ahora
  avisa (una vez por sesion) en vez de fallar en silencio.
- **CUDA 12**: se detectan tambien las DLLs de los paquetes `nvidia-*-cu12`
  (`nvidia\<pkg>\bin\*.dll`, no solo el layout anidado de cu13). Si
  `llama.dll` o sus DLLs no cargan, el mensaje ahora explica que hacer.
- **Agregar/eliminar un capitulo o restaurar una version** ya no descarta lo
  que habias escrito sin sincronizar.
- **Guardado atomico** (archivo temporal + reemplazo, con copia `.bak` de la
  version anterior) y los errores al guardar ahora se muestran.
- **Un capitulo con apenas mas de 10,000 palabras ya no bloquea toda la
  generacion**: es una advertencia, y la ultima seccion se ajusta para no
  pasarse del limite.
- El empaquetado ya no incluye cuBLAS dos veces (~550 MB menos) ni las
  import libraries `.lib` de llama_cpp.

**Nuevas funcionalidades — inspiradas en un generador de historias de la competencia (toolsaday.com), a pedido del usuario:**
- **Proposito de capitulo**: selector "Proposito" (Apertura/Escena climatica/
  Final/Epilogo) en cada capitulo, independiente del "Tipo de escritura"
  (que es de toda la historia).
- **Refinar capitulo**: reescribe un capitulo ya generado segun una
  instruccion puntual, sin tener que regenerarlo entero. Si el capitulo no
  cabe completo en el contexto del modelo, se refina por partes (ver
  arriba); subir `n_ctx` en la pestaña Modelo permite refinarlo de una vez.
- **Versiones anteriores**: regenerar, refinar, o reducir repeticion ya no
  son irreversibles — se guarda la version previa (hasta 5 por capitulo) y
  se puede recuperar desde un boton nuevo en cada capitulo.
- **Expandir con IA / Importar desde archivo**: en Plot, Personajes y
  Setting, dos botones nuevos junto al contador de palabras.

**Corrección importante — los errores dejaban de mostrarse silenciosamente:**
- Si algo fallaba al generar un capítulo, generar el esquema, o cargar un
  modelo (un `.gguf` corrupto, el contexto lleno, el modelo no cargado,
  etc.), la app debía mostrar un cuadro de error explicando qué pasó — pero
  por un detalle de cómo Python maneja las variables de `except ... as exc`,
  ese mensaje nunca llegaba a aparecer: fallaba silenciosamente con un error
  interno no relacionado, sin avisos, sin diálogo. En el `.exe` empaquetado
  esto era invisible por completo (no hay consola). Encontrado corriendo
  `pyflakes` sobre el código, no probando la app manualmente. Corregido en
  los tres lugares donde pasaba; se agregaron pruebas automatizadas
  (`tests/test_gui.py`) que reproducen la falla exacta y confirman que ya no
  ocurre.

**Nueva funcionalidad — configuracion avanzada del modelo desde la interfaz:**
- La pestaña **"Modelo"** ahora tiene campos para **n_ctx**, **n_gpu_layers**
  y **n_threads** — antes había que editar `app/engine.py` a mano para
  cambiar cualquiera de estos (ver sección "Rendimiento / GPU" arriba). Se
  validan antes de cargar, y el mensaje de confirmación muestra con qué
  valores quedó cargado el modelo.

**Nueva funcionalidad — tipo de escritura:**
- En la pestaña **"Esquema"**, un selector de "Tipo de escritura" (Narrativa,
  Descriptiva, Creativa, Diálogo, Poética, Acción rápida, o ninguno) aplica a
  toda la historia. Se agrega como una línea de énfasis adicional al prompt
  del esquema y al de cada capítulo, sin reemplazar las reglas de formato
  existentes (cursivas para pensamientos, comillas para diálogo, etc.). Se
  guarda con el proyecto; un proyecto guardado antes de esta funcionalidad
  simplemente carga sin ningún énfasis seleccionado.

**Nueva funcionalidad — flujo "outline-first" (esquema antes de la prosa):**
- Pestaña **"Esquema"**: genera un beat sheet completo de todos los
  capítulos (título + 2-4 eventos clave por capítulo) a partir de tu plot,
  personajes y setting, con un solo botón. Puedes editarlo antes de generar
  la prosa.
- Al generar un capítulo en la pestaña "Capítulos", si ese capítulo tiene un
  esquema asignado, el modelo lo recibe como guía obligatoria de los eventos
  a cubrir (`app/prompts.py`, `THIS CHAPTER'S OUTLINE`), además de una lista
  compacta con los títulos de todos los capítulos planeados, para que tenga
  conciencia del arco completo de la historia.
- Bug corregido de paso: generar un capítulo o el esquema ahora sincroniza
  primero **todos** los campos (plot, personajes, setting, esquema) desde la
  interfaz; antes esos campos solo se actualizaban al guardar/exportar, así
  que generar sin haber guardado antes podía usar datos vacíos o viejos.

**Correcciones aplicadas (versión anterior):**
- Se agregó un botón **"Cancelar"** funcional junto a "Generar" en cada
  capítulo (antes el motor soportaba cancelar, pero no había forma de
  activarlo desde la interfaz).
- Al terminar de generar un capítulo, la app ahora le pide al modelo un
  **resumen** de ese capítulo y lo usa como contexto para el siguiente
  (antes ese resumen nunca se generaba y se usaba en su lugar un recorte
  crudo del texto, que podía cortar a media escena).
- Se agregó **control de desbordamiento de contexto**: antes de cada
  llamada al modelo se cuentan los tokens reales del prompt (usando el
  tokenizador del propio modelo) y, si no cabe en su ventana de contexto,
  la app reduce automáticamente cuánto plot/personajes/setting/resumen
  incluye y reintenta, en vez de fallar de forma críptica o generar texto
  cortado a la mitad.
- De paso, se corrigió un bug relacionado: al continuar un capítulo largo,
  el recorte de "lo ya escrito" tomaba el **inicio** del capítulo en vez del
  **final**, lo que podía hacer que el modelo perdiera el hilo de la escena
  actual al seguir escribiendo.

## Limitaciones reales que debes conocer

Esto no es Claude ni ChatGPT: es un modelo de IA de codigo abierto,
razonablemente bueno pero mucho mas limitado, corriendo en tu propia
computadora.

1. **Calidad de escritura**: modelos locales de 7-8 mil millones de
   parametros (lo que corre bien en una PC normal) escriben peor, con menos
   coherencia en historias largas, que un modelo de la nube.
2. **Memoria de contexto**: el modelo no puede "leer" tus 50,000 palabras de
   plot completas en cada capitulo. La app las recorta/resume
   automaticamente para que quepan; entre mas largo sea tu plot, mas se
   pierde el detalle fino.
3. **Velocidad**: generar 10,000 palabras en una CPU normal puede tardar
   varios minutos por capitulo (mas rapido si tu PC tiene GPU compatible,
   ver seccion de rendimiento).
4. **Filtros del propio modelo**: algunos modelos de instrucciones tienen su
   propio entrenamiento de seguridad y pueden negarse a escribir ciertas
   escenas pase lo que le pidas en el prompt; eso depende del modelo que
   elijas, no de esta app.

## Instalacion (en tu PC con Windows)

Si tienes un zip de release (`StoryForge-<versión>-cpu.zip` o
`-cuda13.zip`, generados por CI) o el instalador
(`StoryForge-<versión>-<variante>-setup.exe`, instalación por usuario en
`%LOCALAPPDATA%\Programs\StoryForge`, sin permisos de administrador), no
necesitas Python: descomprime o instala, copia tu modelo `.gguf` a la
carpeta `models\` junto a `StoryForge.exe` (o configura otra carpeta en
Archivo > Preferencias) y ejecuta `StoryForge.exe`. Para compilarlo tú:

1. Instala Python 3.10 o mas nuevo (marca "Add python.exe to PATH" en el
   instalador de python.org); `build.bat` usa 3.14 por defecto.
2. Descarga/copia esta carpeta completa a tu PC.
3. Descarga un modelo `.gguf` (ver `models/README.txt` para recomendaciones)
   y colocalo dentro de la carpeta `models/`.
4. Genera el ejecutable corriendo `build.bat` (doble clic, o desde una
   terminal `cmd`; `build.bat cpu` para la versión sin GPU). Usa Python
   3.14 vía el `py` launcher (`py -3.14`; otra versión con
   `set STORYFORGE_PYVER=3.12`). Crea un entorno limpio `.build-venv` con versiones
   exactas (`requirements-build.txt` + el wheel precompilado de
   llama-cpp-python), descarga los datos de NLTK, corre las pruebas con
   cobertura, usa PyInstaller para producir el build, compila el instalador
   en `dist\installer\` si encuentra Inno Setup 6 (si no, avisa y sigue), y
   copia el programa a `StoryForge-App\StoryForge.exe` —
   una carpeta fija y facil de ubicar (a diferencia de `dist\`, que es la
   carpeta de trabajo de PyInstaller y se borra/regenera en cada build).
   Para firmar (Authenticode) el .exe, el instalador y su desinstalador:
   `set CODESIGN_THUMBPRINT=<huella SHA-1>` (un certificado de firma de
   codigo del almacen de Windows) antes de `build.bat`; usa signtool del
   Windows SDK y sella con `CODESIGN_TIMESTAMP_URL` (por defecto DigiCert).
5. Copia la carpeta `models/` (con tu modelo adentro) junto al .exe, dentro
   de `StoryForge-App\`, si no quedo ahi automaticamente, y ejecuta
   `StoryForge-App\StoryForge.exe`. `build.bat` conserva
   `StoryForge-App\models\` entre builds (reemplaza todo lo demas).

El .exe tiene que compilarse en Windows (no hay compilacion cruzada desde
otro sistema). El paso 4 es una sola linea de comando y tarda unos minutos
(crea el entorno, instala, prueba y empaqueta).

### Uso sin compilar un .exe (para probar mas rapido)

Si solo quieres probarlo sin empaquetarlo:

```
pip install -r requirements.txt
python storyforge.py
```

## Rendimiento / GPU (opcional)

Opciones en la pestaña Modelo: con GPU, deja n_gpu_layers en -1 si el
modelo cabe (usa "Estimar VRAM"), activa flash attention, usa un lote
(n_batch) de 1024-2048 y, para contextos largos, la caché KV q8_0 (la mitad
de memoria; requiere flash attention). n_ctx = 0 usa el contexto con el que
se entrenó el modelo. Ver `models/README.txt` para qué modelos caben en
16 GB de VRAM. Consejo: guarda los .gguf fuera de OneDrive y configura esa
carpeta en Archivo > Preferencias.

Por defecto, `llama-cpp-python` corre en CPU. Si tu PC tiene una GPU NVIDIA
(probado con series RTX 40 y 50), puedes instalar una version compilada con
soporte CUDA para acelerar mucho la generacion:

1. **Instala la version de `llama-cpp-python` con CUDA**, desde el indice de
   wheels precompilados del propio autor (no hace falta compilar nada a
   mano, ni tener el CUDA Toolkit completo instalado):

   ```powershell
   pip install --index-url https://abetlen.github.io/llama-cpp-python/whl/cu130 llama-cpp-python --force-reinstall --no-deps
   ```

   Cambia `cu130` por el indice que corresponda a tu driver de NVIDIA si
   `cu130` no esta disponible (por ejemplo `cu124`/`cu126`/`cu128`) -- revisa
   `https://abetlen.github.io/llama-cpp-python/whl/` para ver los indices
   publicados.

2. **Instala las DLLs del runtime de CUDA** (el wheel de arriba las necesita
   para cargar, pero no las incluye -- son ~450 MB, principalmente
   `cublas`):

   ```powershell
   pip install nvidia-cuda-runtime nvidia-cublas
   ```

   `app/engine.py` detecta automaticamente estos paquetes (si estan
   instalados) y agrega su carpeta de DLLs al `PATH` antes de importar
   `llama_cpp` -- no hace falta configurar variables de entorno a mano. Si
   no los instalas, todo sigue funcionando en CPU-only como antes.

No hace falta editar codigo para el resto: en la pestaña **"Modelo"**, junto
al selector de archivo, hay tres campos de configuracion avanzada:

- **Contexto (n_ctx)**: tamaño de la ventana de contexto del modelo (al
  elegir un modelo se propone su contexto de entrenamiento, como mucho
  16,384; sin esa informacion, 8192; `0` usa el de entrenamiento). Mas grande permite incluir mas plot/personajes/setting/
  capitulos previos por llamada, pero usa mas RAM y puede ser mas lento.
- **Capas en GPU (n_gpu_layers)**: si la app detecta una version de
  `llama-cpp-python` con soporte de GPU real (paso 1 de arriba), este campo
  se precarga en **-1** (todas las capas) automaticamente; si no, se precarga
  en 0 (solo CPU). Un texto junto al campo confirma cual de los dos casos
  detecto. Puedes cambiar el número a mano en cualquier momento.
- **Hilos CPU (n_threads)**: vacio = automatico (por defecto). Solo hace
  falta tocarlo si quieres limitar cuantos hilos de CPU usa la generacion.

Se validan antes de cargar el modelo (numeros enteros, n_ctx y n_threads
mayores a 0, n_gpu_layers mayor o igual a 0 o -1 para "todas") y el mensaje
de "Modelo cargado" confirma con que valores quedo cargado.

## Reductor de repeticion (WordNet)

El `.exe` ya trae los datos de NLTK (stopwords y WordNet), asi que funciona
sin internet. Ejecutando desde el codigo fuente, la primera vez que uses
"Reducir repeticion" o "Reporte de repeticion" la app intenta descargarlos
(~11 MB) si no los tiene. Esto requiere internet **una sola vez**; despues
funciona sin conexion. Si nunca tienes internet disponible, esta funcion
simplemente no sustituira sinonimos (el resto de la app sigue funcionando
igual).

## Sobre el contenido de las historias

Esta app no impone un filtro de contenido propio: lo que se genera depende
del modelo local que elijas y de tus prompts. Ten en cuenta que:

- Los limites de seguridad de cada modelo (si los tiene) dependen de ese
  modelo, no de esta app.
- Usa esta herramienta de forma responsable y conforme a las leyes de tu
  pais, especialmente en cuanto a menores de edad y a personas reales.

## Estructura del proyecto

```
storyforge/
  app/
    project.py       Modelo de datos (plot/personajes/setting/lorebook/capitulos), limites,
                     formato versionado (format_version 2) y guardado atomico
    prompts.py       Plantillas de prompt, guia de estilo, lorebook y recorte de contexto
    chat_format.py   Plantillas de chat (GGUF Jinja, Llama 3, ChatML, Mistral, Alpaca, sin plantilla)
    sampling.py      Muestreo por tarea, presets y semilla
    engine.py        Motor de generacion local (llama-cpp-python)
    gguf.py          Lectura de la cabecera GGUF, modelos partidos, estimacion de VRAM
    settings.py      Opciones por PC (por modelo, ultimo modelo, preferencias)
    paths.py         Donde viven modelos, nltk_data, autoguardado, registro y settings
    fileutil.py      Escritura atomica con reintentos
    repetition.py    Analisis y reduccion de repeticion de palabras
    export.py        Exportacion a .docx / .txt / Markdown / EPUB
    gui.py           Ventana principal (CustomTkinter): abrir/guardar, autoguardado, errores
    ui_*.py          Menu y pestanas (ui_menu, ui_model_tab, ui_story_tabs, ui_lorebook_tab,
                     ui_outline_tab, ui_chapters_tab, ui_chapter_editor), dialogos
                     (ui_dialogs), barra de estado (ui_status), orden de Tab (ui_focus)
                     y piezas comunes (ui_common)
    strings_es.py    Todos los textos visibles de la interfaz
    task_runner.py   Tareas del modelo en segundo plano (ocupado, Detener, errores)
    web_server.py    StoryForge en el celular: servidor web local (--servidor), API JSON
    generator.py     Generador de historias: formulario -> prompt, historial, guardados y presets
    web/             La página del celular (index.html, app.js, style.css), la de conexión con QR
                     y el generador de historias (generador.html/.js/.css)
    main.py          Punto de entrada
  assets/             Icono de la app (icon.ico, icon.png)
  installer/          Instalador de Inno Setup (StoryForge.iss)
  scripts/            run_coverage.ps1 (reporte de cobertura)
  storyforge.py       Script de arranque (usado por PyInstaller)
  storyforge.spec     Especificacion de empaquetado de PyInstaller
  build.bat           Script de una linea para generar el .exe en Windows
  requirements*.txt   Dependencias: app, desarrollo, build fijado, DLLs de CUDA
  models/             Coloca aqui tu modelo .gguf
  tests/              Pruebas automatizadas (pytest)
  docs/               Documentacion tecnica (arquitectura, workflows, historial de fixes)
  GUIA_DE_USUARIO.md  Guia de uso de cada pestana y funcion, para quien usa la app
```

## Pruebas

```
pip install -r requirements-dev.txt
python -m pytest -q
ruff check app tests
```

Resultado el 2026-10-17: **429 passed, 4 skipped, 21 subtests** (los 4
saltados son la prueba opcional con un modelo real); corre la suite tú
mismo antes de confiar en este número. `scripts\run_coverage.ps1` genera el
reporte de cobertura (usa `.venv`). Las pruebas
nunca escriben en tu carpeta de datos real: `tests/conftest.py` y
`tests/test_gui.py` apuntan `STORYFORGE_USER_DATA_DIR` a una carpeta
temporal. CI (`.github/workflows/build-exe.yml`) corre en cada push a
`master` `ruff check app tests` y la suite con cobertura, y
arma dos zips: `StoryForge-<versión>-cpu.zip` y
`StoryForge-<versión>-cuda13.zip`. Un tag `v<versión>` (igual a
`app/__init__.py`) los publica como GitHub Release, junto con el instalador
de cada variante.

`tests/test_real_model.py` es una prueba opcional con un modelo real
(`set STORYFORGE_TEST_MODEL=C:\ruta\modelo-chico.gguf`); sin esa variable
se salta. `tests/test_prompt_snapshots.py` compara cada prompt con
`tests/snapshots/` (regenerar con `STORYFORGE_UPDATE_SNAPSHOTS=1`).

Las pruebas de `project.py`, `repetition.py` (rutas sin datos de NLTK) y la
logica del motor de generacion (con un modelo simulado) no requieren
`llama-cpp-python` ni un modelo real instalados.

## Documentacion tecnica

Este README cubre el uso dia a dia. Para arquitectura, entry points,
comportamiento de cada feature y el historial de bugs corregidos, ver
[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) y
[docs/workflows/README.md](docs/workflows/README.md).
