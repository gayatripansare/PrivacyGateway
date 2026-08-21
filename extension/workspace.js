document.addEventListener("DOMContentLoaded", () => {
const API_BASE = "http://127.0.0.1:8000";
const MIME_EXT = new Map([
  ["text/plain", "txt"], ["text/csv", "csv"], ["application/pdf", "pdf"],
  ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"],
  ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"],
  ["application/vnd.ms-excel.sheet.macroEnabled.12", "xlsm"],
  ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"]
]);
const SUPPORTED = new Set(["txt","csv","json","pdf","docx","xlsx","xlsm","pptx","png","jpg","jpeg","bmp","webp","gif","py","js","ts","html","md","yaml","yml","xml","log"]);
const getExt = name => { const value = String(name || "").toLowerCase(); const dot = value.lastIndexOf("."); return dot >= 0 ? value.slice(dot + 1) : ""; };
async function detectExtension(file) {
  const named = getExt(file.name);
  const mime = MIME_EXT.get(file.type || "");
  if (SUPPORTED.has(named)) return named;
  if (mime) return mime;
  const bytes = new Uint8Array(await file.slice(0, Math.min(file.size, 4 * 1024 * 1024)).arrayBuffer());
  const head = new TextDecoder("latin1").decode(bytes.subarray(0, 16));
  if (head.startsWith("%PDF-")) return "pdf";
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return "png";
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "jpg";
  if (head.startsWith("GIF8")) return "gif";
  if (head.startsWith("BM")) return "bmp";
  if (head.startsWith("RIFF") && head.includes("WEBP")) return "webp";
  if (bytes[0] === 0xd0 && bytes[1] === 0xcf && bytes[2] === 0x11 && bytes[3] === 0xe0) return "doc";
  if (bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04) {
    const zipText = new TextDecoder("latin1").decode(bytes);
    if (zipText.includes("word/")) return "docx";
    if (zipText.includes("xl/")) return "xlsx";
    if (zipText.includes("ppt/")) return "pptx";
  }
  const sample = new TextDecoder("utf-8", { fatal: false }).decode(bytes.subarray(0, 8192));
  const printable = [...sample].filter(ch => ch === "\n" || ch === "\r" || ch === "\t" || (ch >= " " && ch <= "~")).length;
  if (sample && printable / Math.max(1, sample.length) > 0.92) return "txt";
  return "";
}
const backendName = async file => {
  const ext = await detectExtension(file);
  if (!ext) throw new Error(`Unsupported or unidentified format: ${file.name || "upload"}`);
  return SUPPORTED.has(getExt(file.name)) ? file.name : `${file.name || "upload"}.${ext}`;
};
const events = new Map();
const cleanedFiles = new Map();
let state = { sourceTabId: null, lastCleanText: "" };

const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));

function send(message) {
  return new Promise(resolve => chrome.runtime.sendMessage(message, response => resolve(response || { ok: false })));
}

function renderCleanedFiles() {
  const box = $("cleaned-files");
  if (!box) return;
  if (!cleanedFiles.size) {
    box.innerHTML = '<div class="empty">Select files above to create cleaned copies.</div>';
    return;
  }
  box.innerHTML = [...cleanedFiles.values()].map(item => `<div class="event success">
    <div class="name" title="${esc(item.name)}">${esc(item.name)}</div>
    <div>${item.findings} sensitive item(s)</div>
    <div><button data-upload="${esc(item.id)}">Auto-Upload Clean</button> <button data-download="${esc(item.id)}">Download Clean</button></div>
  </div>`).join("");
  box.querySelectorAll("[data-upload]").forEach(button => button.addEventListener("click", async () => {
    const item = cleanedFiles.get(button.dataset.upload);
    if (!item) return;
    button.disabled = true;
    button.textContent = "Uploading…";
    const response = await send({ type: "INSERT_CLEAN_FILE", tabId: state.sourceTabId, file: item.blob, name: item.name, mime: item.blob.type });
    button.textContent = response.ok ? "Uploaded clean" : "Upload failed";
    if (!response.ok) $("summary-detail").textContent = response.error || "Select the original file input on the source page first.";
  }));
  box.querySelectorAll("[data-download]").forEach(button => button.addEventListener("click", () => {
    const item = cleanedFiles.get(button.dataset.download);
    if (!item) return;
    const url = URL.createObjectURL(item.blob);
    const link = document.createElement("a");
    link.href = url; link.download = `PrivacyGate_Cleaned_${item.name}`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
}

function render() {
  const list = $("event-list");
  const rows = [...events.values()].sort((a,b) => (b.timestamp || 0) - (a.timestamp || 0));
  if (!rows.length) {
    list.innerHTML = '<div class="empty">No activity yet. Upload files or paste text on the source page.</div>';
  } else {
    list.innerHTML = rows.map(event => {
      const label = event.kind === "text" ? "Text paste" : (event.name || event.fileName || "File");
      const detail = event.detail || (event.findings != null ? `${event.findings.length} sensitive item(s)` : "");
      const status = event.status || "queued";
      return `<div class="event ${status === "cleaned" ? "success" : status === "failed" || status === "blocked" ? "error" : ""}">
        <div class="name" title="${esc(label)}">${esc(label)}</div>
        <div>${esc(detail)}</div><div class="status ${esc(status)}">${esc(status)}</div>
      </div>`;
    }).join("");
  }
  const cleaned = rows.filter(row => row.status === "verified" || row.status === "cleaned").length;
  $("summary").textContent = `${rows.length} scan${rows.length === 1 ? "" : "s"}`;
  $("summary-detail").textContent = cleaned ? `${cleaned} clean result${cleaned === 1 ? "" : "s"} ready.` : "Waiting for uploads or text paste.";
  $("auto-paste").disabled = !state.lastCleanText;
  renderCleanedFiles();
}

async function refresh() {
  const response = await send({ type: "GET_WORKSPACE_STATE" });
  if (response.ok) {
    state.sourceTabId = response.sourceTabId;
    state.lastCleanText = response.lastCleanText || "";
    events.clear();
    (response.events || []).forEach((event, index) => events.set(`${event.timestamp}-${index}`, event));
    render();
  }
  const status = await send({ type: "CHECK_SERVICE" });
  $("service").textContent = status.running ? "Scanner online" : "Scanner offline";
  $("service").style.color = status.running ? "var(--green)" : "var(--orange)";
}

chrome.runtime.onMessage.addListener(message => {
  if (message.type === "WORKSPACE_EVENT") {
    const event = message.event || {};
    events.set(`${event.timestamp}-${Math.random()}`, event);
    render();
  }
});

const openSourceButton = $("open-source");
if (openSourceButton) openSourceButton.addEventListener("click", async () => {
  const response = await send({ type: "FOCUS_SOURCE" });
  const detail = $("summary-detail");
  if (!response.ok && detail) detail.textContent = response.error || "No source tab is available.";
});

const autoPasteButton = $("auto-paste");
if (autoPasteButton) autoPasteButton.addEventListener("click", async () => {
  const button = autoPasteButton;
  button.disabled = true;
  button.textContent = "Pasting…";
  const response = await send({ type: "INSERT_CLEAN_TEXT", tabId: state.sourceTabId });
  button.textContent = response.ok ? "Pasted" : "Copy Clean Text";
  const detail = $("summary-detail");
  if (!response.ok && detail) detail.textContent = response.error || "Focus an editable field on the source page first.";
  setTimeout(() => { button.textContent = "Auto-Paste Clean Text"; render(); }, 1800);
});

const workspaceFiles = $("workspace-files");
if (workspaceFiles) workspaceFiles.addEventListener("change", async event => {
  const files = [...event.target.files];
  for (const file of files) {
    const id = `${file.name}-${file.size}-${file.lastModified}`;
    events.set(id, { kind: "file", name: file.name, status: "scanning", detail: "Scanning" });
    render();
    try {
      const form = new FormData();
      form.append("file", file, await backendName(file));
      form.append("sensitivity", "standard");
      const response = await fetch(`${API_BASE}/scan-file`, { method: "POST", body: form });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const stateHeader = response.headers.get("X-PrivacyGate-State") || "uncertain";
      const reason = response.headers.get("X-PrivacyGate-Reason") || "verification_header_missing";
      const blob = await response.blob();
      const findings = Number(response.headers.get("X-Findings-Count") || 0);
      if (stateHeader !== "verified") throw new Error(`Verification ${stateHeader}: ${reason}`);
      cleanedFiles.set(id, { id, name: file.name, blob, findings, state: stateHeader });
      events.set(id, { kind: "file", name: file.name, status: "verified", detail: `${findings} sensitive item(s)` });
    } catch (error) {
      events.set(id, { kind: "file", name: file.name, status: "failed", detail: error.message });
    }
    render();
  }
  event.target.value = "";
});

const clearEventsButton = $("clear-events");
if (clearEventsButton) clearEventsButton.addEventListener("click", async () => {
  await send({ type: "CLEAR_WORKSPACE_EVENTS" });
  events.clear();
  render();
});

refresh();
setInterval(refresh, 3000);
});
