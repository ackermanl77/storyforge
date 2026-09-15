# StoryForge Local

App de escritorio para escribir historias de ficcion largas (hasta 10
capitulos de hasta 10,000 palabras cada uno) a partir de un plot, personajes
y un setting que tu escribes. Genera el texto en ingles usando un modelo de
IA que corre **localmente en tu PC**, sin depender de internet ni de una API
externa una vez que tienes el modelo descargado.

## Que incluye

- Interfaz grafica (pestanas: Modelo, Plot, Personajes, Setting, **Esquema**, Capitulos).
- **Flujo "outline-first"**: en la pestana Esquema puedes generar de un jalon
  un beat sheet de todos los capitulos (titulo + eventos clave de cada uno) a
  partir del plot/personajes/setting, editarlo, y luego generar la prosa de
  cada capitulo en la pestana Capitulos siguiendo ese esquema. Esto mejora
  mucho la coherencia de una historia larga frente a improvisar capitulo por
  capitulo.
- Limites de palabras validados: plot ≤ 50,000, personajes ≤ 10,000,
  setting ≤ 10,000, hasta 10 capitulos de hasta 10,000 palabras cada uno.
- Generacion de capitulos por secciones (para poder llegar a objetivos
  largos sin exceder lo que un modelo local puede escribir de un jalon).
- Convenciones de formato automaticas en el texto generado: narracion en
  tercera persona por defecto, pensamientos internos en *cursiva* y primera
  persona, dialogo con comillas.
- Reductor de repeticion de palabras (basado en WordNet, funciona offline
  una vez descargados sus datos).
- Guardar/abrir proyecto (.json) y exportar la historia a Word (.docx) o
  texto plano (.txt).

## Historial de cambios

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

1. Instala Python 3.10 o mas nuevo (marca "Add python.exe to PATH" en el
   instalador de python.org).
2. Descarga/copia esta carpeta completa a tu PC.
3. Descarga un modelo `.gguf` (ver `models/README.txt` para recomendaciones)
   y colocalo dentro de la carpeta `models/`.
4. Genera el ejecutable corriendo `build.bat` (doble clic, o desde una
   terminal `cmd`). Esto instala las dependencias con pip y usa PyInstaller
   para producir `dist/StoryForge/StoryForge.exe`.
5. Copia la carpeta `models/` (con tu modelo adentro) junto al .exe si no
   quedo ahi automaticamente, y ejecuta `StoryForge.exe`.

Por que no viene ya compilado: el .exe tiene que compilarse en Windows (no
puedo generar un ejecutable nativo de Windows desde el entorno Linux donde
yo corro). El paso 4 es una sola linea de comando y tarda 1-3 minutos.

### Uso sin compilar un .exe (para probar mas rapido)

Si solo quieres probarlo sin empaquetarlo:

```
pip install -r requirements.txt
python storyforge.py
```

## Rendimiento / GPU (opcional)

Por defecto, `llama-cpp-python` corre en CPU. Si tu PC tiene una GPU NVIDIA,
puedes instalar una version compilada con soporte CUDA para acelerar mucho
la generacion; consulta la documentacion de `llama-cpp-python` para el
comando de instalacion con CUDA correspondiente a tu version de CUDA, y
ajusta `n_gpu_layers` en `app/engine.py` (`LocalStoryEngine.load`) a un
numero mayor que 0.

## Reductor de repeticion (WordNet)

La primera vez que uses "Reducir repeticion" o "Reporte de repeticion", la
app intenta descargar los datos de NLTK (stopwords y WordNet, ~35 MB en
total) si no los tiene. Esto requiere internet **una sola vez**; despues
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
    project.py     Modelo de datos (plot/personajes/setting/capitulos) y limites
    prompts.py      Plantillas de prompt y guia de estilo
    engine.py        Motor de generacion local (llama-cpp-python)
    repetition.py    Analisis y reduccion de repeticion de palabras
    export.py        Exportacion a .docx / .txt
    gui.py           Interfaz grafica (CustomTkinter)
    main.py          Punto de entrada
  storyforge.py       Script de arranque (usado por PyInstaller)
  storyforge.spec     Especificacion de empaquetado de PyInstaller
  build.bat           Script de una linea para generar el .exe en Windows
  requirements.txt    Dependencias de la app
  models/             Coloca aqui tu modelo .gguf
  tests/              Pruebas automatizadas (unittest, sin dependencias extra)
```

## Pruebas

```
python -m unittest discover -s tests -v
```

Las pruebas de `project.py`, `repetition.py` (rutas sin datos de NLTK) y la
logica del motor de generacion (con un modelo simulado) no requieren
`llama-cpp-python` ni un modelo real instalados.
