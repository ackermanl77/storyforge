Coloca aqui tu archivo de modelo en formato GGUF (extension .gguf).

La app funciona con cualquier modelo de instrucciones compatible con
llama.cpp. Recomendaciones para escritura creativa en ingles:

RECOMENDADO PARA ESTA PC (32 GB de RAM, sin GPU dedicada):
  - Meta-Llama-3.1-8B-Instruct, cuantizacion Q5_K_M (~5.7 GB)
    Repositorio: bartowski/Meta-Llama-3.1-8B-Instruct-GGUF
    Archivo:     Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf
    Con 32 GB de RAM y sin GPU, la RAM no es el limite: conviene aprovechar
    una cuantizacion mas alta que Q4 para mejor calidad de escritura, ya que
    en CPU la diferencia de velocidad entre Q4 y Q5 es pequena.

  Alternativa si prefieres priorizar velocidad sobre calidad:
  - El mismo modelo en cuantizacion Q4_K_M (~4.9 GB, un poco mas rapido)

Recomendaciones generales para otras PCs:
  - 8 GB de RAM o menos: busca un modelo de 3B en Q4_K_M
  - 16 GB de RAM: Meta-Llama-3.1-8B-Instruct o Mistral-7B-Instruct-v0.3 en Q4_K_M
  - 32 GB de RAM o mas: cualquiera de los anteriores en Q5_K_M o Q6_K

Puedes buscar versiones .gguf ya cuantizadas de estos modelos en
Hugging Face (por ejemplo, en los repositorios de "bartowski" o
"lmstudio-community"). Descarga el archivo .gguf directamente en esta
carpeta.

Velocidad esperada SIN GPU (CPU unicamente): en una CPU moderna tipica, una
seccion de ~900 palabras puede tardar entre 1 y 4 minutos; un capitulo
completo de 10,000 palabras puede tomar entre 15 y 40 minutos. Es normal
que tarde, no es un error de la app.

Nota: descargar el modelo requiere internet una sola vez. Una vez descargado,
la generacion de historias funciona completamente sin conexion.

CON GPU NVIDIA DE 16 GB (p.ej. RTX 5080, todo el modelo en la GPU):
  En la pestana Modelo usa n_gpu_layers = -1, flash attention activado,
  lote (n_batch) 1024-2048 y, para contextos largos, cache KV q8_0. El boton
  "Estimar VRAM" calcula si el modelo cabe con ese contexto y sugiere capas.
  - 7-9B en Q8_0 con 16k-32k de contexto (Llama-3.1-8B-Instruct se entreno
    con 128k; ojo: daredevil-8b-abliterated solo con 8,192 -- no le pidas mas).
  - 12-14B en Q5_K_M / Q6_K con 16k de contexto y cache KV q8_0.
  - 22-24B en Q4_K_M con contexto chico (justo: la app avisa si no cabe).
  - 70B (incluso en Q4/Q5) NO cabe en 16 GB: corre casi todo en la CPU y es
    muy lento. Ademas, un modelo partido en varios archivos (...-00001-of-
    00002.gguf) necesita TODAS sus partes en la misma carpeta; la lista de
    modelos marca los incompletos y no los deja cargar.

Consejo: si esta carpeta esta dentro de OneDrive, guarda los .gguf en otra
carpeta (p.ej. C:\Modelos) y configurala en Archivo > Preferencias >
"Carpeta de modelos adicional": asi no se sincronizan varios GB ni quedan
"solo en linea" (lo que haria que la primera carga los descargue entera).
