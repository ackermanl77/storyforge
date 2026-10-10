// StoryForge en el celular: la pagina que sirve app/web_server.py.
// Sin dependencias: llama a la API JSON con la clave de acceso y consulta
// /api/tarea cada segundo mientras el modelo trabaja.
"use strict";

const TOKEN_KEY = "storyforge-token";
const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n || 0).toLocaleString("es");

// ---- clave de acceso: llega una vez en el enlace (?t=...) y se guarda ----
(function captureToken() {
  const params = new URLSearchParams(location.search);
  const t = params.get("t");
  if (t) {
    try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { window.__token = t; }
    history.replaceState(null, "", "/");
  }
})();

function token() {
  try { return localStorage.getItem(TOKEN_KEY) || window.__token || ""; } catch (e) { return window.__token || ""; }
}

async function api(method, path, body) {
  const headers = { "X-StoryForge-Token": token() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new Error("No hay conexión con la PC. ¿Sigue encendida y en la misma red Wi-Fi?");
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* sin cuerpo JSON */ }
  if (response.status === 401) $("auth-warning").classList.remove("hidden");
  if (!response.ok) throw new Error((data && data.error) || `Error ${response.status}`);
  return data;
}

// ---- avisos ----
let toastTimer = null;
function toast(message, kind = "") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), kind === "error" ? 8000 : 4000);
}

async function run(action) {
  try { return await action(); } catch (e) { toast(e.message, "error"); return undefined; }
}

// ---- estado de la pagina ----
const state = {
  view: "inicio",
  status: null,
  project: null,
  chapter: null,        // indice del capitulo abierto
  chapterDirty: false,
  job: { id: null, offset: 0, running: false },
};

function busy() { return state.job.running; }

// ---- vistas ----
function show(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  $(`view-${view}`).classList.remove("hidden");
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view || (view === "capitulo" && b.dataset.view === "capitulos"));
  });
  const needsProject = ["historia", "esquema", "capitulos", "capitulo", "exportar"].includes(view);
  $("no-project").classList.toggle("hidden", !(needsProject && !state.project));
  $(`view-${view}`).classList.toggle("hidden", needsProject && !state.project);
  window.scrollTo(0, 0);
}

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", async () => {
  if (!(await leaveChapter())) return;
  show(b.dataset.view);
}));

async function leaveChapter() {
  if (state.view === "capitulo" && state.chapterDirty && !busy()) {
    if (confirm("Hay cambios sin guardar en este capítulo. ¿Guardarlos?")) {
      return (await run(saveChapter)) !== undefined;
    }
    state.chapterDirty = false;
  }
  return true;
}

// ---- estado general (modelo / proyecto) ----
function renderStatus(st) {
  state.status = st;
  const model = st.modelo;
  const pill = $("top-model");
  pill.textContent = model ? "Modelo listo" : "Sin modelo";
  pill.classList.toggle("ok", !!model);
  $("model-status").textContent = model
    ? `Cargado: ${model.nombre} (contexto ${fmt(model.n_ctx)} tokens)`
    : "Sin modelo cargado.";
  $("top-project").textContent = st.proyecto ? st.proyecto.nombre : "Sin proyecto";
  $("projects-dir").textContent = `Carpeta de proyectos en la PC: ${st.carpeta_proyectos}`;
  $("models-dirs").textContent = `Modelos buscados en: ${(st.carpetas_modelos || []).join(" · ")}`;
}

async function refreshStatus() {
  const st = await api("GET", "/api/estado");
  renderStatus(st);
  if (st.tarea) trackJob(st.tarea, true);
  return st;
}

async function loadModels() {
  const models = await api("GET", "/api/modelos");
  const select = $("model-select");
  select.innerHTML = "";
  if (!models.length) {
    select.add(new Option("(no se encontraron modelos .gguf; ver las carpetas abajo)", ""));
    return;
  }
  const loaded = state.status && state.status.modelo ? state.status.modelo.nombre : null;
  for (const m of models) {
    const option = new Option(m.nombre, m.id);
    if (loaded && m.id.endsWith(loaded)) option.selected = true;
    select.add(option);
  }
}

$("model-load").addEventListener("click", () => run(async () => {
  const id = $("model-select").value;
  if (!id) return;
  trackJob(await api("POST", "/api/modelo/cargar", { modelo: id }));
}));

$("model-unload").addEventListener("click", () => run(async () => {
  renderStatus(await api("POST", "/api/modelo/descargar"));
}));

// ---- proyectos ----
async function loadProjects() {
  const projects = await api("GET", "/api/proyectos");
  const list = $("project-list");
  list.innerHTML = "";
  if (!projects.length) {
    list.innerHTML = '<li class="muted">Todavía no hay proyectos. Crea uno arriba.</li>';
    return;
  }
  const current = state.project ? state.project.archivo : null;
  for (const p of projects) {
    const li = document.createElement("li");
    li.classList.toggle("current", p.archivo === current);
    li.innerHTML = `<div><div class="title"></div><div class="meta"></div></div><span class="muted">Abrir ›</span>`;
    li.querySelector(".title").textContent = p.nombre;
    li.querySelector(".meta").textContent = `${p.capitulos} capítulos · ${fmt(p.palabras)} palabras`;
    li.addEventListener("click", () => run(async () => {
      if (busy()) throw new Error("Espera a que termine la tarea en curso.");
      setProject(await api("POST", "/api/proyecto/abrir", { archivo: p.archivo }));
      await loadProjects();
      show("capitulos");
    }));
    list.appendChild(li);
  }
}

$("new-project").addEventListener("click", () => run(async () => {
  const name = $("new-project-name").value.trim();
  if (!name) { $("new-project-name").focus(); return; }
  setProject(await api("POST", "/api/proyectos", { nombre: name }));
  $("new-project-name").value = "";
  await loadProjects();
  show("historia");
}));

function setProject(project) {
  state.project = project;
  $("top-project").textContent = project ? project.nombre : "Sin proyecto";
  if (!project) return;
  renderStory(project);
  renderOutline(project);
  renderChapterList(project);
}

async function reloadProject() {
  if (!state.project) return;
  setProject(await api("GET", "/api/proyecto"));
}

// ---- historia ----
function wordCount(text) { return (text.match(/\S+/g) || []).length; }

function renderStory(p) {
  const estilo = $("p-estilo");
  estilo.innerHTML = "";
  for (const s of p.estilos) estilo.add(new Option(s.etiqueta, s.valor));
  document.querySelectorAll("#view-historia [data-field]").forEach((el) => { el.value = p[el.dataset.field] || ""; });
  updateCounts();
}

function updateCounts() {
  document.querySelectorAll("[data-count]").forEach((el) => {
    el.textContent = `${fmt(wordCount($(el.dataset.count).value))} palabras`;
  });
}
document.querySelectorAll("#view-historia textarea").forEach((el) => el.addEventListener("input", updateCounts));

$("save-story").addEventListener("click", () => run(async () => {
  const body = {};
  document.querySelectorAll("#view-historia [data-field]").forEach((el) => { body[el.dataset.field] = el.value; });
  setProject(await api("PUT", "/api/proyecto", body));
  toast("Guardado.", "ok");
}));

// ---- esquema ----
function renderOutline(p) {
  const box = $("outline-list");
  box.innerHTML = "";
  p.capitulos.forEach((ch) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <label>Capítulo ${ch.indice + 1}</label>
      <input type="text" class="o-title">
      <label>Eventos</label>
      <textarea rows="5" class="o-text"></textarea>
      <button class="btn small o-save">Guardar</button>`;
    card.querySelector(".o-title").value = ch.titulo;
    card.querySelector(".o-text").value = ch.esquema;
    card.querySelector(".o-save").addEventListener("click", () => run(async () => {
      await api("PUT", `/api/capitulo/${ch.indice}`, {
        titulo: card.querySelector(".o-title").value, esquema: card.querySelector(".o-text").value,
      });
      await reloadProject();
      toast("Guardado.", "ok");
    }));
    box.appendChild(card);
  });
}

$("outline-generate").addEventListener("click", () => run(async () => {
  const n = parseInt($("outline-count").value, 10);
  if (state.project.capitulos.length && !confirm("Esto reemplaza el título y el esquema de los capítulos existentes (su texto se conserva). ¿Continuar?")) return;
  trackJob(await api("POST", "/api/esquema", { capitulos: n }));
}));

// ---- lista de capitulos ----
function renderChapterList(p) {
  const list = $("chapter-list");
  list.innerHTML = "";
  if (!p.capitulos.length) {
    list.innerHTML = '<li class="muted">Sin capítulos. Genera un esquema o agrega uno.</li>';
  }
  for (const ch of p.capitulos) {
    const li = document.createElement("li");
    let note = "";
    if (ch.palabras && !ch.tiene_resumen) note = " · sin resumen";
    else if (ch.resumen_desactualizado) note = " · resumen desactualizado";
    if (ch.prompt_propio) note += " · prompt propio";
    li.innerHTML = `<div><div class="title"></div><div class="meta"></div></div><span class="muted">›</span>`;
    li.querySelector(".title").textContent = `${ch.indice + 1}. ${ch.titulo || "(sin título)"}`;
    li.querySelector(".meta").textContent = `${fmt(ch.palabras)} / ${fmt(ch.objetivo)} palabras${note}`;
    li.addEventListener("click", () => run(() => openChapter(ch.indice)));
    list.appendChild(li);
  }
  $("chapter-add").disabled = p.capitulos.length >= p.max_capitulos;
}

$("chapter-add").addEventListener("click", () => run(async () => {
  const ch = await api("POST", "/api/capitulos", { titulo: "" });
  await reloadProject();
  await openChapter(ch.indice);
}));

// ---- un capitulo ----
function fillChapter(ch) {
  state.chapter = ch.indice;
  const purpose = $("ch-proposito");
  purpose.innerHTML = "";
  for (const p of state.project.propositos) purpose.add(new Option(p.etiqueta, p.valor));
  $("ch-titulo").value = ch.titulo;
  $("ch-objetivo").value = ch.objetivo;
  purpose.value = ch.proposito;
  $("ch-esquema").value = ch.esquema;
  $("ch-nota").value = ch.nota_autor;
  $("ch-prompt").value = ch.prompt || "";
  updatePromptState();
  $("ch-texto").value = ch.texto;
  $("ch-resumen").textContent = ch.resumen || "(todavía no hay resumen)";
  $("ch-summary-state").textContent = ch.resumen_desactualizado ? "(desactualizado)" : "";
  $("ch-continue").disabled = busy() || !ch.texto.trim();
  updateChapterWords();
  state.chapterDirty = false;
}

function updateChapterWords() {
  $("ch-words").textContent = `${fmt(wordCount($("ch-texto").value))} / ${fmt($("ch-objetivo").value)} palabras`;
}

async function openChapter(index) {
  fillChapter(await api("GET", `/api/capitulo/${index}`));
  show("capitulo");
  if (state.job.running && state.lastJob && state.lastJob.capitulo === index) {
    $("ch-texto").value = state.jobText || "";
    $("ch-texto").scrollTop = $("ch-texto").scrollHeight;
  }
}

function updatePromptState() {
  $("ch-prompt-state").textContent = $("ch-prompt").value.trim() ? "● activo" : "";
}

$("ch-prompt").addEventListener("input", updatePromptState);

$("ch-prompt-template").addEventListener("click", () => {
  if ($("ch-prompt").value.trim() && !confirm("¿Reemplazar el prompt propio de este capítulo por la plantilla?")) return;
  $("ch-prompt").value = state.project.plantilla_prompt;
  state.chapterDirty = true;
  updatePromptState();
});

["ch-titulo", "ch-objetivo", "ch-proposito", "ch-esquema", "ch-nota", "ch-prompt", "ch-texto"].forEach((id) => {
  $(id).addEventListener("input", () => { state.chapterDirty = true; updateChapterWords(); });
});

function chapterBody(includeText) {
  const body = {
    titulo: $("ch-titulo").value,
    objetivo: parseInt($("ch-objetivo").value, 10) || 2000,
    proposito: $("ch-proposito").value,
    esquema: $("ch-esquema").value,
    nota_autor: $("ch-nota").value,
    prompt: $("ch-prompt").value,
  };
  if (includeText) body.texto = $("ch-texto").value;
  return body;
}

async function saveChapter() {
  fillChapter(await api("PUT", `/api/capitulo/${state.chapter}`, chapterBody(true)));
  await reloadProject();
  return true;
}

$("chapter-back").addEventListener("click", async () => {
  if (!(await leaveChapter())) return;
  show("capitulos");
});

$("ch-save").addEventListener("click", () => run(async () => { await saveChapter(); toast("Guardado.", "ok"); }));

$("ch-generate").addEventListener("click", () => run(async () => {
  if ($("ch-texto").value.trim() && !confirm("Esto reemplaza el texto actual del capítulo (la versión anterior queda guardada en Versiones). ¿Generar?")) return;
  // Titulo/objetivo/esquema cuentan para la generacion; el texto se reemplaza.
  await api("PUT", `/api/capitulo/${state.chapter}`, chapterBody(false));
  state.chapterDirty = false;
  $("ch-texto").value = "";
  trackJob(await api("POST", `/api/capitulo/${state.chapter}/generar`, { continuar: false }));
}));

$("ch-continue").addEventListener("click", () => run(async () => {
  await api("PUT", `/api/capitulo/${state.chapter}`, chapterBody(true));
  state.chapterDirty = false;
  trackJob(await api("POST", `/api/capitulo/${state.chapter}/generar`, { continuar: true }));
}));

$("ch-summary").addEventListener("click", () => run(async () => {
  trackJob(await api("POST", `/api/capitulo/${state.chapter}/resumen`));
}));

$("ch-delete").addEventListener("click", () => run(async () => {
  if (!confirm("¿Eliminar este capítulo y todo su texto?")) return;
  setProject(await api("DELETE", `/api/capitulo/${state.chapter}`));
  state.chapterDirty = false;
  show("capitulos");
}));

// ---- exportar ----
document.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", () => run(async () => {
  const response = await fetch(`/api/exportar/${b.dataset.export}`, { headers: { "X-StoryForge-Token": token() } });
  if (!response.ok) {
    let message = `Error ${response.status}`;
    try { message = (await response.json()).error || message; } catch (e) { /* sin JSON */ }
    throw new Error(message);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : `historia.${b.dataset.export}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
})));

// ---- tareas del modelo ----
$("job-stop").addEventListener("click", () => run(() => api("POST", "/api/detener")));

function setBusy(isBusy) {
  document.querySelectorAll("main button").forEach((b) => {
    if (b.id === "chapter-back" || b.dataset.export) return;
    b.disabled = isBusy;
  });
  $("ch-texto").readOnly = isBusy;
  if (!isBusy && state.view === "capitulo") $("ch-continue").disabled = !$("ch-texto").value.trim();
  if (!isBusy && state.project) $("chapter-add").disabled = state.project.capitulos.length >= state.project.max_capitulos;
}

// fromStatus: la tarea viene de /api/estado, sin texto (solo /api/tarea lo trae).
function trackJob(snapshot, fromStatus = false) {
  if (!snapshot) return;
  if (snapshot.id !== state.job.id) {
    state.job = { id: snapshot.id, offset: 0, running: snapshot.estado === "running" };
    state.jobText = "";
    // Una tarea que ya termino antes de abrir la pagina no se anuncia.
    state.job.announced = snapshot.estado !== "running";
  }
  applyJob(snapshot, fromStatus);
  if (snapshot.estado === "running") schedulePoll(300);
}

function applyJob(job, fromStatus = false) {
  state.lastJob = job;
  if (!fromStatus) {
    if (job.reiniciar) state.jobText = "";
    if (job.texto) state.jobText = (job.desde === 0 ? "" : state.jobText || "") + job.texto;
    state.job.offset = job.largo;
  }
  const running = job.estado === "running";
  const banner = $("job");
  banner.classList.toggle("hidden", !running);
  if (running) {
    $("job-label").textContent = job.etiqueta;
    const fraction = job.objetivo ? Math.min(1, job.palabras / job.objetivo) : null;
    banner.classList.toggle("indeterminate", fraction === null);
    $("job-bar").style.width = fraction === null ? "" : `${Math.round(fraction * 100)}%`;
    const parts = [];
    if (job.mensaje) parts.push(job.mensaje);
    if (job.objetivo) parts.push(`${fmt(job.palabras)} / ${fmt(job.objetivo)} palabras`);
    if (job.tokens_por_segundo) parts.push(`${job.tokens_por_segundo} tok/s`);
    if (job.eta_segundos) parts.push(`faltan ~${Math.ceil(job.eta_segundos / 60)} min`);
    if (!parts.length) parts.push(`${Math.round(job.segundos)} s`);
    $("job-detail").textContent = parts.join(" · ");
    if (!fromStatus && job.tipo === "chapter" && state.view === "capitulo" && state.chapter === job.capitulo) {
      const box = $("ch-texto");
      const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
      box.value = state.jobText;
      if (atEnd) box.scrollTop = box.scrollHeight;
      updateChapterWords();
    }
  }
  const wasRunning = state.job.running;
  state.job.running = running;
  setBusy(running);
  if (wasRunning && !running && !state.job.announced) {
    state.job.announced = true;
    finishJob(job);
  }
}

async function finishJob(job) {
  const kind = job.estado === "error" ? "error" : job.estado === "ok" ? "ok" : "";
  toast(job.mensaje || "Listo.", kind);
  await run(async () => {
    await refreshStatus();
    if (job.tipo === "load") await loadModels();
    await reloadProject();
    if (state.view === "capitulo" && job.capitulo === state.chapter) fillChapter(await api("GET", `/api/capitulo/${state.chapter}`));
  });
}

let pollTimer = null;
function schedulePoll(delay) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, delay);
}

let lastStatus = 0;
async function poll() {
  try {
    if (state.job.running) {
      const job = await api("GET", `/api/tarea?desde=${state.job.offset}`);
      if (job) applyJob(job);
    }
    if (Date.now() - lastStatus > 5000) {
      lastStatus = Date.now();
      await refreshStatus();
    }
  } catch (e) {
    // Sin conexion un momento (p.ej. el celular bloqueo la pantalla): se reintenta.
  }
  schedulePoll(state.job.running ? 1000 : 4000);
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) schedulePoll(0); });

// ---- inicio ----
(async function start() {
  if (!token()) $("auth-warning").classList.remove("hidden");
  await run(async () => {
    const st = await refreshStatus();
    lastStatus = Date.now();
    await loadModels();
    if (st.proyecto) setProject(await api("GET", "/api/proyecto"));
    await loadProjects();
  });
  show("inicio");
  schedulePoll(1000);
})();
