// Generador de historias de StoryForge (app/web/generador.html): un formulario,
// una historia. Usa la API del servidor local (app/web_server.py) con la misma
// clave de acceso que la página del celular, y consulta /api/tarea mientras el
// modelo escribe.
"use strict";

const TOKEN_KEY = "storyforge-token";
const FORM_KEY = "storyforge-generador-formulario";
const $ = (id) => document.getElementById(id);
const fmt = (n) => Number(n || 0).toLocaleString("es");
const TEXT_FIELDS = ["plot", "characters", "setting", "genre", "theme", "point_of_view", "tone", "context"];

const state = { options: null, history: [], outputs: [], job: null, poll: null, lastForm: null };

// ---- clave de acceso: llega en el enlace (?t=...) y se guarda ----
(function captureToken() {
  const t = new URLSearchParams(location.search).get("t");
  if (t) {
    try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { window.__token = t; }
    history.replaceState(null, "", "/generador");
  }
})();

function token() {
  try { return localStorage.getItem(TOKEN_KEY) || window.__token || ""; } catch (e) { return window.__token || ""; }
}

async function api(method, path, body) {
  const options = { method, headers: { "X-StoryForge-Token": token() } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
  return data;
}

function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), 2600);
}

async function run(fn) {
  try { await fn(); } catch (e) { toast(e.message); }
}

// ---- formulario ----
function chipGroup(containerId, items, onChange) {
  const box = $(containerId);
  box.innerHTML = "";
  for (const item of items) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.setAttribute("role", "radio");
    chip.dataset.value = item.valor;
    chip.textContent = item.etiqueta;
    chip.addEventListener("click", () => { setChip(containerId, item.valor); onChange && onChange(); });
    box.appendChild(chip);
  }
}

function setChip(containerId, value) {
  for (const chip of $(containerId).children) chip.setAttribute("aria-checked", String(chip.dataset.value === value));
}

function chipValue(containerId) {
  const on = [...$(containerId).children].find((c) => c.getAttribute("aria-checked") === "true");
  return on ? on.dataset.value : $(containerId).children[0].dataset.value;
}

function readForm() {
  const form = {};
  for (const field of TEXT_FIELDS) form[field] = $(field).value;
  form.purpose = chipValue("purpose");
  form.format = chipValue("format");
  form.length = $("length").value;
  form.dialogue = $("dialogue-on").checked ? Number($("dialogue").value) : -1;
  return form;
}

function writeForm(form) {
  for (const field of TEXT_FIELDS) $(field).value = form[field] || "";
  setChip("purpose", form.purpose || "complete");
  setChip("format", form.format || "prose");
  $("length").value = form.length || "short";
  const hasDialogue = typeof form.dialogue === "number" && form.dialogue >= 0;
  $("dialogue-on").checked = hasDialogue;
  $("dialogue").disabled = !hasDialogue;
  $("dialogue").value = hasDialogue ? form.dialogue : 50;
  updateCounts();
  rememberForm();
}

function updateCounts() {
  const limits = (state.options || {}).limites || {};
  document.querySelectorAll("[data-count]").forEach((el) => {
    const field = el.dataset.count;
    el.textContent = `${fmt($(field).value.length)} / ${fmt(limits[field])}`;
  });
}

function rememberForm() {
  try { localStorage.setItem(FORM_KEY, JSON.stringify(readForm())); } catch (e) { /* sin almacenamiento */ }
}

function fillPresets(presets, select) {
  const box = $("preset-select");
  box.innerHTML = "";
  box.add(new Option("Cargar preset…", ""));
  for (const name of Object.keys(presets)) box.add(new Option(name, name));
  if (select) box.value = select;
  state.options.presets = presets;
}

async function loadOptions() {
  const options = await api("GET", "/api/generador");
  state.options = options;
  chipGroup("purpose", options.propositos, rememberForm);
  chipGroup("format", options.formatos, rememberForm);
  const length = $("length");
  length.innerHTML = "";
  for (const item of options.largos) length.add(new Option(item.etiqueta, item.valor));
  for (const [field, values] of Object.entries(options.sugerencias)) {
    const list = $(`dl-${field}`);
    list.innerHTML = "";
    for (const value of values) list.appendChild(new Option(value));
  }
  for (const [field, limit] of Object.entries(options.limites)) $(field).maxLength = limit;
  fillPresets(options.presets);
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(FORM_KEY) || "null"); } catch (e) { saved = null; }
  writeForm(saved || {});
}

// ---- modelo ----
async function loadModels() {
  const [models, status] = await Promise.all([api("GET", "/api/modelos"), api("GET", "/api/estado")]);
  const select = $("model-select");
  select.innerHTML = "";
  for (const m of models) select.add(new Option(m.nombre, m.id));
  if (!models.length) select.add(new Option("No hay modelos .gguf en la carpeta models", ""));
  showStatus(status);
  if (status.tarea && status.tarea.estado === "running") track(status.tarea);
}

function showStatus(status) {
  const model = status.modelo;
  const pill = $("model-status");
  pill.textContent = model ? `Cargado: ${model.nombre}` : "Sin modelo";
  pill.classList.toggle("muted", !model);
  if (model) {
    const option = [...$("model-select").options].find((o) => o.text === model.nombre || o.value.endsWith(model.nombre));
    if (option) $("model-select").value = option.value;
  }
}

// ---- tareas (cargar modelo / generar) ----
function track(snapshot) {
  state.job = { id: snapshot.id, kind: snapshot.tipo, text: "", offset: 0 };
  setRunning(true);
  applySnapshot(snapshot);
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(state.poll);
  state.poll = setTimeout(poll, 600);
}

async function poll() {
  if (!state.job) return;
  try {
    const snapshot = await api("GET", `/api/tarea?desde=${state.job.offset}`);
    if (!snapshot || snapshot.id !== state.job.id) return;
    applySnapshot(snapshot);
    if (snapshot.estado === "running") schedulePoll();
    else await finish(snapshot);
  } catch (e) {
    schedulePoll();
  }
}

function applySnapshot(job) {
  if (job.reiniciar) state.job.text = "";
  if (job.texto) state.job.text = (job.desde === 0 ? "" : state.job.text) + job.texto;
  state.job.offset = job.largo;
  const parts = [job.etiqueta];
  if (job.mensaje) parts.push(job.mensaje);
  if (job.objetivo) parts.push(`${fmt(job.palabras)} / ${fmt(job.objetivo)} palabras`);
  if (job.tokens_por_segundo) parts.push(`${job.tokens_por_segundo} tok/s`);
  $("progress-text").textContent = parts.join(" · ");
  $("progress-fill").style.width = job.objetivo ? `${Math.min(100, Math.round(100 * job.palabras / job.objetivo))}%` : "15%";
  if (state.job.kind === "story") {
    $("live").classList.remove("hidden");
    $("outputs-empty").classList.add("hidden");
    $("live-text").textContent = state.job.text || "…";
  }
}

async function finish(job) {
  const kind = state.job.kind;
  state.job = null;
  setRunning(false);
  $("live").classList.add("hidden");
  if (kind === "load") {
    showStatus(await api("GET", "/api/estado"));
    toast(job.estado === "ok" ? "Modelo cargado." : job.mensaje);
    return;
  }
  await refreshHistory();
  if (job.estado === "error") {
    showError(job.mensaje);
    return;
  }
  const newest = state.history[0];
  if (newest && !state.outputs.some((o) => o.id === newest.id)) state.outputs.unshift(newest);
  renderOutputs();
  toast(job.estado === "cancelled" ? "Detenido: se guardó lo escrito hasta ahí." : "Historia lista.");
}

function setRunning(running) {
  $("progress").classList.toggle("hidden", !running);
  $("generate").disabled = running;
  $("load-model").disabled = running;
  $("stop").classList.toggle("hidden", !running);
}

function showError(message) {
  const el = $("form-error");
  el.textContent = message || "";
  el.classList.toggle("hidden", !message);
}

async function generate(form) {
  showError("");
  state.lastForm = form;
  const snapshot = await api("POST", "/api/generador/generar", form);
  switchTab("outputs");
  track(snapshot);
}

// ---- resultados / historial / guardados ----
function storyCard(entry, { collapsed = false } = {}) {
  const card = document.createElement("article");
  card.className = "story" + (collapsed ? " collapsed" : "");
  const head = document.createElement("header");
  const title = document.createElement("b");
  title.textContent = entry.title;
  const meta = document.createElement("span");
  meta.className = "small muted";
  meta.textContent = `${fmt(entry.words)} palabras · ${new Date(entry.created * 1000).toLocaleString("es")}`;
  head.append(title, meta);
  const text = document.createElement("pre");
  text.textContent = entry.text;
  const tools = document.createElement("div");
  tools.className = "tools";
  const button = (label, handler, extra = "") => {
    const b = document.createElement("button");
    b.className = `btn small ${extra}`;
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", () => run(handler));
    tools.appendChild(b);
    return b;
  };
  if (collapsed) button("Ver completa", async () => card.classList.toggle("collapsed"));
  button("Copiar", async () => { await navigator.clipboard.writeText(entry.text); toast("Copiado."); });
  const star = button(entry.saved ? "★ Guardada" : "☆ Guardar", async () => {
    const updated = await api("POST", `/api/generador/historial/${entry.id}/guardar`, { guardado: !entry.saved });
    entry.saved = updated.saved;
    await refreshHistory();
    renderOutputs();
  }, entry.saved ? "star on" : "star");
  star.title = "Los guardados no se borran del historial";
  button("Descargar .txt", async () => download(entry));
  button("Regenerar", async () => generate(entry.form));
  button("Usar estos ajustes", async () => { writeForm(entry.form); window.scrollTo({ top: 0, behavior: "smooth" }); });
  button("Borrar", async () => {
    if (!confirm("¿Borrar esta historia del historial?")) return;
    await api("DELETE", `/api/generador/historial/${entry.id}`);
    state.outputs = state.outputs.filter((o) => o.id !== entry.id);
    await refreshHistory();
    renderOutputs();
  }, "ghost");
  card.append(head, text, tools);
  return card;
}

function download(entry) {
  const blob = new Blob([entry.text], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  const name = (entry.form.genre || "historia").replace(/[^\w\- ]+/g, "").trim() || "historia";
  link.href = URL.createObjectURL(blob);
  link.download = `${name}-${entry.id}.txt`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function renderOutputs() {
  const box = $("outputs");
  box.innerHTML = "";
  for (const entry of state.outputs) {
    const fresh = state.history.find((h) => h.id === entry.id) || entry;
    box.appendChild(storyCard(fresh));
  }
  $("outputs-empty").classList.toggle("hidden", state.outputs.length > 0 || !$("live").classList.contains("hidden"));
  renderList("history", state.history, "Todavía no hay historias en el historial.");
  renderList("saved", state.history.filter((h) => h.saved), "Pulsa ☆ Guardar en una historia para tenerla aquí.");
}

function renderList(id, items, emptyText) {
  const box = $(id);
  box.innerHTML = "";
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = emptyText;
    box.appendChild(p);
    return;
  }
  for (const entry of items) box.appendChild(storyCard(entry, { collapsed: true }));
}

async function refreshHistory() {
  state.history = await api("GET", "/api/generador/historial");
  renderOutputs();
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  for (const tab of ["outputs", "history", "saved"]) $(`tab-${tab}`).classList.toggle("hidden", tab !== name);
}

// ---- eventos ----
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
document.querySelectorAll("[data-field]").forEach((el) => el.addEventListener("input", () => { updateCounts(); rememberForm(); }));
$("length").addEventListener("change", rememberForm);
$("dialogue").addEventListener("input", rememberForm);
$("dialogue-on").addEventListener("change", () => { $("dialogue").disabled = !$("dialogue-on").checked; rememberForm(); });
$("generate").addEventListener("click", () => run(() => generate(readForm())));
$("stop").addEventListener("click", () => run(() => api("POST", "/api/detener")));
$("load-model").addEventListener("click", () => run(async () => {
  const id = $("model-select").value;
  if (!id) return;
  track(await api("POST", "/api/modelo/cargar", { modelo: id }));
}));
$("preset-select").addEventListener("change", () => {
  const name = $("preset-select").value;
  const preset = name && state.options.presets[name];
  if (preset) { writeForm(preset); toast(`Preset «${name}» cargado.`); }
});
$("save-preset").addEventListener("click", () => run(async () => {
  const name = prompt("Nombre del preset (si ya existe uno tuyo con ese nombre, se reemplaza):");
  if (!name || !name.trim()) return;
  const result = await api("POST", "/api/generador/presets", { nombre: name.trim(), formulario: readForm() });
  fillPresets(result.presets, result.nombre);
  toast(`Preset «${result.nombre}» guardado.`);
}));
$("delete-preset").addEventListener("click", () => run(async () => {
  const name = $("preset-select").value;
  if (!name) { toast("Elige primero uno de tus presets."); return; }
  const result = await api("POST", "/api/generador/presets/borrar", { nombre: name });
  fillPresets(result.presets);
  toast(`Preset «${name}» borrado.`);
}));
$("clear-form").addEventListener("click", () => writeForm({}));

(async function start() {
  if (!token()) $("auth-warning").classList.remove("hidden");
  await run(loadOptions);
  await run(loadModels);
  await run(refreshHistory);
})();
