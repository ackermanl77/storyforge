# Guía de Usuario — StoryForge Local

Esta guía explica **cómo usar** cada parte de la aplicación, pestaña por
pestaña y función por función. Si buscas cómo instalar la app o detalles
técnicos de implementación, revisa [README.md](README.md) (instalación,
rendimiento/GPU, limitaciones) y [docs/](docs/PROJECT_STATUS.md)
(documentación técnica para quien quiera modificar el código).

## Índice

1. [Qué es StoryForge Local](#qué-es-storyforge-local)
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

La interfaz tiene seis pestañas: **Modelo, Plot, Personajes, Setting,
Esquema, Capítulos**. Las primeras cuatro son donde defines tu historia; las
últimas dos son donde la generas y editas.

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
    para leer tu plot/personajes/setting/capítulos anteriores. Por defecto
    8192. Súbelo si te encuentras con errores de "el contexto es demasiado
    grande" — pero ocupa más RAM y puede ser más lento.
  - **Capas en GPU (n_gpu_layers)**: 0 = solo CPU (por defecto). Solo sirve
    si instalaste una versión de `llama-cpp-python` con soporte de GPU (ver
    sección "Rendimiento / GPU" en el README).
  - **Hilos CPU (n_threads)**: vacío = automático (recomendado para la
    mayoría). Solo tócalo si quieres limitar cuántos núcleos de tu CPU usa
    la generación.
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

### 6. Pestaña "Capítulos"

Donde generas y editas la prosa de cada capítulo, uno por uno. Cada
capítulo tiene su propio panel con título, palabras objetivo, propósito
narrativo, botones de generación/edición, y el texto en sí.

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
7. **Guarda tu proyecto** regularmente, y **exporta** a Word o TXT cuando
   la historia esté lista.

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
- **Generar**: dispara la generación. Si el capítulo ya tenía contenido, se
  te pide confirmar (la versión anterior se guarda automáticamente, ver
  ["Versiones anteriores"](#versiones-anteriores)).
- El capítulo se escribe **por secciones** (de a ~900 palabras),
  mostrando el progreso en vivo, hasta acercarse al objetivo. Esto existe
  para poder llegar a objetivos largos sin exceder lo que un modelo local
  puede escribir de un jalón.
- **Cancelar**: se detiene al terminar la sección actual (no a la mitad de
  una), conservando lo generado hasta ese punto.
- Al terminar, la app le pide al modelo un **resumen** del capítulo, que se
  usa como contexto de continuidad para el siguiente capítulo.

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
3. Click en **"Aplicar refinamiento"** y confirma.
4. La versión anterior se guarda automáticamente (ver "Versiones
   anteriores"). El modelo reescribe el capítulo completo aplicando tu
   instrucción, manteniendo la trama y los personajes.

**Importante**: a diferencia de generar (que se hace por secciones),
refinar necesita que el capítulo **completo** quepa en el contexto del
modelo de una sola vez, sin barra de progreso por secciones. Un capítulo
muy largo (varios miles de palabras) puede fallar con un error de "contexto
demasiado grande" si tu modelo tiene un `n_ctx` chico — en ese caso, sube
`n_ctx` en la pestaña Modelo (si tu hardware lo permite) o acorta el
capítulo primero.

Cada clic en "Aplicar refinamiento" es independiente — no es una
conversación con memoria de instrucciones anteriores más allá de su efecto
ya aplicado al texto. Si quieres deshacer un refinamiento, usa "Versiones
anteriores" en vez de pedirle al modelo que "deshaga lo último".

### Versiones anteriores

Cada capítulo guarda automáticamente su versión previa cuando:
- Lo **regeneras** (y ya tenía contenido).
- Lo **refinas**.
- Le aplicas **"Reducir repetición"**.

Se guardan hasta **5 versiones** por capítulo (la más vieja se descarta al
llegar al límite, sin aviso).

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
caja de texto del capítulo — solo se activa con los tres botones de arriba.

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

En cada capítulo, dos botones basados en análisis de palabras (WordNet, no
IA generativa):

- **Reporte de repetición**: muestra qué palabras se usan con más
  frecuencia de la recomendada, sin cambiar nada.
- **Reducir repetición**: reemplaza automáticamente las repeticiones
  excesivas por sinónimos (a partir de la 2ª aparición de cada palabra en
  adelante; la primera aparición se deja intacta como "ancla"). Guarda la
  versión anterior antes de aplicar el cambio (ver "Versiones anteriores").

**Nota**: la primera vez que uses cualquiera de los dos, la app intenta
descargar datos de NLTK (~35 MB) si no los tiene — requiere internet una
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
- **Abrir proyecto...**: carga un archivo `.json` de proyecto guardado
  antes.
- **Guardar proyecto** / **Guardar proyecto como...**: guarda todo
  (plot, personajes, setting, esquema, capítulos, tipo de escritura,
  configuración) en un archivo `.json`.
- **Exportar a Word (.docx)**: genera un documento Word con un
  encabezado por capítulo; los pensamientos internos marcados con
  `*asteriscos*` en el texto se convierten en cursiva real.
- **Exportar a TXT**: exporta la historia completa como texto plano.

Ninguna de las dos exportaciones incluye el esquema ni las versiones
anteriores — solo el título y contenido final de cada capítulo.

## Autoguardado y recuperación

Mientras hay una generación en curso (capítulo, esquema, refinamiento), la
app guarda tu progreso automáticamente cada 20 segundos en una copia
separada de tu guardado manual — pensado para que un cierre inesperado
(crash, corte de luz) durante una generación larga (que puede tomar 15-40
minutos) no te haga perder todo.

Si la app detecta esa copia al arrancar, te pregunta si quieres
recuperarla. Al recuperar, tienes que elegir dónde guardar el proyecto de
nuevo (no sobrescribe automáticamente ningún archivo). La copia se borra
sola en cuanto guardas el proyecto de forma explícita, o si decides no
guardar al cerrar la app.

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
| Versiones anteriores por capítulo | 5 |

Si algo excede un límite, la app te avisa antes de generar o guardar — no
te bloquea de escribir de más, pero sí de generar/guardar con esos
excedentes sin antes confirmar o corregir.

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
Solo se guardan las últimas 5 versiones por capítulo; una sexta
regeneración/refinamiento/reducción de repetición descarta la más vieja sin
aviso.

**¿Por qué el modelo se niega a escribir cierto contenido?**
Depende del modelo que elijas, no de esta app — StoryForge Local no impone
ningún filtro de contenido propio, pero algunos modelos tienen su propio
entrenamiento de seguridad. Ver la sección correspondiente en el
[README](README.md).
