# Guía de Usuario — StoryForge Local

Esta guía explica **cómo usar** cada parte de la aplicación, pestaña por
pestaña y función por función. Si buscas cómo instalar la app o detalles
técnicos de implementación, revisa [README.md](README.md) (instalación,
rendimiento/GPU, limitaciones) y [docs/](docs/PROJECT_STATUS.md)
(documentación técnica para quien quiera modificar el código).

## Índice

1. [Qué es StoryForge Local](#qué-es-storyforge-local)
   - [Instalar y abrir la app](#instalar-y-abrir-la-app)
2. [Recorrido por cada pestaña](#recorrido-por-cada-pestaña)
3. [Flujo de trabajo recomendado](#flujo-de-trabajo-recomendado)
4. [Guía de cada función en detalle](#guía-de-cada-función-en-detalle)
   - [Flujo outline-first](#flujo-outline-first-generar-el-esquema-completo)
   - [Tipo de escritura](#tipo-de-escritura)
   - [Generar un capítulo](#generar-un-capítulo)
   - [Propósito de capítulo](#propósito-de-capítulo)
   - [Refinar un capítulo](#refinar-un-capítulo)
   - [Versiones anteriores](#versiones-anteriores)
   - [Expandir con IA / Importar desde archivo](#expandir-con-ia--importar-desde-archivo)
   - [Reducir repetición / Reporte de repetición](#reducir-repetición--reporte-de-repetición)
5. [Guardar, abrir y exportar](#guardar-abrir-y-exportar)
6. [Autoguardado y recuperación](#autoguardado-y-recuperación)
   - [Usar StoryForge desde el celular](#usar-storyforge-desde-el-celular)
7. [Límites y validaciones](#límites-y-validaciones)
8. [Convenciones de formato del texto generado](#convenciones-de-formato-del-texto-generado)
9. [Preguntas frecuentes / solución de problemas](#preguntas-frecuentes--solución-de-problemas)

---

## Qué es StoryForge Local

StoryForge Local es una app de escritorio para escribir historias de
ficción largas (hasta 10 capítulos de hasta 10,000 palabras cada uno) a
partir de un plot, personajes y un setting que tú escribes. El texto se
genera **en inglés**, usando un modelo de IA que corre **localmente en tu
PC** — sin depender de internet ni de una API externa una vez que tienes el
modelo descargado.

La interfaz tiene siete pestañas: **Modelo, Plot, Personajes, Setting,
Lorebook, Esquema, Capítulos**. En Modelo cargas la IA; en Plot,
Personajes, Setting y Lorebook defines tu historia; en Esquema y Capítulos
la generas y editas.

### Instalar y abrir la app

- **Con el instalador** (`StoryForge-<versión>-<variante>-setup.exe`): se
  instala solo para tu usuario, sin permisos de administrador, en
  `%LOCALAPPDATA%\Programs\StoryForge`, con acceso directo en el menú
  Inicio (y en el escritorio si lo marcas). Al actualizar, reemplaza el
  programa pero no toca los modelos que copiaste; desinstalar tampoco los
  borra.
- **Con el zip** (`StoryForge-<versión>-cpu.zip` o `-cuda13.zip`):
  descomprímelo donde quieras y ejecuta `StoryForge.exe`. La variante
  `cuda13` usa una GPU NVIDIA; `cpu` funciona en cualquier PC.
- En ambos casos copia tu modelo `.gguf` a la carpeta `models\` que está
  junto a `StoryForge.exe` (ver `models\README.txt` para recomendaciones), o
  guárdalo en otra carpeta —mejor fuera de OneDrive— y configúrala en
  **Archivo > Preferencias**.
- La app no está firmada: Windows SmartScreen puede advertir la primera vez
  ("Más información" > "Ejecutar de todas formas").
- Para ejecutarla desde el código fuente o compilarla tú, ver el
  [README](README.md).

---

## Recorrido por cada pestaña

### 1. Pestaña "Modelo"

Aquí cargas el modelo de IA (`.gguf`) que va a escribir tu historia. Sin un
modelo cargado, ninguna función de generación funciona (el resto de la app
— guardar, escribir tus notas, exportar — sí funciona sin modelo).

- **Selector de archivo**: elige un modelo de la carpeta `models/`, con
  "Elegir archivo..." si está en otro lado, o "Actualizar lista" si acabas
  de copiar uno nuevo a `models/`.
- **Cargar modelo**: carga el modelo seleccionado. Puede tardar desde
  algunos segundos hasta un minuto o más, dependiendo del tamaño del
  archivo.
- **Configuración avanzada** (no hace falta tocarla si no sabes qué son):
  - **Contexto (n_ctx)**: cuánta "memoria" de una sola vez tiene el modelo
    para leer tu plot/personajes/setting/capítulos anteriores. La primera
    vez que eliges un modelo se propone su contexto de entrenamiento (como
    mucho 16k); `0` usa exactamente ese. Si pides más de lo que el modelo
    aprendió, la app avisa antes de cargar.
  - **Capas en GPU (n_gpu_layers)**: si la app detecta soporte de GPU se
    propone `-1` (todas las capas); sin GPU, `0`. **Estimar VRAM** calcula si
    el modelo cabe en la VRAM libre con ese contexto y completa el número de
    capas sugerido.
  - **Flash attention, lote (n_batch / n_ubatch) y caché KV**: con GPU,
    flash attention y un lote de 1024-2048 aceleran la lectura del prompt; la
    caché KV `q8_0` ocupa la mitad de memoria (requiere flash attention).
  - Debajo del selector se ve la información del modelo (arquitectura,
    cuantización, tamaño, contexto entrenado, si trae plantilla de chat). Un
    modelo partido en varios archivos aparece una sola vez; si le faltan
    partes se marca "incompleto" y no se puede cargar.
  - La app recuerda estas opciones **por modelo y por PC**, y al abrir un
    proyecto preselecciona el modelo con el que se escribió (o avisa si ese
    archivo ya no está).
  - **Hilos CPU (n_threads)**: vacío = automático (recomendado para la
    mayoría). Solo tócalo si quieres limitar cuántos núcleos de tu CPU usa
    la generación.
- **Formato de chat**: cómo se le "habla" al modelo. Los modelos *instruct*
  (Llama 3 Instruct, Mistral, Qwen y sus derivados) siguen mucho mejor las
  instrucciones cuando las reciben en el formato de turnos con el que fueron
  entrenados.
  - **Auto (desde el GGUF)** (por defecto): usa la plantilla que trae el
    archivo `.gguf`; si no trae ninguna, la deduce del vocabulario del modelo
    (por ejemplo, detecta Llama 3 aunque el GGUF no traiga plantilla).
  - **Llama 3 / ChatML / Mistral / Alpaca**: fuerza una plantilla concreta,
    por si "Auto" elige mal.
  - **Sin plantilla (modelo base)**: el modo de antes (texto corrido), para
    modelos *base* que no son instruct.
  - Se recuerda por modelo, y se puede cambiar sin volver a cargar el modelo.
    El estatus muestra qué formato quedó en uso.
- El estatus abajo confirma qué modelo quedó cargado y con qué
  configuración, o muestra el error si algo falló (archivo corrupto,
  incompatible, etc.).

### 2. Pestaña "Plot"

Escribe aquí la idea/premisa de tu historia: de qué trata, quién es el
protagonista, qué conflicto central impulsa la trama. Límite: 50,000
palabras. Cuanto más claro y concreto, mejor guía le das al modelo.

Junto al contador de palabras tienes dos botones (ver la sección
["Expandir con IA / Importar desde archivo"](#expandir-con-ia--importar-desde-archivo)
más abajo para el detalle):
- **Importar desde archivo...**: trae el texto de un `.txt` directamente.
- **Expandir con IA**: convierte una nota corta en una versión más
  desarrollada (necesita un modelo cargado).

### 3. Pestaña "Personajes"

Describe aquí a tus personajes: personalidad, apariencia, relaciones entre
ellos, motivaciones. Límite: 10,000 palabras. Mismos botones de
importar/expandir que Plot.

### 4. Pestaña "Setting"

Describe dónde y cuándo ocurre la historia: época, lugar, ambiente, reglas
del mundo si aplica (por ejemplo, en fantasía o ciencia ficción). Límite:
10,000 palabras. Mismos botones de importar/expandir.

### 5. Pestaña "Esquema"

Aquí generas (opcionalmente, pero muy recomendado) un **esquema completo de
toda la historia** antes de escribir prosa — ver
["Flujo outline-first"](#flujo-outline-first-generar-el-esquema-completo)
más abajo.

### Muestreo (pestaña "Modelo", abajo)

Cómo de creativo o preciso escribe el modelo. **Preset** de la prosa:
Creativo, Equilibrado (por defecto), Preciso, o Personalizado (editas
temperatura, min_p, top_p, top_k y penalizaciones). Los resúmenes, el
esquema y los refinados usan sus propios valores, más conservadores.
**Semilla**: vacía = aleatoria (la barra de estado y el mensaje de "Listo"
muestran la que se usó); "Usar la última" la copia para repetir exactamente
un resultado. Se guarda con el proyecto.

### Pestaña "Lorebook"

Personajes secundarios, lugares u objetos que no hace falta repetir en
Personajes/Setting. Cada entrada tiene nombre, **palabras clave**
(separadas por coma) y texto, y solo entra en el prompt cuando alguna
palabra clave aparece en el esquema del capítulo, en el resumen de los
capítulos anteriores o en lo último que se escribió (también si la menciona
el texto de otra entrada que sí coincidió). Opciones: **Activa** (desmarcada
nunca se usa), **Incluir siempre** y **Prioridad** (con muchas
coincidencias entran primero las de mayor prioridad). Después de generar,
cada entrada usada muestra "✓ usada en la última generación" y por qué. El
buscador filtra por nombre o palabra clave.

### 6. Pestaña "Capítulos"

Donde generas y editas la prosa de cada capítulo. Se edita **un capítulo a
la vez**, con el cuadro de texto ocupando todo el alto de la ventana: la
columna de la izquierda lista los capítulos y un click muestra ese capítulo
(el resaltado indica cuál estás viendo). Cada capítulo tiene título,
palabras objetivo, propósito narrativo, botones de generación/edición, el
texto en sí y su resumen.

**Atajos de teclado:** Ctrl+N (nuevo proyecto), Ctrl+O (abrir), Ctrl+S
(guardar), Ctrl+Shift+S (guardar como), Ctrl+Z / Ctrl+Y (deshacer/rehacer en
cualquier cuadro de texto), Ctrl+Enter dentro del texto de un capítulo
(Generar si está vacío, Continuar si ya tiene texto), Esc (cancelar la tarea
en curso), Ctrl+F (buscar y reemplazar en el capítulo), Ctrl+Shift+F (buscar
en todo el proyecto) y F11 (modo enfoque: oculta la lista de capítulos, el
refinamiento y el resumen). **Tab / Shift+Tab** recorren los campos y
botones de cada panel y diálogo en el orden en que se ven (los ocultos o
deshabilitados se saltan).

**Más funciones del capítulo:**
- **Nota del autor**: una instrucción corta ("Elena oculta que está
  herida") que el modelo lee justo antes de escribir cada sección; hay otra
  para toda la historia en la pestaña Plot.
- **Reintentar** repite la última ejecución de Generar/Continuar desde el
  mismo punto (con otra semilla) y guarda cada resultado como alternativa;
  `<` y `>` las recorren. Las alternativas se guardan con el proyecto (las
  10 más recientes), así que al reabrirlo siguen ahí; editar el texto a mano
  las descarta. "Reintentar" en sí vale solo en la sesión en que generaste.
- **Clic derecho sobre texto seleccionado**: Reescribir, Expandir,
  Describir o Acortar solo ese fragmento (o con una instrucción propia). Ves
  una vista previa con diferencias antes de aceptar.
- **Más herramientas**: Reducir repetición, Reporte de repetición, Buscar y
  reemplazar y Eliminar capítulo.
- La lista de la izquierda muestra palabras escritas / objetivo de cada
  capítulo, y la barra de estado el total del proyecto.

**Barra de estado (abajo):** operación en curso y tiempo, tokens por
segundo, palabras y tiempo restante estimado, uso de la ventana de contexto
(en ámbar/rojo cuando se acerca al límite), **Ver prompt** (el texto exacto
que recibió el modelo) y **Detener** (para cualquier tarea: capítulo,
esquema, resumen, refinado, expandir).

---

## Flujo de trabajo recomendado

1. **Modelo**: descarga un modelo `.gguf` (ver `models/README.txt` para
   recomendaciones) y cárgalo.
2. **Plot / Personajes / Setting**: escribe (o expande con IA) las tres
   bases de tu historia.
3. **Esquema**: genera el esquema completo de todos los capítulos de un
   jalón. Revísalo y ajústalo a mano si algo no te convence.
4. **Capítulos**: agrega los capítulos (si generaste el esquema, ya
   aparecen automáticamente con título y esquema asignado) y genera la
   prosa de cada uno, en orden — cada capítulo usa el resumen de los
   anteriores para mantener continuidad.
5. Si algo no quedó como querías: **refínalo** con una instrucción puntual,
   o **regenéralo** desde cero (la versión anterior queda guardada, ver
   ["Versiones anteriores"](#versiones-anteriores)).
6. **Reduce repetición** si el texto abusa de ciertas palabras.
7. **Guarda tu proyecto** regularmente, y **exporta** a Word, EPUB,
   Markdown o TXT cuando la historia esté lista.

No es obligatorio seguir este orden al pie de la letra (puedes escribir
capítulos sin esquema, por ejemplo), pero generar el esquema primero mejora
mucho la coherencia de una historia larga frente a improvisar capítulo por
capítulo.

---

## Guía de cada función en detalle

### Flujo "outline-first" (generar el esquema completo)

En la pestaña Esquema:

1. Escribe "Número de capítulos" (máximo 10).
2. Elige, opcionalmente, un **"Tipo de escritura"** (ver abajo) — aplica a
   toda la historia, esquema incluido.
3. Click en **"Generar esquema completo"**.
4. El modelo genera, de un jalón, un título + 2 a 4 eventos clave por cada
   capítulo. Si ya tenías capítulos, se te pide confirmar — se reemplaza el
   título y esquema de cada uno, pero **la prosa ya generada se conserva**.
   Se aceptan los formatos que los modelos suelen usar aunque se les pida
   texto plano (`**Chapter 1: ...**`, `### Chapter 1 - ...`,
   `Chapter One: ...`, números romanos). Si la respuesta no tiene ningún
   encabezado de capítulo reconocible, se muestra un error con la respuesta
   del modelo y **no se modifica nada** (antes se metía todo el texto en el
   esquema del capítulo 1). Si salen menos capítulos de los pedidos, o la
   respuesta se cortó por largo, el estado lo avisa como "Esquema
   incompleto".
5. Puedes editar el resultado libremente antes de pasar a "Capítulos" a
   generar la prosa. Cada esquema individual tiene un límite de 800
   palabras.

Cuando generes la prosa de un capítulo que tiene esquema asignado, el
modelo lo recibe como guía obligatoria de los eventos a cubrir, además de
una lista compacta de los títulos de todos los capítulos planeados (para
que tenga conciencia del arco completo de la historia).

### Tipo de escritura

Selector en la pestaña Esquema, junto a "Número de capítulos". Aplica a
**toda la historia** (esquema y cada capítulo), no a uno solo. Opciones:

| Opción | Qué enfatiza |
|---|---|
| Narrativa | Ritmo de trama: causa y efecto claro entre eventos |
| Descriptiva | Descripción sensorial rica: ambiente, detalle físico |
| Creativa | Prosa literaria e imaginativa: metáforas, riesgo estilístico |
| Diálogo | Escenas conducidas por diálogo, poca narración entre líneas |
| Poética | Prosa lírica y rítmica, lenguaje evocador |
| Acción rápida | Oraciones cortas, ritmo alto, poca introspección |

Elegir "(Por defecto)" no aplica ningún énfasis adicional — solo las
convenciones de formato normales (ver más abajo).

### Generar un capítulo

En la pestaña Capítulos, cada panel tiene:

- **Título** y **Palabras objetivo** (máximo 10,000).
- **Generar**: escribe el capítulo desde cero. Si el capítulo ya tenía
  contenido, se te pide confirmar (la versión anterior se guarda
  automáticamente, ver ["Versiones anteriores"](#versiones-anteriores)).
- **Continuar**: sigue escribiendo desde el final del texto actual, sin
  borrar nada (si el capítulo ya llegó a su objetivo, agrega una sección
  más, ~900 palabras). Úsalo después de cancelar, de editar a mano, o
  cuando quieras más texto.
- **Desde el cursor** (continuar desde el cursor): igual, pero desde donde está el cursor en
  el texto; lo que haya después del cursor se reemplaza (se te pide
  confirmar y la versión anterior queda en "Versiones anteriores").
- Al continuar, el modelo recibe **todo lo que quepa** del capítulo ya
  escrito (no solo las últimas 400 palabras), y una pista de por qué evento
  del esquema debería ir.
- El capítulo se escribe **por secciones** (de a ~900 palabras),
  mostrando el progreso en vivo, hasta acercarse al objetivo. Esto existe
  para poder llegar a objetivos largos sin exceder lo que un modelo local
  puede escribir de un jalón. Cada sección escribe solo su parte del esquema
  (por ejemplo, los eventos 1-2 de 6) y solo la última cierra el capítulo;
  el capítulo se da por terminado cuando llega al objetivo, o cuando el
  modelo lo cierra por su cuenta con al menos el 80 % escrito. Si te quedan
  capítulos cortos, un esquema con más eventos y un modelo más capaz ayudan
  más que subir el objetivo (ver las recomendaciones de
  `models/README.txt`).
- **Cancelar** (o Esc): se detiene en segundos, a mitad de la sección si
  hace falta, conservando lo generado hasta ese punto. Después puedes seguir
  con "Continuar".
- **Mientras el modelo escribe, el texto de ese capítulo queda en solo
  lectura** (borde amarillo): antes, lo que tecleabas ahí se perdía al
  terminar la generación. Puedes seguir editando los demás capítulos.
- Si una sección se corta por largo a mitad de una oración, la siguiente
  sigue esa misma oración (ya no se parte en dos párrafos). Si el modelo
  cierra el capítulo por su cuenta cerca del objetivo (80% o más), el
  capítulo se da por terminado; si lo cierra mucho antes, se le pide que
  siga sin concluir todavía.
- Al terminar, la app le pide al modelo un **resumen** del capítulo, que se
  usa como contexto de continuidad para los capítulos siguientes. Los
  capítulos siguientes reciben siempre el resumen del capítulo
  inmediatamente anterior y sus últimas líneas, más los resúmenes de los
  capítulos previos que quepan (del más reciente al más antiguo).

**El resumen de cada capítulo** está debajo de su texto ("Mostrar
resumen"): puedes leerlo y corregirlo a mano (se guarda con el proyecto).
Al lado del conteo de palabras verás "Resumen al día", "Resumen
desactualizado" (cambiaste el texto después de resumirlo: al refinar,
restaurar una versión, reducir repetición, continuar, cancelar o editar a
mano) o "Sin resumen". "Regenerar resumen" lo vuelve a pedir al modelo. Al
generar o continuar un capítulo, si algún capítulo anterior tiene el resumen
desactualizado o sin hacer, la app ofrece regenerarlo primero. Los capítulos
muy largos se resumen por partes, así que los eventos del medio ya no se
pierden.

**Cuánto tarda**: en una CPU normal, una sección de ~900 palabras puede
tardar entre 1 y 4 minutos; un capítulo completo de 10,000 palabras puede
tomar entre 15 y 40 minutos. Es normal, no es un error.

**Mientras se genera un capítulo**, no puedes generar otro capítulo, el
esquema, cargar un modelo distinto, ni agregar/quitar capítulos — la app
bloquea esas acciones hasta que termine (el motor de IA solo puede atender
una cosa a la vez).

### Propósito de capítulo

Selector "Propósito" en cada capítulo (debajo del título), independiente
del "Tipo de escritura" (que es de toda la historia). Le dice al modelo qué
rol narrativo cumple **ese capítulo específico**:

| Opción | Qué le pide al modelo |
|---|---|
| Apertura | Presentar el mundo normal y el incidente que arranca la historia, sin resolver nada todavía |
| Escena climática | Construir hacia la confrontación decisiva del conflicto central |
| Final | Resolver el conflicto central, sin introducir tramas nuevas sin resolver |
| Epílogo | Mostrar el después, en un registro más corto y reflexivo, sin conflicto nuevo |

"(Capítulo regular)" — la opción por defecto — no agrega ninguna
instrucción especial. Tú decides qué capítulo es cuál; la app no valida que
tenga sentido con la posición del capítulo en la historia.

### Refinar un capítulo

En vez de regenerar un capítulo entero desde cero, puedes pedirle al modelo
que lo **reescriba según una instrucción puntual** — por ejemplo "hazlo más
oscuro" o "acorta el diálogo del final".

1. El capítulo debe tener contenido ya generado.
2. Escribe la instrucción en el campo "Instrucción de refinamiento" (abajo
   del todo del panel del capítulo).
3. Click en **"Aplicar refinamiento"**. El modelo reescribe el capítulo
   aplicando tu instrucción (la barra de estado muestra "parte i de n" si es
   largo; "Detener" lo cancela sin tocar nada).
4. Se abre una **vista previa lado a lado** con lo quitado en rojo y lo
   agregado en verde. Nada cambia hasta que eliges **Aceptar**, **Aceptar y
   seguir refinando** (aplica y deja el campo listo para otra instrucción) o
   **Descartar**. Al aceptar, la versión anterior se guarda en "Versiones
   anteriores" con la instrucción usada.

**Importante**: el capítulo **nunca se recorta** al refinar. Si cabe
completo en el contexto del modelo, se revisa de una sola vez; si no (un
capítulo largo con un `n_ctx` chico), la app lo revisa **por partes**
(grupos de párrafos consecutivos, aplicando la misma instrucción a cada
parte) y las vuelve a unir en orden. Una instrucción que depende de todo el
capítulo a la vez ("cambia el final para que conecte con el inicio")
funciona mejor si el capítulo cabe entero: sube `n_ctx` en la pestaña
Modelo si tu hardware lo permite. Si alguna parte vuelve vacía, el capítulo
no se modifica y se muestra un error.

Cada clic en "Aplicar refinamiento" es independiente — no es una
conversación con memoria de instrucciones anteriores más allá de su efecto
ya aplicado al texto. Si quieres deshacer un refinamiento, usa "Versiones
anteriores" en vez de pedirle al modelo que "deshaga lo último".

### Versiones anteriores

Cada capítulo guarda automáticamente su versión previa cuando:
- Lo **regeneras** o **continúas** (y ya tenía contenido), incluido
  **Reintentar**.
- Lo **refinas** o **reescribes una selección** (clic derecho).
- **Reemplazas** texto con Buscar y reemplazar (en el capítulo o en todo el
  proyecto).
- Le aplicas **"Reducir repetición"**.
- **Restauras** otra versión.

Se guardan hasta **20 versiones** por capítulo (la más vieja se descarta
al llegar al límite); **"Versiones guardadas por capítulo"**, en la pestaña
Plot, cambia ese número para el proyecto (5, 10, 20, 50 o 100; rige desde el
próximo cambio de cada capítulo). Cada versión indica de dónde viene (generar,
continuar, refinar con qué instrucción, reescribir selección, reemplazar,
restaurar...) y la fecha, y "Comparar con la actual" muestra las
diferencias.

Para recuperar una versión anterior:
1. Click en **"Versiones anteriores (N)"** en el panel del capítulo (el
   número indica cuántas hay guardadas; con 0 solo muestra un aviso).
2. Se abre una ventana con un desplegable (la versión más reciente
   primero) y una vista previa de solo lectura del texto de esa versión.
3. **"Restaurar esta versión"** reemplaza el contenido actual del capítulo
   por la versión elegida — y de paso, **guarda lo que tenías antes de
   restaurar** como una versión nueva, así que restaurar también se puede
   deshacer.

Esto no cubre ediciones manuales que hagas escribiendo directamente en la
caja de texto del capítulo (para esas está Ctrl+Z) — solo se activa con
las acciones de arriba.

### Expandir con IA / Importar desde archivo

Disponibles en Plot, Personajes y Setting, junto al contador de palabras de
cada uno.

**Expandir con IA** (necesita un modelo cargado):
1. Escribe una nota corta — una idea en una o dos oraciones alcanza.
2. Click en "Expandir con IA".
3. Si el campo ya tiene bastante texto (más de ~60 palabras), se te pide
   confirmar — expandir **reemplaza** el campo completo, no agrega al
   final.
4. El modelo desarrolla tu nota en una versión más completa, sin inventar
   una historia distinta a la que ya planteaste (misma premisa/personajes/
   ambientación, solo con más detalle). La expansión queda acotada a un
   máximo de 500 palabras, sin importar el límite real del campo.

**Importar desde archivo...** (no necesita modelo, no llama a la IA):
1. Click en el botón, elige un archivo `.txt`.
2. Si el campo ya tiene contenido, se te pide confirmar el reemplazo.
3. El contenido del archivo reemplaza el campo directamente.

### Reducir repetición / Reporte de repetición

En cada capítulo, dentro de **Más herramientas**, dos acciones basadas en
análisis de palabras (WordNet, no IA generativa):

- **Reporte de repetición**: muestra qué palabras se usan con más
  frecuencia de la recomendada, sin cambiar nada.
- **Reducir repetición**: reemplaza automáticamente las repeticiones
  excesivas por sinónimos (a partir de la 2ª aparición de cada palabra en
  adelante; la primera aparición se deja intacta como "ancla"). Guarda la
  versión anterior antes de aplicar el cambio (ver "Versiones anteriores").

**Nota**: el `.exe` ya trae los datos de NLTK que necesita. Ejecutando
desde el código fuente, la primera vez que uses cualquiera de los dos la
app intenta descargarlos (~11 MB) si no los tiene — requiere internet una
sola vez; después funciona offline. Sin esos datos, el reporte igual
funciona, pero "Reducir repetición" no tiene sinónimos para sustituir.

Esta es una pasada basada en reglas, no una reescritura con IA: conserva la
estructura de la oración y solo cambia la palabra puntual — revisa el
resultado, un sinónimo ocasionalmente no encaja gramaticalmente con el
tiempo verbal o la función de la palabra en esa oración específica.

---

## Guardar, abrir y exportar

Todo desde el menú **Archivo**:

- **Nuevo proyecto**: empieza de cero (pide confirmar si hay cambios sin
  guardar).
- **Abrir proyecto...**: carga un proyecto guardado antes (`.storyforge.json`
  o `.json`). Si el archivo está dañado y existe la copia `.bak` de la
  versión anterior, la app ofrece abrirla.
- **Guardar proyecto** / **Guardar proyecto como...**: guarda todo
  (plot, personajes, setting, esquema, capítulos, lorebook, muestreo, nota
  del autor, título y autor) en un archivo `.storyforge.json`. El título de
  la ventana muestra el nombre del archivo y un `•` si hay cambios sin
  guardar; nuevo/abrir/salir solo preguntan si los hay.
- **Exportar a Word (.docx)**: portada con título y autor, un capítulo por
  página; `*cursiva*` y `**negrita**` se convierten en formato real.
- **Exportar a EPUB** (para lectores de libros electrónicos) y **a
  Markdown**.
- **Exportar a TXT**: la historia completa como texto plano.
- El título, el autor y el encabezado de capítulo al exportar ("Chapter N:
  título", "Capítulo N: título" o solo el título) se eligen arriba en la
  pestaña Plot.
- **Preferencias...**: tema (oscuro, claro, sistema), escala, fuente e
  interlineado del editor y una carpeta de modelos adicional (útil para
  guardarlos fuera de OneDrive).

Ninguna exportación incluye el esquema ni las versiones
anteriores — solo el título y contenido final de cada capítulo.

## Usar StoryForge desde el celular

Puedes escribir desde el navegador del celular mientras el modelo sigue
corriendo en tu PC (no hace falta instalar nada en el celular).

1. En la PC, abre **"StoryForge Local en el celular"** desde el menú Inicio
   (o ejecuta `StoryForge.exe --servidor`; sin empaquetar:
   `python storyforge.py --servidor`). En lugar de la ventana de siempre se
   abre en el navegador de la PC una página con un **código QR**.
2. Si Windows pregunta si StoryForge puede usar la red, permítelo en
   **redes privadas**.
3. Con el celular conectado a la **misma red Wi-Fi**, escanea el QR (o
   escribe el enlace que aparece debajo). En el menú del navegador,
   "Agregar a la pantalla de inicio" lo deja como una app.
4. En **Inicio** carga el modelo (se usan los mismos ajustes que guardaste
   para ese modelo en la pestaña Modelo: capas en GPU, contexto...) y crea o
   abre un proyecto. Después: **Historia** (plot, personajes, setting, tipo
   de escritura), **Esquema**, **Capítulos** (Generar / Continuar / Detener,
   con el texto apareciendo en vivo) y **Exportar** (Word, EPUB, Markdown o
   texto, descargado al celular).

Cosas a tener en cuenta:

- El enlace lleva una **clave de acceso**: quien lo tenga y esté en tu red
  puede usar StoryForge. No lo compartas. Sigue sirviendo después de
  reiniciar el servidor.
- Los proyectos del modo celular viven en su propia carpeta (la página del
  QR la muestra; `--carpeta <ruta>` la cambia y se recuerda). Para seguir en
  el celular un proyecto empezado en la PC, cópialo a esa carpeta, y al
  revés: el archivo `.storyforge.json` es el mismo formato.
- No abras el mismo proyecto a la vez en la ventana de StoryForge y en el
  celular: cada uno guardaría encima de los cambios del otro. Tampoco
  conviene tener la ventana y el servidor con un modelo cargado al mismo
  tiempo (serían dos copias del modelo en memoria).
- Cada cambio se guarda en el momento. Mientras el modelo trabaja, el
  proyecto no se puede editar (los botones quedan desactivados).
- Al generar un capítulo, los resúmenes faltantes o desactualizados de los
  capítulos anteriores se regeneran antes, sin preguntar (son su contexto).
- En el celular están las funciones principales; Lorebook, refinar,
  reescribir una selección, versiones anteriores y reducir repetición
  siguen en la ventana de la PC.
- Para apagarlo: botón **"Detener el servidor"** en la página del QR (o
  Ctrl+C en la consola).

## Autoguardado y recuperación

La app guarda tu progreso automáticamente en una copia separada de tu
guardado manual: cada 20 segundos mientras hay una generación en curso
(capítulo, esquema, refinamiento) y cada minuto si escribiste algo sin
guardar — así un cierre inesperado (crash, corte de luz) no te hace perder
ni una generación larga ni lo que escribiste a mano. La escritura se hace en
segundo plano, sin congelar la ventana.

Si la app detecta esa copia al arrancar, te pregunta si quieres
recuperarla. Al recuperar, tienes que elegir dónde guardar el proyecto de
nuevo (no sobrescribe automáticamente ningún archivo). La copia se borra
sola en cuanto guardas el proyecto de forma explícita, o si decides no
guardar al cerrar la app.

En el `.exe`, la copia de autoguardado vive en
`%APPDATA%\StoryForge\autosave\` (y los errores se registran en
`%APPDATA%\StoryForge\storyforge.log`); ejecutando desde el código fuente,
en la carpeta `autosave\` del proyecto. Si el autoguardado no se puede
escribir, la app te avisa una vez por sesión en vez de fallar en silencio.
Si defines la variable de entorno `STORYFORGE_USER_DATA_DIR`, el
autoguardado, el registro y `settings.json` (el formato de chat recordado
por modelo) van a esa carpeta (útil para una instalación portable; las
pruebas automáticas la usan para no tocar nunca tu autoguardado real).

Si ocurre un error inesperado (un fallo interno de la app), ahora se
muestra un aviso con el mensaje y se registra con todo el detalle en
`storyforge.log`; **Ayuda > Abrir carpeta de registros** abre esa carpeta.
Antes, en el `.exe`, esos errores no dejaban ningún rastro.

Guardar un proyecto es atómico: se escribe primero a un archivo temporal y
solo entonces reemplaza al anterior, que queda como `<archivo>.json.bak`.
Si el guardado falla (disco lleno, carpeta sin permisos), ves un mensaje de
error y el archivo anterior queda intacto; si pasa al cerrar la app, la app
no se cierra.

Al cerrar la app (con la X de la ventana o "Salir" del menú), siempre se te
pregunta si quieres guardar — con opción de cancelar el cierre.

---

## Límites y validaciones

| Campo | Límite |
|---|---|
| Plot | 50,000 palabras |
| Personajes | 10,000 palabras |
| Setting | 10,000 palabras |
| Capítulos por historia | 10 |
| Palabras por capítulo | 10,000 |
| Esquema por capítulo | 800 palabras |
| Versiones anteriores por capítulo | 20 (configurable: 5 a 100) |
| Nota del autor | 150 palabras |
| Entradas del Lorebook | 200 (de hasta 500 palabras cada una) |

Si algo excede un límite, la app te avisa antes de generar o guardar — no
te bloquea de escribir de más, pero sí de generar/guardar con esos
excedentes sin antes confirmar o corregir. Excepción: el **texto** de un
capítulo que pasa de 10,000 palabras (p.ej. por editarlo a mano) es solo
una advertencia al guardar y no bloquea generar otros capítulos ni el
esquema; al generar, la última sección se ajusta para no pasarse del límite.

## Convenciones de formato del texto generado

El modelo siempre recibe estas reglas, sin importar qué tipo de escritura o
propósito de capítulo hayas elegido:

- Narración en tercera persona, tiempo pasado, por defecto.
- Pensamientos internos de un personaje: entre `*asteriscos*`, primera
  persona, tiempo presente.
- Diálogo: comillas estándar, un párrafo nuevo por cada personaje que
  habla.
- Sin repetir la misma palabra o frase descriptiva más de dos veces en la
  misma escena (aunque para eso también existe "Reducir repetición", por
  si el modelo no lo logra del todo).
- Todo el texto generado es en **inglés**, sin importar en qué idioma
  escribas tus notas de Plot/Personajes/Setting.

---

## Preguntas frecuentes / solución de problemas

**"El contexto es demasiado grande para este modelo"**
Tu plot/personajes/setting/esquema/capítulo (para refinar) son demasiado
largos para la ventana de contexto (`n_ctx`) del modelo cargado. La app ya
intenta recortar automáticamente en varios niveles antes de rendirse — si
aun así falla, acorta tus notas, baja el objetivo de palabras, o sube
`n_ctx` en la pestaña Modelo (pestaña "Modelo") si tu hardware lo permite.

**No aparece ningún mensaje de error y algo claramente falló**
Si esto te pasa en una versión anterior a la que tienes ahora, era un bug
real (ya corregido) donde los errores de generación fallaban en completo
silencio. Si te sigue pasando, revisa que tengas la última versión.

**El botón de generar/refinar/expandir está deshabilitado y no sé por qué**
Probablemente hay otra generación en curso en otra parte de la app (otro
capítulo, el esquema, cargar un modelo) — solo se puede hacer una cosa a la
vez porque el modelo de IA no soporta llamadas simultáneas. Espera a que
termine la que está en curso.

**"Reducir repetición" no cambia nada**
O el texto no tiene palabras suficientemente repetidas para que se active,
o no se pudieron descargar/encontrar los datos de NLTK (necesitas internet
la primera vez). "Reporte de repetición" te dice si detectó algo.

**Un capítulo tarda muchísimo en generarse**
Es esperable en CPU (15-40 minutos para 10,000 palabras). Si tienes una GPU
NVIDIA, revisa la sección "Rendimiento / GPU" del [README](README.md) — ya
no hace falta editar código, puedes configurar `n_gpu_layers` desde la
pestaña Modelo una vez instalada la versión de `llama-cpp-python` con
soporte CUDA.

**Perdí una versión anterior de un capítulo**
Se guardan las últimas 20 versiones por capítulo (o las que elijas en
"Versiones guardadas por capítulo", pestaña Plot); a partir de ahí cada
cambio nuevo descarta la más vieja.

**¿Por qué el modelo se niega a escribir cierto contenido?**
Depende del modelo que elijas, no de esta app — StoryForge Local no impone
ningún filtro de contenido propio, pero algunos modelos tienen su propio
entrenamiento de seguridad. Ver la sección correspondiente en el
[README](README.md).
