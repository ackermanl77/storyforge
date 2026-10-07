Coloca aqui tu archivo de modelo en formato GGUF (extension .gguf).

La app funciona con cualquier modelo de instrucciones compatible con
llama.cpp. Puedes buscar versiones .gguf ya cuantizadas en Hugging Face (por
ejemplo, en los repositorios de "bartowski" o "lmstudio-community") y
descargar el archivo .gguf directamente en esta carpeta. Descargar requiere
internet una sola vez; despues la generacion funciona sin conexion.

RECOMENDADO PARA ESTA PC (GPU NVIDIA RTX 5080 de 16 GB):
  En la pestana Modelo usa n_gpu_layers = -1, flash attention activado,
  lote (n_batch) 1024-2048 y, para contextos largos, cache KV q8_0. El boton
  "Estimar VRAM" calcula si el modelo cabe con ese contexto y sugiere capas.

  - Modelo de uso diario: un 7-9B en Q8_0, todo en la GPU, con 16k-32k de
    contexto. Por ejemplo:
      bartowski/Meta-Llama-3.1-8B-Instruct-GGUF
      Meta-Llama-3.1-8B-Instruct-Q8_0.gguf (~8.5 GB; entrenado con 128k)
    daredevil-8b-abliterated.Q8_0.gguf tambien cabe entero, pero solo admite
    8,192 de contexto -- no le pidas mas.
  - Mas calidad sin salir de la GPU: 12-14B en Q5_K_M / Q6_K con 16k de
    contexto y cache KV q8_0.
  - 22-24B en Q4_K_M con contexto chico (justo: la app avisa si no cabe).
  - 70B (incluso en Q4/Q5, ~40-50 GB) NO cabe en 16 GB: la GPU carga solo
    parte de las capas y el resto corre en la CPU, asi que es mucho mas lento
    (minutos por seccion). Si el modelo ni siquiera cabe entre la RAM y la
    VRAM, llama.cpp lo va leyendo del disco y se vuelve aun mas lento. Usalo
    solo para textos cortos donde la calidad importe mas que la velocidad.

  Un modelo partido en varios archivos (...-00001-of-00002.gguf) necesita
  TODAS sus partes en la misma carpeta; selecciona la parte 00001. La lista
  de modelos lo muestra como "(N partes)" y marca los incompletos, que no se
  pueden cargar.

SIN GPU (solo CPU), segun la RAM:
  - 8 GB de RAM o menos: un modelo de 3B en Q4_K_M
  - 16 GB de RAM: Meta-Llama-3.1-8B-Instruct o Mistral-7B-Instruct-v0.3 en Q4_K_M
  - 32 GB de RAM o mas: cualquiera de los anteriores en Q5_K_M o Q6_K
  Velocidad esperada en una CPU moderna tipica: una seccion de ~900 palabras
  puede tardar entre 1 y 4 minutos; un capitulo de 10,000 palabras, entre 15 y
  40 minutos. Es normal que tarde, no es un error de la app.

Consejo: si esta carpeta esta dentro de OneDrive, guarda los .gguf en otra
carpeta (p.ej. C:\Modelos) y configurala en Archivo > Preferencias >
"Carpeta de modelos adicional": asi no se sincronizan varios GB ni quedan
"solo en linea" (lo que haria que la primera carga los descargue entera).
