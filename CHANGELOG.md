# Historial de cambios

Los cambios importantes de StoryForge. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones,
[Semantic Versioning](https://semver.org/lang/es/). El historial detallado de versiones
anteriores está en la sección "Historial de cambios" del README.

## [Sin publicar] -- 0.4.0

### Agregado
- Comenzar con los capítulos del último proyecto y una barra de menús con el tema de la app.
- Comentarios del editor, detección de personajes, escenas y tramos privados, relaciones del
  lorebook, retratos con un PixelFlow local y lorebook de serie.
- Progresiones del lorebook, matriz de la historia, notas del proyecto en el prompt y
  componentes de prompt reutilizables.
- Importar un manuscrito (.docx, .md o .txt) como proyecto nuevo.
- Recordar pasajes anteriores relevantes (BM25 o un modelo de embeddings GGUF), lluvia de
  ideas y entrevistas a personajes, alternativas en una palabra.
- Modelo en un servidor compatible con OpenAI, frases a evitar y limpieza de la salida del
  modelo, generador de historias y ajustes de la historia con presets.
- Comprobación de versión nueva una vez por arranque, contra los GitHub Releases del proyecto (update.json).
- Auditoría de dependencias (`pip-audit`) en CI y Dependabot.
- Licencia MIT, `THIRD_PARTY_NOTICES.md` (incluido en el programa y en el instalador),
  `SECURITY.md` y una sección de privacidad en el README.

### Corregido
- Guardado de proyectos y flujos del servidor más robustos: rutas de proyecto seguras,
  admisión de tareas sincronizada y reversión de archivos vinculados.

### Seguridad
- `diskcache` (lo trae llama-cpp-python) tiene un aviso sin versión corregida
  (PYSEC-2026-2447); StoryForge no usa su caché en disco, y la auditoría lo ignora con esa
  justificación.
