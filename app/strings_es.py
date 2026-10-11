"""
Todos los textos visibles de la interfaz en espanol (F8): app/gui.py,
app/ui_*.py y app/task_runner.py los importan como `from . import
strings_es as S` y no llevan textos propios (tests/test_strings_es.py lo
comprueba). Un texto con {campos} se usa con S.NOMBRE.format(campo=...).
Tambien estan aqui las etiquetas visibles de valores que se GUARDAN en los
proyectos.

Fuera de este modulo quedan los mensajes que arma el backend
(app/engine.py, app/project.py, app/gguf.py, app/export.py, p.ej. errores
de carga o advertencias al guardar) y los prompts para el modelo
(app/prompts.py), que no son textos de la interfaz.

Los tipos de escritura y propositos de capitulo se guardan sin acentos
("Dialogo", "Escena climatica"...) desde las primeras versiones: esas claves
no cambian (los proyectos viejos tienen que seguir cargando y los prompts
las usan como clave), pero el usuario ve la version bien escrita.

Glosario elegido para la interfaz: se conservan "Plot", "Setting" y
"Lorebook" (son los nombres de pestana que ya usan la guia y el README, y
terminos habituales en herramientas de escritura con IA); el resto va en
espanol con acentos y tuteo ("puedes", nunca "podes").
"""
from __future__ import annotations

from typing import Dict

from .project import CHAPTER_PURPOSES, WRITING_STYLES

APP_NAME = "StoryForge Local"

STYLE_LABELS: Dict[str, str] = {
    "Narrativa": "Narrativa",
    "Descriptiva": "Descriptiva",
    "Creativa": "Creativa",
    "Dialogo": "Diálogo",
    "Poetica": "Poética",
    "Accion rapida": "Acción rápida",
}

PURPOSE_LABELS: Dict[str, str] = {
    "Apertura": "Apertura",
    "Escena climatica": "Escena climática",
    "Final": "Final",
    "Epilogo": "Epílogo",
}

WRITING_STYLE_DEFAULT_LABEL = "(Por defecto)"
CHAPTER_PURPOSE_DEFAULT_LABEL = "(Capítulo regular)"

CHAPTER_HEADING_LABELS: Dict[str, str] = {
    "Chapter": "Chapter N: título",
    "Capítulo": "Capítulo N: título",
    "": "Solo el título",
}

HISTORY_SOURCE_LABELS: Dict[str, str] = {
    "generate": "generar",
    "continue": "continuar",
    "refine": "refinar",
    "reduce": "reducir repetición",
    "restore": "restaurar versión",
    "rewrite": "reescribir selección",
    "replace": "reemplazar texto",
    "retry": "reintentar",
    "retry-section": "reintentar la última sección",
    "phone-edit": "editar desde el celular",
}

assert set(STYLE_LABELS) == set(WRITING_STYLES)
assert set(PURPOSE_LABELS) == set(CHAPTER_PURPOSES)


def style_label(key: str) -> str:
    return STYLE_LABELS.get(key, WRITING_STYLE_DEFAULT_LABEL) if key else WRITING_STYLE_DEFAULT_LABEL


def style_key(label: str) -> str:
    """Clave guardada para una etiqueta visible (acepta tambien la clave)."""
    if label in STYLE_LABELS:
        return label
    for key, value in STYLE_LABELS.items():
        if value == label:
            return key
    return ""


def purpose_label(key: str) -> str:
    return PURPOSE_LABELS.get(key, CHAPTER_PURPOSE_DEFAULT_LABEL) if key else CHAPTER_PURPOSE_DEFAULT_LABEL


def purpose_key(label: str) -> str:
    if label in PURPOSE_LABELS:
        return label
    for key, value in PURPOSE_LABELS.items():
        if value == label:
            return key
    return ""


def history_source_label(source: str) -> str:
    """"refine: hazlo mas oscuro" -> "refinar: hazlo mas oscuro"."""
    if not source:
        return ""
    kind, _, detail = source.partition(":")
    label = HISTORY_SOURCE_LABELS.get(kind.strip(), kind.strip())
    return f"{label}: {detail.strip()}" if detail.strip() else label


STYLE_OPTIONS = [WRITING_STYLE_DEFAULT_LABEL] + [STYLE_LABELS[k] for k in WRITING_STYLES]
PURPOSE_OPTIONS = [CHAPTER_PURPOSE_DEFAULT_LABEL] + [PURPOSE_LABELS[k] for k in CHAPTER_PURPOSES]

# Formas sin acento (o con voseo) que NO deben aparecer en textos visibles de
# la interfaz -- ver tests/test_strings_es.py.
UNACCENTED_FORMS = [
    r"\bcapitulos?\b", r"\bpestana\b", r"\bningun\b", r"\bproposito\b", r"\bnumero\b",
    r"\bversion\b", r"\breduccion\b", r"\brepeticion\b", r"\bgeneracion\b", r"\bseccion\b",
    r"\binstruccion\b", r"\btitulo\b", r"\bbusqueda\b", r"\bultim[ao]s?\b", r"\bdespues\b",
    r"\btambien\b", r"\baqui\b", r"\bpodes\b", r"\binvalido\b", r"\bmaximo\b", r"\bminimo\b",
    r"\bautomatico\b", r"\bresumenes\b", r"\btodavia\b", r"\bvacio\b", r"\bdialogo\b",
    r"\bepilogo\b", r"\bclimatica\b", r"\bpoetica\b", r"\baccion\b",
]


# ======================================================================
# Textos de la interfaz (F8): todo texto visible de app/gui.py, app/ui_*.py y
# app/task_runner.py vive aqui. Los que llevan {campos} se usan con
# .format(...); se agrupan por el modulo que los usa primero.
# ======================================================================

# ---- app/ui_common.py ----
NO_MODELS_LABEL = "(sin modelos en models/)"
CONTADOR_PALABRAS_VACIO = "0 / {max_words:,} palabras"
IMPORTAR_DESDE_ARCHIVO = "Importar desde archivo..."
EXPANDIR_CON_IA = "Expandir con IA"
CONTADOR_PALABRAS = "{words:,} / {max_words:,} palabras"

# ---- app/gui.py ----
LOG_EN_CONSOLA = "la consola desde la que se inició la app"
NO_INSTALADO = "no instalado"
SI = "sí"
NO_SOLO_CPU = "no (solo CPU)"
NO_DISPONIBLE = "no disponible"
NINGUNO = "ninguno"
ABOUT_VRAM_GB = "{gb:.1f} GB"
ABOUT_PYTHON = "Python {python_version} ({architecture}), {system} {release}"
ABOUT_LLAMA_CPP = "llama-cpp-python: {llama_version}"
ABOUT_GPU = "Soporte de GPU en llama-cpp-python: {gpu}"
ABOUT_VRAM = "VRAM libre (nvidia-smi): {vram}"
ABOUT_MODELO = "Modelo cargado: {model}"
ABOUT_CARPETA_MODELOS = "Carpeta de modelos: {folder}"
ABOUT_DATOS_USUARIO = "Datos de usuario (autoguardado, preferencias): {folder}"
ABOUT_REGISTRO = "Registro de errores: {location}"
ERROR_INESPERADO = (
    "Ocurrió un error inesperado{where}:\n\n{error_type}: {exc}\n\nEl detalle quedó registrado en:\n"
    "{log_location}"
)
NOMBRE_DE_ARCHIVO_SUGERIDO = "historia"
EN_SEGUNDO_PLANO = " en segundo plano"
LA_CARPETA_DE_REGISTROS_ES = "La carpeta de registros es:\n{folder}\n\n({exc})"
ACERCA_DE = "Acerca de {APP_TITLE}"
TODAVIA_NO_SE_ENVIO_NINGUN = "Todavía no se envió ningún prompt al modelo en esta sesión."
OPERACION_TOKENS_DE_PROMPT_RESERVADOS = (
    "Operación: {operation}  |  {prompt_tokens:,} tokens de prompt + {max_tokens:,} reservados "
    "de {n_ctx:,} (nivel de presupuesto {budget_level}/3)\nSemilla: {seed}   Muestreo: "
    "{sampling}"
)
PROMPT_ENVIADO_AL_MODELO = "Prompt enviado al modelo"
TAB_MODELO = "Modelo"
TAB_PLOT = "Plot"
TAB_PERSONAJES = "Personajes"
TAB_SETTING = "Setting"
TAB_LOREBOOK = "Lorebook"
TAB_ESQUEMA = "Esquema"
TAB_CAPITULOS = "Capítulos"
SE_ENCONTRO_UNA_COPIA_DE = (
    "Se encontró una copia de autoguardado de una sesión anterior que no se guardó (cierre "
    "inesperado o crash). ¿Recuperar ese proyecto ahora?"
)
NO_SE_PUDO_ESCRIBIR_EL = (
    "No se pudo escribir el autoguardado en:\n{autosave_path}\n\n{exc}\n\nLa app sigue normalmente, "
    "pero guarda el proyecto a mano de vez en cuando. (Este aviso no se repite en esta sesión.)"
)
HAY_CAMBIOS_SIN_GUARDAR_GUARDARLOS = "Hay cambios sin guardar. ¿Guardarlos antes de {action}?"
GENERACION_EN_CURSO_CAMBIAR_PROYECTO = (
    "Hay una generación en curso. Espera a que termine antes de cambiar de proyecto."
)
CREAR_UN_PROYECTO_NUEVO = "crear un proyecto nuevo"
ABRIR_OTRO_PROYECTO = "abrir otro proyecto"
ABRIR_PROYECTO = "Abrir proyecto"
PROYECTO_STORYFORGE = "Proyecto StoryForge"
TODOS_LOS_ARCHIVOS = "Todos los archivos"
NO_SE_PUDO_ABRIR_EL = (
    "No se pudo abrir el proyecto:\n{exc}\n\nHay una copia de seguridad de la versión anterior "
    "({backup}). ¿Abrir esa copia?"
)
NO_SE_PUDO_ABRIR_PROYECTO = "No se pudo abrir el proyecto: {exc}"
TAMPOCO_SE_PUDO_ABRIR_LA = "Tampoco se pudo abrir la copia de seguridad: {exc2}"
SE_ABRIO_LA_COPIA_DE = "Se abrió la copia de seguridad. Guárdala con \"Guardar proyecto como\"."
GENERACION_EN_CURSO_SALIR = (
    "Hay una generación en curso. Si sales ahora se perderá el progreso no guardado de ese "
    "capítulo/esquema. ¿Salir de todas formas?"
)
GUARDAR_EL_PROYECTO_ANTES_DE = "¿Guardar el proyecto antes de salir?"
GUARDAR_PROYECTO_COMO = "Guardar proyecto como"
SE_GUARDARA_CON_ESTAS_ADVERTENCIAS = "Se guardará con estas advertencias:\n\n"
NO_SE_PUDO_GUARDAR = "No se pudo guardar el proyecto en:\n{path}\n\n{exc}"
PROYECTO_GUARDADO = "Proyecto guardado."
EXPORTADO_A = "Exportado a {path}"
ERROR_AL_EXPORTAR = "Error al exportar: {exc}"
EXPORTAR_A_WORD = "Exportar a Word"
WORD = "Word"
EXPORTAR_A_TXT = "Exportar a TXT"
TIPO_TEXTO = "Texto"
EXPORTAR_A_MARKDOWN = "Exportar a Markdown"
MARKDOWN = "Markdown"
EXPORTAR_A_EPUB = "Exportar a EPUB"
EPUB = "EPUB"

# ---- app/ui_menu.py ----
NUEVO_PROYECTO = "Nuevo proyecto"
CTRL_N = "Ctrl+N"
ABRIR_PROYECTO_MENU = "Abrir proyecto..."
CTRL_O = "Ctrl+O"
GUARDAR_PROYECTO = "Guardar proyecto"
CTRL_S = "Ctrl+S"
GUARDAR_PROYECTO_COMO_MENU = "Guardar proyecto como..."
CTRL_SHIFT_S = "Ctrl+Shift+S"
EXPORTAR_A_WORD_DOCX = "Exportar a Word (.docx)"
EXPORTAR_A_MARKDOWN_MD = "Exportar a Markdown (.md)"
PREFERENCIAS_MENU = "Preferencias..."
SALIR = "Salir"
MENU_ARCHIVO = "Archivo"
BUSCAR_EN_EL_CAPITULO = "Buscar en el capítulo"
CTRL_F = "Ctrl+F"
BUSCAR_EN_PROYECTO_MENU = "Buscar en todo el proyecto..."
CTRL_SHIFT_F = "Ctrl+Shift+F"
MENU_EDITAR = "Editar"
MODO_ENFOQUE = "Modo enfoque"
F11 = "F11"
VER_EL_ULTIMO_PROMPT_ENVIADO = "Ver el último prompt enviado"
MENU_VER = "Ver"
ACERCA_DE_STORYFORGE = "Acerca de StoryForge"
ABRIR_CARPETA_DE_REGISTROS = "Abrir carpeta de registros"
MENU_AYUDA = "Ayuda"

# ---- app/ui_model_tab.py ----
COLOCA_UN_ARCHIVO_DE_MODELO = (
    "Coloca un archivo de modelo .gguf en la carpeta 'models/' junto al programa (o en la "
    "carpeta de modelos adicional de Archivo > Preferencias) y cárgalo aquí. Ver "
    "models/README.txt para recomendaciones según tu GPU."
)
ACTUALIZAR_LISTA = "Actualizar lista"
ELEGIR_ARCHIVO = "Elegir archivo..."
CARGAR_MODELO = "Cargar modelo"
CONTEXTO_N_CTX_0_EL = "Contexto (n_ctx, 0 = el del modelo):"
CAPAS_EN_GPU_1_TODAS = "Capas en GPU (-1 = todas):"
CAPAS_EN_GPU_0_SOLO = "Capas en GPU (0 = solo CPU):"
ESTIMAR_VRAM = "Estimar VRAM"
HILOS_CPU_VACIO_AUTOMATICO = "Hilos CPU (vacío = automático):"
GPU_DETECTADA_SE_USARA_PARA = "GPU detectada: se usará para acelerar la generación."
SIN_SOPORTE_DE_GPU_SOLO = "Sin soporte de GPU (solo CPU)."
FLASH_ATTENTION = "Flash attention"
LOTE_N_BATCH = "Lote (n_batch):"
N_UBATCH_ETIQUETA = "n_ubatch:"
AUTO_PLACEHOLDER = "auto"
CACHE_KV = "Caché KV:"
FORMATO_DE_CHAT = "Formato de chat:"
AUTO_USA_LA_PLANTILLA_DEL = (
    "Auto usa la plantilla del GGUF o la deduce del vocabulario. Usa \"Sin plantilla\" para "
    "modelos base."
)
UN_N_CTX_MAYOR_PERMITE = (
    "Un n_ctx mayor permite más contexto por llamada pero usa más memoria; no pases del "
    "contexto con el que se entrenó el modelo. Con GPU: flash attention + lote 1024-2048 "
    "aceleran el procesamiento del prompt, y la caché KV q8_0 usa la mitad de memoria "
    "(requiere flash attention). En CPU deja n_gpu_layers en 0."
)
NINGUN_MODELO_CARGADO = "Ningún modelo cargado."
MUESTREO_DE_LA_PROSA_SE = "Muestreo de la prosa (se guarda con el proyecto)"
PRESET = "Preset:"
TEMPERATURA = "Temperatura"
PENALIZ_REPETICION = "Penaliz. repetición"
PRESENCIA = "Presencia"
FRECUENCIA = "Frecuencia"
SEMILLA_VACIO_ALEATORIA = "Semilla (vacío = aleatoria):"
USAR_LA_ULTIMA = "Usar la última"
TODAVIA_NO_SE_GENERO_NADA = "Todavía no se generó nada en esta sesión."
ULTIMA_SEMILLA_USADA = "Última semilla usada: {seed}"
ELIGE_PRIMERO_UN_MODELO_GGUF = "Elige primero un modelo .gguf existente."
FORMATO_DE_CHAT_ACTUAL = "Formato de chat: {description}"
ETIQUETA_AUTO = "{label} (auto)"
SELECCIONA_UN_MODELO_GGUF = "Selecciona un modelo .gguf"
GGUF = "GGUF"
ESTE_PROYECTO_SE_ESCRIBIO_CON = (
    "Este proyecto se escribió con el modelo \"{stored}\", que no se encontró en la carpeta de "
    "modelos. Elige otro modelo o copia ese archivo a models/."
)
MODELO_DEL_PROYECTO_SELECCIONADO_PULSA = "Modelo del proyecto seleccionado: {path}. Pulsa \"Cargar modelo\"."
CONTEXTO_N_CTX_INVALIDO_DEBE = "Contexto (n_ctx) inválido: debe ser un entero >= 0 (0 = el del modelo)."
CAPAS_EN_GPU_N_GPU = "Capas en GPU (n_gpu_layers) inválido: debe ser un entero >= 0, o -1 para todas."
HILOS_CPU_N_THREADS_INVALIDO = "Hilos CPU (n_threads) inválido: debe ser un entero mayor a 0, o vacío."
N_BATCH_N_UBATCH_INVALIDO = "n_batch / n_ubatch inválido: un entero mayor a 0, o vacío."
LA_CACHE_KV_REQUIERE_FLASH = "La caché KV {kv} requiere flash attention: actívala o usa f16."
ESPERA_ANTES_DE_CARGAR_MODELO = "Espera a que termine la generación en curso antes de cargar otro modelo."
SELECCIONA_UN_ARCHIVO_GGUF_VALIDO = "Selecciona un archivo .gguf válido."
PEDISTE_N_CTX_PERO_ESTE = (
    "Pediste n_ctx={n_ctx:,}, pero este modelo se entrenó con {trained:,} tokens de contexto: "
    "por encima de eso la calidad suele degradarse mucho. ¿Cargar igual?"
)
CARGANDO_MODELO_ESTADO = "Cargando {path}..."
FLASH_ATTENTION_DETALLE = "flash attention"
CACHE_KV_DETALLE = "caché KV {kv_cache_type}"
MODELO_CARGADO_N_CTX_N = (
    "Modelo cargado: {path} (n_ctx={actual_ctx}, n_gpu_layers={n_gpu_layers}{extra}; formato "
    "de chat: {chat_format})"
)
ERROR_GENERICO = "Error: {exc}"
CARGANDO_MODELO_TAREA = "Cargando {path}"

# ---- app/ui_story_tabs.py ----
TITULO_DE_LA_HISTORIA = "Título de la historia:"
AUTOR = "Autor:"
ENCABEZADO_AL_EXPORTAR = "Encabezado al exportar:"
VERSIONES_POR_CAPITULO = "Versiones guardadas por capítulo:"
NOTA_DEL_AUTOR_TODA_LA = "Nota del autor (toda la historia):"
INSTRUCCION_CORTA_QUE_SE_APLICA = (
    "Instrucción corta que se aplica a cada sección (máximo {MAX_AUTHOR_NOTE_WORDS} palabras), "
    "p.ej. \"tono sombrío, frases cortas\""
)
STORY_PLOT_IDEA_DE_LA = "Story Plot (idea de la historia)"
PERSONAJES_DESCRIPCION_PERSONALIDAD_RELACIONES = "Personajes (descripción, personalidad, relaciones)"
SETTING_DONDE_Y_CUANDO_OCURRE = "Setting (dónde y cuándo ocurre la historia)"
IMPORTAR_TEXTO_DESDE_ARCHIVO = "Importar texto desde archivo"
NO_SE_PUDO_LEER_ARCHIVO = "No se pudo leer el archivo: {exc}"
ESTO_REEMPLAZARA_EL_CONTENIDO_ACTUAL = "Esto reemplazará el contenido actual de este campo. ¿Continuar?"
PRIMERO_CARGA_UN_MODELO_LOCAL = "Primero carga un modelo local (.gguf) en la pestaña 'Modelo'."
YA_HAY_GENERACION_EN_CURSO = "Ya hay una generación en curso. Espera a que termine antes de iniciar otra."
ESCRIBE_UNA_IDEA_CORTA_EN = "Escribe una idea corta en {field_label} primero."
YA_TIENE_BASTANTE_TEXTO_ESCRITO = (
    "{field_label} ya tiene bastante texto escrito. Expandir con IA lo reemplaza por completo "
    "(Ctrl+Z lo recupera). ¿Continuar?"
)
EXPANDIR = "Expandir {field_label}"
ERROR_EXPANDIENDO_EL_CAMPO = "Error expandiendo el campo: "

# ---- app/ui_lorebook_tab.py ----
NOMBRE = "Nombre:"
P_EJ_ELENA_VASQUEZ = "p.ej. Elena Vasquez"
ELIMINAR = "Eliminar"
PALABRAS_CLAVE_SEPARADAS_POR_COMA = "Palabras clave (separadas por coma):"
P_EJ_ELENA_LA_REINA = "p.ej. Elena, la reina, Su Majestad"
ACTIVA = "Activa"
INCLUIR_SIEMPRE = "Incluir siempre"
PRIORIDAD = "Prioridad:"
TEXTO_ETIQUETA = "Texto:"
USADA_EN_LA_ULTIMA_GENERACION = "✓ usada en la última generación"
ENTRADA = "entrada {number}"
LOREBOOK_ENTRADA = "Lorebook: {name}"
ELIMINAR_LA_ENTRADA_DE_LOREBOOK = "¿Eliminar la entrada de lorebook '{label}'?"
EL_LOREBOOK_GUARDA_PERSONAJES_SECUNDARIOS = (
    "El Lorebook guarda personajes secundarios, lugares u objetos que no necesitas repetir en "
    "Personajes/Setting. Cada entrada solo se agrega al prompt cuando alguna de sus palabras "
    "clave aparece en el esquema del capítulo, en el resumen de los capítulos anteriores o en "
    "lo último que se escribió -- así puedes mantener un elenco o mundo mucho más grande sin "
    "agotar el contexto del modelo. \"Incluir siempre\" la agrega en cada capítulo; con muchas "
    "coincidencias entran primero las de mayor prioridad."
)
AGREGAR_ENTRADA = "+ Agregar entrada"
MAXIMO_ENTRADAS = "(máximo {MAX_LORE_ENTRIES} entradas)"
BUSCAR_ETIQUETA = "Buscar:"
FILTRAR_POR_NOMBRE_O_PALABRA = "Filtrar por nombre o palabra clave..."
YA_HAY_ENTRADAS_EL_MAXIMO = "Ya hay {MAX_LORE_ENTRIES} entradas (el máximo)."
AUN_NO_HAY_ENTRADAS_DE = "Aún no hay entradas de lorebook. Agrega una arriba."
NINGUNA_ENTRADA_COINCIDE_CON_LA = "Ninguna entrada coincide con la búsqueda."

# ---- app/ui_outline_tab.py ----
CAPITULO_N = "Capítulo {number}"
CAPITULO_N_TITULO = "Capítulo {number}: {title}"
CONTADOR_PALABRAS_ESQUEMA = "{words:,} / {MAX_OUTLINE_WORDS_PER_CHAPTER:,} palabras"
GENERA_PRIMERO_UN_ESQUEMA_BEAT = (
    "Genera primero un esquema (beat sheet) de todos los capítulos a partir del plot, "
    "personajes y setting. Escribir la historia siguiendo un esquema acordado de antemano "
    "ayuda mucho a que se mantenga consistente de principio a fin. Puedes editar el resultado "
    "aquí antes de generar la prosa en la pestaña 'Capítulos'."
)
NUMERO_DE_CAPITULOS = "Número de capítulos:"
TIPO_DE_ESCRITURA = "Tipo de escritura:"
GENERAR_ESQUEMA_COMPLETO = "Generar esquema completo"
COMPLETAR_CAPITULOS_FALTANTES = "Completar capítulos faltantes"
CORRIGE_ANTES_DE_GENERAR_EL = "Corrige antes de generar el esquema:\n\n"
YA_HAY_GENERACION_EN_CURSO_ESQUEMA = (
    "Ya hay una generación en curso (un capítulo u otra operación). Espera a que termine."
)
NUMERO_DE_CAPITULOS_INVALIDO = "Número de capítulos inválido."
ESTO_REEMPLAZARA_EL_TITULO_Y = (
    "Esto reemplazará el título y esquema de los capítulos existentes (la prosa ya generada de "
    "cada capítulo se conserva). ¿Continuar?"
)
GENERANDO_ESQUEMA = "Generando esquema..."
ESQUEMA_DETENIDO_NO_SE_CAMBIO = "Esquema detenido: no se cambió nada."
ERROR_GENERANDO_EL_ESQUEMA = "Error generando el esquema: "
LA_RESPUESTA_DEL_MODELO_SE = " (la respuesta del modelo se cortó por largo)"
ESQUEMA_INCOMPLETO_DE_CAPITULOS_USA = (
    "Esquema incompleto: {have} de {wanted} capítulos{cause}. Usa \"Completar capítulos "
    "faltantes\", genera de nuevo o complétalos a mano."
)
ESQUEMA_GENERADO_CAPITULOS = "Esquema generado: {have} capítulos."
YA_HAY_GENERACION_EN_CURSO_CORTO = "Ya hay una generación en curso. Espera a que termine."
COMPLETANDO_EL_ESQUEMA = "Completando el esquema..."
COMPLETAR_ESQUEMA = "Completar esquema"
ERROR_COMPLETANDO_EL_ESQUEMA = "Error completando el esquema: "
NO_SE_MODIFICO_EL_ESQUEMA = (
    "{exc}\n\nNo se modificó el esquema. Genera de nuevo (o prueba otro \"Formato de chat\" en la "
    "pestaña Modelo).\n\nRespuesta del modelo:\n{snippet}"
)
AUN_NO_HAY_CAPITULOS_GENERA = (
    "Aún no hay capítulos. Genera un esquema completo arriba, o agrega capítulos manualmente "
    "en la pestaña 'Capítulos'."
)

# ---- app/ui_chapters_tab.py ----
AGREGAR_CAPITULO = "+ Agregar capítulo"
MAXIMO_CAPITULOS = "(máximo {MAX_CHAPTERS} capítulos)"
MODO_ENFOQUE_F11 = "Modo enfoque (F11)"
SALIR_DEL_MODO_ENFOQUE = "Salir del modo enfoque"
YA_HAY_CAPITULOS_EL_MAXIMO = "Ya hay {MAX_CHAPTERS} capítulos (el máximo)."
AUN_NO_HAY_CAPITULOS_AGREGA = "Aún no hay capítulos. Agrega uno arriba o genera un esquema en la pestaña 'Esquema'."
SIN_CAPITULOS = "Sin capítulos."
CAPITULO_BARRA_LATERAL = "{number}. {title}\n{words:,} / {target_words:,} palabras"
ESPERA_GENERACION_EN_CURSO = "Espera a que termine la generación en curso."

# ---- app/ui_chapter_editor.py ----
TITULO_DEL_CAPITULO = "Título del capítulo"
PALABRAS_OBJETIVO = "Palabras objetivo:"
PROPOSITO = "Propósito:"
NOTA_DEL_AUTOR = "Nota del autor:"
INSTRUCCION_CORTA_QUE_EL_MODELO = (
    "Instrucción corta que el modelo lee justo antes de escribir (p.ej. \"Elena oculta que está "
    "herida\")"
)
GENERAR = "Generar"
CONTINUAR = "Continuar"
DESDE_EL_CURSOR = "Desde el cursor"
REINTENTAR = "Reintentar"
REINTENTAR_SECCION = "Últ. sección"
CANCELAR = "Cancelar"
VERSIONES_ANTERIORES_0 = "Versiones anteriores (0)"
MAS_HERRAMIENTAS = "Más herramientas ▾"
REDUCIR_REPETICION = "Reducir repetición"
REPORTE_DE_REPETICION = "Reporte de repetición"
BUSCAR_Y_REEMPLAZAR_CTRL_F = "Buscar y reemplazar (Ctrl+F)"
ELIMINAR_CAPITULO = "Eliminar capítulo"
REEMPLAZAR_ETIQUETA = "Reemplazar:"
REEMPLAZAR = "Reemplazar"
REEMPLAZAR_TODO = "Reemplazar todo"
CERRAR = "Cerrar"
INSTRUCCION_DE_REFINAMIENTO_EJ_HAZLO = (
    "Instrucción de refinamiento (ej: hazlo más oscuro, acorta el diálogo del final)"
)
APLICAR_REFINAMIENTO = "Aplicar refinamiento"
MOSTRAR_RESUMEN = "Mostrar resumen"
PROMPT_PROPIO = "Prompt propio"
PROMPT_PROPIO_ACTIVO = "Prompt propio ●"
INSERTAR_PLANTILLA = "Insertar plantilla"
PROMPT_PROPIO_AYUDA = (
    "Si escribes algo aquí, este capítulo se genera SOLO con este texto: StoryForge no agrega el plot, "
    "los personajes, el setting, el esquema, los resúmenes ni sus reglas de estilo, y el propósito y la "
    "nota del autor de este capítulo se ignoran. Puedes traerlos donde quieras con {plot}, {personajes}, "
    "{setting}, {esquema}, {anterior} (lo que pasó antes), {título}, {capítulo}, {palabras} y {nota_autor}. "
    "Déjalo vacío para usar el prompt automático."
)
REEMPLAZAR_PROMPT_CON_PLANTILLA = "¿Reemplazar el prompt propio de este capítulo por la plantilla?"
REGENERAR_RESUMEN = "Regenerar resumen"
OCULTAR_RESUMEN = "Ocultar resumen"
MENOS_HERRAMIENTAS = "Menos herramientas ▴"
RESUMEN_AL_DIA = "Resumen al día"
RESUMEN_DESACTUALIZADO = "Resumen desactualizado"
SIN_RESUMEN = "Sin resumen"
VERSIONES_ANTERIORES = "Versiones anteriores ({count})"
CONTADOR_PALABRAS_CAPITULO = "{words:,} / {MAX_WORDS_PER_CHAPTER:,} palabras (objetivo {target_words:,})"
CANCELANDO_SE_DETENDRA_EN_BREVE = "Cancelando... se detendrá en breve."
YA_HAY_GENERACION_EN_CURSO_CAPITULO = (
    "Ya hay una generación en curso (otro capítulo, el esquema, o cargando un modelo). Espera "
    "a que termine antes de iniciar otra."
)
EL_RESUMEN_DE_LOS_CAPITULOS = (
    "El resumen de los capítulos {numbers} falta o está desactualizado (el texto cambió "
    "después de resumirlo). Esos resúmenes son la memoria que recibe este capítulo.\n\n"
    "¿Regenerarlos antes de generar? (No = generar igual, con los resúmenes actuales)"
)
CORRIGE_ANTES_DE_GENERAR = "Corrige antes de generar:\n\n"
EL_CAPITULO_YA_TIENE_TEXTO = (
    "El capítulo {number} ya tiene texto generado. Generar de nuevo reemplazará ese contenido "
    "(la versión actual se guarda en \"Versiones anteriores\", así que es recuperable). Para "
    "seguir escribiendo sin borrar nada usa \"Continuar\". ¿Regenerar desde cero?"
)
SE_CONTINUARA_DESDE_EL_CURSOR = (
    "Se continuará desde el cursor: las {words:,} palabras que hay después del cursor se "
    "reemplazarán por texto nuevo (la versión actual se guarda en \"Versiones anteriores\"). "
    "¿Continuar?"
)
CONTINUANDO = "Continuando"
GENERANDO = "Generando"
ESTO_PUEDE_TARDAR_VARIOS_MINUTOS = "{mode}... esto puede tardar varios minutos en CPU."
PROGRESO_PALABRAS = "{mode}... {words:,} / {target:,} palabras"
LISTO = "Listo."
REGENERANDO_EL_RESUMEN_DEL_CAPITULO = "Regenerando el resumen del capítulo {number}..."
GENERANDO_RESUMEN_PARA_CONTINUIDAD_ENTRE = "Generando resumen para continuidad entre capítulos..."
CANCELADO_ANTES_DEL_RESUMEN_USA = "Cancelado antes del resumen. Usa \"Regenerar resumen\"."
LISTO_PERO_NO_SE_PUDO = "Listo, pero no se pudo generar el resumen (ver el registro). Usa \"Regenerar resumen\"."
CANCELADO_PUEDES_SEGUIR_CON_CONTINUAR = "Cancelado. Puedes seguir con \"Continuar\"."
LISTO_SEMILLA = "Listo (semilla {seed})."
ERROR_GENERANDO_CAPITULO = "Error generando capítulo: "
SIN_TEXTO_PARA_RESUMIR = "Este capítulo todavía no tiene texto para resumir."
GENERANDO_RESUMEN = "Generando resumen..."
RESUMEN_ACTUALIZADO = "Resumen actualizado."
RESUMEN_CANCELADO = "Resumen cancelado."
NO_SE_PUDO_GENERAR_RESUMEN = "No se pudo generar el resumen: {exc}"
RESUMEN = "Resumen"
REPETICION_CAPITULO = "Repetición - Capítulo {number}"
ELIMINAR_EL_CAPITULO = "¿Eliminar el capítulo {number}?"
SIN_TEXTO_PARA_REFINAR = "Este capítulo todavía no tiene contenido para refinar. Genéralo primero."
ESCRIBE_UNA_INSTRUCCION_DE_REFINAMIENTO = (
    "Escribe una instrucción de refinamiento (por ejemplo: \"hazlo más oscuro\")."
)
REFINANDO_CAPITULO_VERAS_UNA_VISTA = "Refinando capítulo... (verás una vista previa antes de aplicar nada)"
REFINANDO_LA_PARTE_DE = "Refinando la parte {part} de {total}..."
REVISA_LA_VISTA_PREVIA_ACEPTAR = "Revisa la vista previa: Aceptar aplica el cambio."
REFINAR_CAPITULO_INSTRUCCION = "Refinar capítulo {number}: {instruction}"
REFINAMIENTO_DESCARTADO = "Refinamiento descartado."
REFINAMIENTO_CANCELADO_EL_CAPITULO_NO = "Refinamiento cancelado: el capítulo no cambió."
REFINAR_CAPITULO_N = "Refinar capítulo {number}"
ERROR_REFINANDO_EL_CAPITULO = "Error refinando el capítulo: "
CAMBIO_APLICADO_LA_VERSION_ANTERIOR = "Cambio aplicado (la versión anterior está en \"Versiones anteriores\")."
SELECCION = "{label} selección"
REESCRIBIR_SELECCION_CON_INSTRUCCION = "Reescribir selección con instrucción..."
SELECCIONA_PRIMERO_EL_FRAGMENTO_DEL = "Selecciona primero el fragmento del capítulo a reescribir."
INSTRUCCION_PARA_ESTE_FRAGMENTO = "Instrucción para este fragmento:"
REESCRIBIR_SELECCION = "Reescribir selección"
TRABAJANDO_SOBRE_LA_SELECCION = "{mode}: trabajando sobre la selección..."
SELECCION_CAPITULO = "{label} selección - Capítulo {number}"
ERROR_REESCRIBIENDO_LA_SELECCION = "Error reescribiendo la selección: "
COINCIDENCIAS = "{count} coincidencias"
REEMPLAZOS = "{count} reemplazos"
ESTE_CAPITULO_NO_TIENE_VERSIONES = "Este capítulo no tiene versiones anteriores guardadas todavía."
VERSIONES_ANTERIORES_CAPITULO = "Versiones anteriores - Capítulo {number}"
VERSION_DE_PALABRAS = "Versión {number} de {total} ({words} palabras)"
VERSION_ETIQUETA = "Versión:"
RESTAURAR_ESTA_VERSION = "Restaurar esta versión"
COMPARAR_CON_LA_ACTUAL = "Comparar con la actual"
GUARDADA_ANTES_DE = "Guardada antes de: {source}"
VERSION_ANTERIOR_IZQUIERDA_FRENTE_A = "Versión anterior (izquierda) frente a la actual (derecha)"
ESTO_REEMPLAZA_EL_CONTENIDO_ACTUAL = (
    "Esto reemplaza el contenido actual del capítulo por esta versión anterior. El contenido "
    "actual también se guarda como versión antes de restaurar, así que esto es reversible. "
    "¿Continuar?"
)

# ---- app/ui_dialogs.py ----
ANTES = "Antes"
DESPUES_PALABRAS = "Después  (+{added} / -{removed} palabras)"
DESCARTAR = "Descartar"
ACEPTAR_Y_SEGUIR_REFINANDO = "Aceptar y seguir refinando"
ACEPTAR = "Aceptar"
COPIAR = "Copiar"
CAPITULO = "Capítulo"
ESQUEMA_N_TITULO = "Esquema {number}: {title}"
RESUMEN_N_TITULO = "Resumen {number}: {title}"
BUSCAR_EN_PROYECTO_TITULO = "Buscar en todo el proyecto"
BUSCAR = "Buscar"
REEMPLAZAR_CON = "Reemplazar con:"
DISTINGUIR_MAYUSCULAS = "Distinguir mayúsculas"
PALABRA_COMPLETA = "Palabra completa"
SE_MUESTRAN_300 = " (se muestran 300)"
RESULTADOS = "{count} resultados{more}"
PREFERENCIAS = "Preferencias"
TEMA = "Tema:"
OSCURO = "Oscuro"
CLARO = "Claro"
SISTEMA = "Sistema"
ESCALA_DE_LA_INTERFAZ = "Escala de la interfaz:"
FUENTE_DEL_EDITOR_VACIO_POR = "Fuente del editor (vacío = por defecto):"
TAMANO_DE_FUENTE_DEL_EDITOR = "Tamaño de fuente del editor:"
INTERLINEADO_PIXELES = "Interlineado (píxeles):"
CARPETA_DE_MODELOS_ADICIONAL = "Carpeta de modelos adicional:"
CONSEJO_GUARDA_LOS_MODELOS_GGUF = (
    "Consejo: guarda los modelos .gguf fuera de OneDrive (p.ej. C:\\Modelos) para que no se "
    "sincronicen ni queden \"solo en línea\"."
)
GUARDAR = "Guardar"

# ---- app/ui_status.py ----
TRABAJANDO = "Trabajando"
DURACION_HORAS = "{hours}h {minutes:02d}m"
TOK_S = "{tps:.1f} tok/s"
PROMPT_S = "prompt {prompt_eval_seconds:.1f} s"
ESTADO_PALABRAS = "{words_written:,}/{target_words:,} palabras"
ETA = "ETA {eta}"
PARTE = "parte {part}/{total_parts}"
SEMILLA = "semilla {seed}"
CONTEXTO_VACIO = "Contexto: --"
NIVEL_3 = ", nivel {budget_level}/3"
CONTEXTO_MEDIDOR = "Contexto {percent:.0f}% ({prompt_tokens:,} + {max_tokens:,} / {n_ctx:,}{level})"
VER_PROMPT = "Ver prompt"
DETENER = "Detener"
LISTO_TIEMPO = "Listo ({elapsed})."
DETENIDO = "Detenido ({elapsed})."
TERMINO_CON_ERROR = "Terminó con error ({elapsed})."
TOK_S_FINAL = "  {tokens_per_second:.1f} tok/s"
PALABRAS_EN_CAPITULOS = "{words:,} palabras en {chapters} capítulos"

# ---- app/task_runner.py ----
EL_CONTEXTO_ES_DEMASIADO_GRANDE = "El contexto es demasiado grande para este modelo:\n\n{exc}"


# --- Mensajes del backend (engine, project, gguf, export, prompts) que llegan a la UI ---
ARCHIVO_NO_ES_PROYECTO = 'El archivo no contiene un proyecto de StoryForge (se esperaba un objeto JSON).'
CACHE_KV_DESCONOCIDA = 'Tipo de caché KV desconocido: {kv_cache_type}'
CACHE_KV_REQUIERE_FLASH_ATTENTION = 'La caché KV {kv_cache_type} requiere flash attention: actívala o usa f16.'
CAPITULO_DEMASIADO_LARGO = 'Capítulo {number}: el contenido tiene {words:,} palabras, más que el máximo recomendado ({maximum:,}).'
CAPITULO_INVALIDO = 'capítulo inválido'
CAPITULO_NO_CABE_PARA_REFINAR = 'El capítulo no cabe completo en la ventana de contexto del modelo ({n_ctx:,} tokens) y ni siquiera hay espacio para refinarlo por partes. Carga el modelo con un n_ctx mayor en la pestaña Modelo.'
CONTEXTO_NO_CABE = 'El contexto necesario ({prompt_tokens:,} tokens) no cabe en la ventana de contexto del modelo ({n_ctx:,} tokens) junto con el espacio reservado para la respuesta ({max_tokens:,} tokens).'
CONTEXTO_NO_CABE_NI_REDUCIDO = 'Incluso reduciendo al mínimo el contexto (plot, personajes, setting y resumen previo), el prompt sigue sin caber en la ventana de contexto de este modelo. Prueba con un plot, personajes o setting más cortos, un objetivo de palabras menor, o carga el modelo con un n_ctx mayor si tu hardware lo permite.'
DEBE_SER_ENTERO_POSITIVO = '{name} debe ser un entero mayor a 0.'
ENTRADA_LOREBOOK_INVALIDA = 'entrada de lorebook inválida'
ESQUEMA_FORMATO_INESPERADO = 'La respuesta del modelo no tiene el formato de esquema esperado ("Chapter 1: <título>" seguido de sus eventos).'
FALTA_LLAMA_CPP = "El paquete 'llama-cpp-python' no está instalado. Instala las dependencias con: pip install -r requirements.txt"
FALTA_PYTHON_DOCX = "El paquete 'python-docx' no está instalado. Instala las dependencias con: pip install -r requirements.txt"
GGUF_CABECERA_INVALIDA = 'Cabecera GGUF inválida.'
GGUF_CADENA_INVALIDA = 'Cadena GGUF de tamaño inválido.'
GGUF_FIRMA_INVALIDA = 'El archivo no es un modelo GGUF (firma inválida).'
GGUF_TIPO_DESCONOCIDO = 'Tipo de valor GGUF desconocido: {value_type}'
GGUF_TRUNCADO = 'El archivo GGUF está truncado (terminó antes de lo esperado).'
LLAMA_CPP_SIN_LIBRERIA = 'llama-cpp-python está instalado, pero no se pudo cargar su librería nativa (llama.dll o alguna de las DLLs que necesita). Si instalaste la versión con CUDA, instala también las DLLs de runtime (pip install nvidia-cuda-runtime nvidia-cublas, ver README > Rendimiento / GPU) o vuelve a la versión solo-CPU.\n\nDetalle: {exc}'
MAXIMO_DE_CAPITULOS = 'No se pueden tener más de {maximum} capítulos.'
MAXIMO_DE_ENTRADAS_LOREBOOK = 'No se pueden tener más de {maximum} entradas de lorebook.'
MODELO_FALTAN_PARTES = 'Este modelo está partido en varios archivos y faltan las partes {parts} en la carpeta. Descarga todas las partes y ponlas juntas; se carga la parte 00001.'
MODELO_NO_ENCONTRADO = 'No se encontró el modelo en: {model_path}'
NO_HAY_TEXTO_SELECCIONADO = 'No hay texto seleccionado.'
NO_SE_PUDO_GENERAR_SECCION = 'No fue posible generar esta sección del capítulo: {exc}'
N_CTX_NEGATIVO = 'n_ctx no puede ser negativo (0 = el contexto entrenado del modelo).'
REFINAR_PARTE_VACIA = 'El modelo devolvió un texto vacío al refinar la parte {part} de {total} del capítulo. No se modificó el capítulo; inténtalo de nuevo.'
NO_HAY_MODELO_CARGADO = 'No hay un modelo cargado. Carga un archivo .gguf primero.'
OPERACION_DETENIDA_POR_EL_USUARIO = 'Operación detenida por el usuario.'
# Motivo por el que una entrada del Lorebook entro al prompt (prompts.LoreMatch.reason_es).
LORE_MOTIVO_SIEMPRE = 'siempre incluida'
LORE_MOTIVO_VIA = '"{keyword}" (mencionada en la entrada "{via}")'
LORE_MOTIVO_KEYWORD = '"{keyword}"'


# ---- app/web_server.py (StoryForge en el celular) ----
WEB_TAREA_CARGAR_MODELO = "Cargando {name}"
WEB_TAREA_ESQUEMA = "Esquema"
WEB_TAREA_CAPITULO = "Capítulo {number}"
WEB_TAREA_RESUMEN = "Resumen del capítulo {number}"
WEB_MODELO_CARGADO = "Modelo cargado: {name} (contexto {n_ctx:,} tokens)."
WEB_ESQUEMA_LISTO = "Esquema generado: {have} de {wanted} capítulos."
WEB_TAREA_DETENIDA = "Detenido: no se cambió nada."
WEB_RESUMEN_LISTO = "Resumen actualizado."
WEB_HAY_UNA_TAREA = "Ya hay una tarea en curso ({label}). Espera a que termine o detenla."
WEB_SIN_PROYECTO = "No hay un proyecto abierto. Abre o crea uno en Proyectos."
WEB_PROYECTO_NO_ENCONTRADO = "No se encontró el proyecto {name}."
WEB_PROYECTO_NO_SE_PUDO_ABRIR = "No se pudo abrir el proyecto {name}: {exc}"
WEB_NOMBRE_VACIO = "Escribe un nombre para el proyecto."
WEB_MODELO_NO_DISPONIBLE = "Ese modelo no está en la carpeta de modelos."
WEB_CAPITULO_NO_EXISTE = "No existe el capítulo {number}."
WEB_CAMPO_INVALIDO = "Valor inválido para {name}."
WEB_FORMATO_DESCONOCIDO = "Formato de exportación desconocido: {fmt}"
WEB_SOLICITUD_INVALIDA = "Solicitud inválida."
WEB_NO_AUTORIZADO = "Acceso no autorizado. Abre de nuevo el enlace que muestra StoryForge en la PC."
WEB_SOLO_DESDE_LA_PC = "Esta página solo se puede abrir desde la PC donde corre StoryForge."
WEB_NO_ENCONTRADO = "No encontrado."
WEB_PUERTO_OCUPADO = "No se pudo usar el puerto {port}: {exc}. ¿Ya hay otro StoryForge en modo servidor? Prueba con --puerto."
WEB_SERVIDOR_LISTO = (
    "StoryForge en el celular está listo.\n"
    "  En la PC:      {local_url}\n"
    "  En el celular: {phone_url}\n"
    "  (el celular tiene que estar en la misma red Wi-Fi que la PC)\n"
    "  Proyectos en:  {projects_dir}\n"
    "Ctrl+C para detener el servidor."
)
WEB_AYUDA_SERVIDOR = "Usa StoryForge desde el celular: inicia un servidor web en la red local en vez de la ventana."
WEB_AYUDA_PUERTO = "Puerto del servidor (por defecto {port})."
WEB_AYUDA_CARPETA = "Carpeta de proyectos del servidor (se recuerda para la próxima vez)."
WEB_AYUDA_MODELOS = "Carpeta extra donde buscar modelos .gguf (se recuerda para la próxima vez)."
WEB_AYUDA_SIN_NAVEGADOR = "No abrir la página de conexión en el navegador de la PC."

# Errores de Python, del sistema y de llama.cpp explicados en español
# (app/error_text.describe_exception: lo que se muestra en vez del texto en inglés).
ERR_ARCHIVO_NO_ENCONTRADO = "No se encontró el archivo o la carpeta: {path}"
ERR_SIN_PERMISO = (
    "No hay permiso para usar {path}. Puede estar abierto en otro programa, ser de solo lectura o estar "
    "sincronizándose con OneDrive; ciérralo o elige otra carpeta."
)
ERR_ES_CARPETA = "{path} es una carpeta, no un archivo."
ERR_NO_ES_CARPETA = "Parte de la ruta {path} no es una carpeta."
ERR_DISCO_LLENO = "No queda espacio en el disco para guardar {path}."
ERR_RUTA_DEMASIADO_LARGA = "El nombre o la ruta es demasiado largo: {path}"
ERR_JSON_INVALIDO = "El archivo no tiene un formato válido (JSON roto en la línea {line}, columna {col}). ¿Se cortó al guardarse?"
ERR_CODIFICACION = "El archivo no es texto UTF-8 (¿es un documento de Word u otro formato?). Guárdalo como texto UTF-8."
ERR_SIN_MEMORIA = "La computadora se quedó sin memoria RAM. Cierra otros programas o usa un modelo más chico."
ERR_SIN_VRAM = (
    "La tarjeta gráfica se quedó sin memoria (VRAM). Baja \"Capas en GPU\" o el contexto en la pestaña "
    "Modelo, o usa un modelo más chico."
)
ERR_MODELO_NO_CARGA = (
    "llama.cpp no pudo cargar el modelo. El archivo puede estar incompleto o dañado (vuelve a descargarlo), "
    "o ser de una arquitectura que esta versión de llama.cpp no conoce."
)
ERR_CONTEXTO_LLAMA = "El texto pedido no entra en la ventana de contexto del modelo. Sube \"Contexto\" en la pestaña Modelo."
ERR_LLAMA_INTERNO = "llama.cpp devolvió un error interno al generar. Vuelve a intentarlo; si se repite, recarga el modelo."
ERR_TIEMPO_AGOTADO = "La operación tardó demasiado y se canceló."
ERR_CONEXION = "Se cortó la conexión."
ERR_DETALLE = "{message}\n(detalle técnico: {detail})"
