/**
 * content.js — PrivacyGate (Fixed + Optimized)
 * Fixes:
 *   1. Scanning cancelled files — added activeScan tracker + cancel logic
 *   2. Double network call removed — serviceOnline merged into scanFile
 *   3. Faster: no status pre-check, scan starts immediately
 */

(() => {
  "use strict";

  const API_BASE    = "http://127.0.0.1:8000";
  const BANNER_ID   = "privacygate-banner";
  const STORAGE_KEY = "privacygate_enabled";

  const INTERCEPT_EXT = new Set([
    "pdf","docx","doc","xlsx","xlsm","pptx",
    "txt","csv","json","py","js","ts","html","md","yaml","yml",
    "jpg","jpeg","png","bmp","webp","gif","svg",
    "sh","bat","env","ini","cfg","sql","log",
  ]);

  let pgEnabled  = true;
  let lastInput  = null;
  const inputByFileKey = new Map();
  let cleanedClipboard = null;
  let lastEditableTarget = null;
  let isDragging = false;
  let dragOffX   = 0;
  let dragOffY   = 0;

  // ── Active scan tracker ──────────────────────────────
  // Stores current scan so we can cancel it if file is removed
  let activeScanId  = null;
  let activeScanFile = null;
  let internalApiDepth = 0;

  function newScanId() {
    return Math.random().toString(36).slice(2);
  }

  // ─────────────────────────────────────────────────────
  // STORAGE
  // ─────────────────────────────────────────────────────

  chrome.storage.local.get([STORAGE_KEY], r => {
    pgEnabled = r[STORAGE_KEY] !== false;
  });
  chrome.storage.onChanged.addListener(c => {
    if (c[STORAGE_KEY]) pgEnabled = c[STORAGE_KEY].newValue !== false;
  });

  // ─────────────────────────────────────────────────────
  // HELPERS
  // ─────────────────────────────────────────────────────

  const getExt       = n => (n || "").split(".").pop().toLowerCase();
  const canIntercept = n => INTERCEPT_EXT.has(getExt(n));

  // Single call — no pre-check. If service offline, catch handles it.
  async function scanFile(file, signal) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("sensitivity", "standard");
    internalApiDepth++;
    try {
      const r = await fetch(`${API_BASE}/scan-file`, {
        method: "POST",
        body: fd,
        signal, // AbortSignal — lets us cancel mid-scan
      });
      if (!r.ok) throw new Error(`API ${r.status}`);
      return {
        blob:    await r.blob(),
        count:   parseInt(r.headers.get("X-Findings-Count") || "0"),
        high:    parseInt(r.headers.get("X-High-Count")     || "0"),
        med:     parseInt(r.headers.get("X-Med-Count")      || "0"),
        low:     parseInt(r.headers.get("X-Low-Count")      || "0"),
        types:   r.headers.get("X-Types-Found")             || "",
        summary: r.headers.get("X-Findings-Summary")        || "[]",
      };
    } finally {
      internalApiDepth--;
    }
  }

  function fileKey(file) {
    return `${file.name || ""}:${file.size}:${file.lastModified || 0}:${file.type || ""}`;
  }

  function setInputFile(input, blob, name, type) {
    if (!input || !(input instanceof HTMLInputElement) || input.type !== "file") return false;
    try {
      const clean = blob instanceof File
        ? blob
        : new File([blob], name || "PrivacyGate_Cleaned", {
            type: type || blob.type || "application/octet-stream",
            lastModified: Date.now()
          });
      const transfer = new DataTransfer();
      transfer.items.add(clean);
      const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files");
      if (!descriptor || !descriptor.set) return false;
      descriptor.set.call(input, transfer.files);
      return input.files && input.files.length === 1 && input.files[0].size === clean.size;
    } catch (error) {
      console.warn("[PrivacyGate] Could not replace input file", error);
      return false;
    }
  }

  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const a   = Object.assign(document.createElement("a"),
                  { href: url, download: name, style: "display:none" });
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
  }

  // ─────────────────────────────────────────────────────
  // AUTO REPLACE in <input type="file">
  // ─────────────────────────────────────────────────────

  async function autoReplace(blob, name, originalFile = null) {
    const key = originalFile ? fileKey(originalFile) : null;
    const inp = (key && inputByFileKey.get(key)) || lastInput || document.querySelector('input[type="file"]');
    if (!inp) return false;
    const ok = setInputFile(inp, blob, name, blob.type);
    if (!ok) return false;
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    inp.dataset.pgSkipNextChange = "1";
    inp.dispatchEvent(new Event("change", { bubbles: true }));
    lastInput = inp;
    return true;
  }

  // ─────────────────────────────────────────────────────
  // CANCEL active scan
  // Called when file is removed from input / user cancels
  // ─────────────────────────────────────────────────────

  function cancelActiveScan(reason) {
    if (activeScanId) {
      activeScanId   = null;
      activeScanFile = null;
      removeBanner();
    }
  }

  // ─────────────────────────────────────────────────────
  // BANNER
  // ─────────────────────────────────────────────────────

  const getBanner    = () => document.getElementById(BANNER_ID);
  const removeBanner = () => { const b = getBanner(); if (b) b.remove(); };

  function makeBanner() {
    removeBanner();
    const b = document.createElement("div");
    b.id = BANNER_ID;
    b.style.cssText = `
      position:fixed;top:20px;right:20px;z-index:2147483647;
      width:340px;background:#0a0a0a;border:1px solid #00f2ff;
      border-radius:12px;box-shadow:0 8px 32px rgba(0,242,255,.15);
      font-family:'Segoe UI',Arial,sans-serif;font-size:13px;
      color:#fff;overflow:hidden;user-select:none;
    `;
    document.body.appendChild(b);
    b.addEventListener("mousedown", e => {
      if (!e.target.closest(".pg-hdr")) return;
      isDragging = true;
      const r = b.getBoundingClientRect();
      dragOffX = e.clientX - r.left;
      dragOffY = e.clientY - r.top;
      e.preventDefault();
    });
    document.addEventListener("mousemove", e => {
      if (!isDragging) return;
      b.style.left  = Math.max(0, e.clientX - dragOffX) + "px";
      b.style.top   = Math.max(0, e.clientY - dragOffY) + "px";
      b.style.right = "auto";
    });
    document.addEventListener("mouseup", () => { isDragging = false; });
    return b;
  }

  function hdr(title, color) {
    return `<div class="pg-hdr" style="background:#111;padding:10px 14px;cursor:move;
      display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #222;">
      <span style="color:${color};font-weight:700;">🛡️ PrivacyGate — ${title}</span>
      <button class="pg-x" style="background:none;border:none;color:#666;font-size:16px;cursor:pointer;">×</button>
    </div>`;
  }

  function riskBadges(high, med, low) {
    return `<div style="display:flex;gap:6px;margin-bottom:10px;font-size:11px;">
      ${high>0?`<span style="background:#ff444422;color:#ff4444;padding:2px 8px;border-radius:4px;">HIGH:${high}</span>`:""}
      ${med >0?`<span style="background:#ff990022;color:#ff9900;padding:2px 8px;border-radius:4px;">MED:${med}</span>` :""}
      ${low >0?`<span style="background:#00cc8822;color:#00cc88;padding:2px 8px;border-radius:4px;">LOW:${low}</span>` :""}
    </div>`;
  }

  function setupClose(b) {
    b.querySelector(".pg-x").addEventListener("click", removeBanner);
  }

  function showScanning(name) {
    const b = makeBanner();
    b.innerHTML = `${hdr("Scanning...", "#00f2ff")}
      <div style="padding:14px;display:flex;align-items:center;gap:10px;">
        <span style="color:#00f2ff;font-size:18px;">⏳</span>
        <div>
          <div style="color:#fff;font-weight:700;">Scanning for sensitive data...</div>
          <div style="color:#555;font-size:11px;">${name}</div>
        </div>
      </div>`;
    setupClose(b);
  }

  function showClean(name) {
    const b = makeBanner();
    b.innerHTML = `${hdr("All Clear", "#00cc88")}
      <div style="padding:12px 14px;">
        <div style="color:#00cc88;font-weight:700;font-size:14px;margin-bottom:4px;">✓ No sensitive data found</div>
        <div style="color:#555;font-size:11px;">${name} — safe to send.</div>
      </div>`;
    setupClose(b);
    setTimeout(removeBanner, 4000);
  }

  function showOffline() {
    const b = makeBanner();
    b.innerHTML = `${hdr("Service Offline", "#ff9900")}
      <div style="padding:12px 14px;">
        <div style="color:#ff9900;font-weight:700;margin-bottom:4px;">⚠ PrivacyGate service offline</div>
        <div style="color:#555;font-size:11px;">
          Start it: <code style="color:#00f2ff;">python service.py run</code><br>
          Text scanning still works locally.
        </div>
      </div>`;
    setupClose(b);
    setTimeout(removeBanner, 8000);
  }

  function showTextResult(findings) {
    const high = findings.filter(f=>f.risk==="HIGH").length;
    const med  = findings.filter(f=>f.risk==="MED").length;
    const low  = findings.filter(f=>f.risk==="LOW").length;
    const col  = high>0?"#ff4444":med>0?"#ff9900":"#00f2ff";
    const b    = makeBanner();
    b.innerHTML = `${hdr(`${findings.length} PII Cleaned`, col)}
      <div style="padding:12px 14px;">
        ${riskBadges(high, med, low)}
        <div style="max-height:120px;overflow-y:auto;background:#111;border-radius:6px;padding:6px 10px;margin-bottom:10px;">
          ${findings.map(f=>`
            <div style="display:flex;justify-content:space-between;padding:3px 0;
              border-bottom:1px solid #1a1a1a;font-size:11px;">
              <span style="color:${PrivacyGateScanner.riskColor(f.risk)};font-weight:600;">${f.type}</span>
              <span style="color:#555;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                ${f.value.substring(0,28)}${f.value.length>28?"…":""}</span>
              <span style="color:#00f2ff;">→ ${f.replace}</span>
            </div>`).join("")}
        </div>
        <div style="background:#0d1f1f;border:1px solid #00f2ff33;border-radius:6px;
          padding:8px 10px;margin-bottom:10px;font-size:11px;color:#00cc88;">
          ✓ Clipboard replaced — paste again (Ctrl+V)
        </div>
        <button class="pg-x" style="width:100%;background:transparent;border:1px solid #333;
          color:#666;border-radius:6px;padding:6px;cursor:pointer;font-size:11px;">Dismiss</button>
      </div>`;
    setTimeout(removeBanner, 15000);
  }

  function showFileResult(result, filename, onAuto, onDl) {
    const col = result.high>0?"#ff4444":result.med>0?"#ff9900":"#00f2ff";
    let list  = [];
    try { list = JSON.parse(result.summary); } catch {}
    const b   = makeBanner();
    b.innerHTML = `${hdr(`${result.count} Sensitive Items`, col)}
      <div style="padding:12px 14px;">
        <div style="color:#888;font-size:11px;margin-bottom:8px;">📄 ${filename}</div>
        ${riskBadges(result.high, result.med, result.low)}
        ${list.length>0?`
        <div style="max-height:80px;overflow-y:auto;background:#111;border-radius:6px;
          padding:6px 10px;margin-bottom:10px;">
          ${list.map(f=>`
            <div style="display:flex;justify-content:space-between;padding:3px 0;
              border-bottom:1px solid #1a1a1a;font-size:11px;">
              <span style="color:${f.risk==="HIGH"?"#ff4444":f.risk==="MED"?"#ff9900":"#00cc88"};
                font-weight:600;">${f.type}</span>
              <span style="color:#00f2ff;font-size:10px;">→ ${f.replace}</span>
            </div>`).join("")}
        </div>`:""}
        <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:10px;">
          <button id="pg-auto" style="background:#00f2ff;border:none;color:#000;
            border-radius:8px;padding:9px 14px;cursor:pointer;font-weight:700;
            font-size:12px;text-align:left;">
            ⚡ Auto-Replace — Use clean file directly
          </button>
          <button id="pg-dl" style="background:#0d1f1f;border:1px solid #00f2ff44;
            color:#00f2ff;border-radius:8px;padding:9px 14px;cursor:pointer;
            font-weight:600;font-size:12px;text-align:left;">
            ↓ Download Clean File — Upload manually
          </button>
        </div>
        <div id="pg-st" style="font-size:11px;color:#666;text-align:center;
          min-height:16px;margin-bottom:6px;"></div>
        <button class="pg-x" style="width:100%;background:transparent;border:1px solid #333;
          color:#666;border-radius:6px;padding:6px;cursor:pointer;font-size:11px;">Dismiss</button>
      </div>`;
    setupClose(b);
    const st = b.querySelector("#pg-st");
    b.querySelector("#pg-auto").addEventListener("click", async () => {
      st.style.color = "#00f2ff";
      st.textContent = "Replacing...";
      const ok = await onAuto();
      st.style.color = ok ? "#00cc88" : "#ff9900";
      st.textContent = ok ? "✓ Replaced — file is now clean!" : "Auto-replace failed — use Download instead.";
      if (ok) setTimeout(removeBanner, 2000);
    });
    b.querySelector("#pg-dl").addEventListener("click", () => {
      onDl();
      st.style.color = "#00cc88";
      st.textContent = "✓ Download started.";
    });
    setTimeout(removeBanner, 30000);
  }

  // ─────────────────────────────────────────────────────
  // CORE FILE HANDLER
  // ─────────────────────────────────────────────────────

  async function handleFile(file, replaceInInput) {
    if (!pgEnabled || !canIntercept(file.name)) return;

    // Cancel any previous scan
    cancelActiveScan("new file");

    // Register this scan
    const scanId = newScanId();
    const abortCtrl = new AbortController();
    activeScanId   = scanId;
    activeScanFile = file.name;

    showScanning(file.name);

    try {
      const result = await scanFile(file, abortCtrl.signal);

      // If this scan was cancelled while waiting, do nothing
      if (activeScanId !== scanId) return;

      activeScanId   = null;
      activeScanFile = null;
      removeBanner();

      if (result.count === 0) { showClean(file.name); return; }

      const cleanName = `PrivacyGate_Cleaned_${file.name}`;
      showFileResult(result, file.name,
async () => {
          const ok = await autoReplace(result.blob, file.name, file);
          if (!ok && replaceInInput) await replaceInInput(result.blob, file.name);
          return ok;
        },
        () => download(result.blob, cleanName)
      );

    } catch (e) {
      if (e.name === "AbortError") return; // Scan cancelled — silent
      if (activeScanId !== scanId) return;
      activeScanId   = null;
      activeScanFile = null;
      removeBanner();
      // Show offline only if it's a network error
      if (e.message.includes("fetch") || e.message.includes("Failed") || e.message.includes("NetworkError")) {
        showOffline();
      }
    }
  }

  // ─────────────────────────────────────────────────────
  // 1. TEXT PASTE
  // ─────────────────────────────────────────────────────

  document.addEventListener("paste", async e => {
    if (!pgEnabled) return;
    const items   = Array.from((e.clipboardData || window.clipboardData).items || []);
    const imgItem = items.find(i => i.kind === "file" && i.type.startsWith("image/"));
    if (imgItem) {
      const file = imgItem.getAsFile();
      if (file) {
        e.preventDefault();
        e.stopPropagation();
        const ext  = file.type.split("/")[1] || "png";
        const named = new File([file], `clipboard_image.${ext}`, { type: file.type });
        await handleFile(named, null);
        return;
      }
    }
    const target = e.target;
    const isEditable = (
      target.tagName === "INPUT" || target.tagName === "TEXTAREA" ||
      target.isContentEditable  || target.getAttribute("contenteditable") === "true"
    );
    if (!isEditable) return;
    lastEditableTarget = target;
    let text = "";
    try { text = (e.clipboardData || window.clipboardData).getData("text/plain"); } catch { return; }
    if (!text || text.trim().length < 4) return;
    if (cleanedClipboard && Date.now() < cleanedClipboard.expires && text === cleanedClipboard.original) {
      e.preventDefault();
      e.stopPropagation();
      try { await navigator.clipboard.writeText(cleanedClipboard.cleaned); } catch (_) {}
      try { document.execCommand("insertText", false, cleanedClipboard.cleaned); } catch (_) {}
      cleanedClipboard = null;
      return;
    }
    const findings = PrivacyGateScanner.scanText(text);
    if (findings.length === 0) return;
    e.preventDefault();
    e.stopPropagation();
    const cleaned = PrivacyGateScanner.cleanText(text, findings);
    cleanedClipboard = { original: text, cleaned, expires: Date.now() + 30000 };
    chrome.runtime.sendMessage({ type: "TEXT_CLEANED", cleaned, findings }).catch(() => {});
    try {
      await navigator.clipboard.writeText(cleaned);
    } catch {
      try { document.execCommand("insertText", false, cleaned); } catch {}
    }
    showTextResult(findings);
  }, true);

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message) return;
    if (message.type === "INSERT_CLEAN_FILE") {
      const input = lastInput && document.contains(lastInput) ? lastInput : document.querySelector('input[type="file"]');
      if (!input || !message.file) {
        sendResponse({ ok: false, error: "Select a file input on the source page first" });
        return true;
      }
      try {
        const clean = message.file instanceof File
          ? message.file
          : new File([message.file], message.name || "PrivacyGate_Cleaned_File", { type: message.mime || "application/octet-stream", lastModified: Date.now() });
        const transfer = new DataTransfer();
        transfer.items.add(clean);
        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files");
        if (!descriptor || !descriptor.set) throw new Error("FileList assignment is unsupported");
        descriptor.set.call(input, transfer.files);
        input.dataset.pgSkipNextChange = "1";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        sendResponse({ ok: true, name: clean.name, size: clean.size });
      } catch (error) {
        sendResponse({ ok: false, error: error.message });
      }
      return true;
    }
    if (message.type !== "INSERT_CLEAN_TEXT") return;
    const text = String(message.text || "");
    let inserted = false;
    const target = lastEditableTarget && document.contains(lastEditableTarget) ? lastEditableTarget : document.activeElement;
    try {
      if (target && (target.isContentEditable || target.tagName === "TEXTAREA" || target.tagName === "INPUT")) {
        target.focus();
        if (target.isContentEditable) {
          inserted = document.execCommand("insertText", false, text);
          if (!inserted) target.textContent += text;
        } else {
          const start = typeof target.selectionStart === "number" ? target.selectionStart : target.value.length;
          const end = typeof target.selectionEnd === "number" ? target.selectionEnd : target.value.length;
          target.setRangeText(text, start, end, "end");
          target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
          inserted = true;
        }
      }
    } catch (error) {
      console.warn("[PrivacyGate] direct Auto-Paste insertion failed", error);
    }
    if (!inserted) {
      navigator.clipboard.writeText(text).then(() => showClean("Cleaned text copied; press Ctrl+V")).catch(() => {});
    }
    sendResponse({ ok: inserted, fallbackClipboard: !inserted });
    return true;
  });

  // ─────────────────────────────────────────────────────
  // 2. FILE INPUT CHANGE
  // ─────────────────────────────────────────────────────

  async function mapWithLimit(items, limit, worker) {
    const output = new Array(items.length);
    let cursor = 0;
    async function run() {
      while (true) {
        const index = cursor++;
        if (index >= items.length) return;
        output[index] = await worker(items[index], index);
      }
    }
    await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
    return output;
  }

  function showBatchResult(results) {
    const findings = results.reduce((sum, item) => sum + item.count, 0);
    const high = results.reduce((sum, item) => sum + item.high, 0);
    const med = results.reduce((sum, item) => sum + item.med, 0);
    const low = results.reduce((sum, item) => sum + item.low, 0);
    const b = makeBanner();
    const color = high ? "#ff4444" : med ? "#ff9900" : "#00cc88";
    b.innerHTML = `${hdr(findings ? `${findings} PII Cleaned` : "All Clear", color)}
      <div style="padding:12px 14px;">
        <div style="color:${color};font-weight:700;margin-bottom:8px;">${results.length} file${results.length === 1 ? "" : "s"} scanned</div>
        ${riskBadges(high, med, low)}
        <div style="color:#00cc88;font-size:11px;">✓ Clean versions are being used for upload.</div>
      </div>`;
    setupClose(b);
    setTimeout(removeBanner, 5000);
  }

  function reportFileEvent(event) {
    chrome.runtime.sendMessage({ type: "FILE_SCAN_EVENT", event }).catch(() => {});
  }

  async function scanAndReplaceInput(inp, files) {
    const selected = files.filter(file => canIntercept(file.name));
    if (!selected.length) return;
    selected.forEach(file => inputByFileKey.set(fileKey(file), inp));
    showScanning(`${selected.length} file${selected.length === 1 ? "" : "s"}`);
    selected.forEach(file => reportFileEvent({ kind: "file", name: file.name, status: "scanning", detail: "Scanning" }));
    const results = await mapWithLimit(selected, 2, async file => {
      const result = await scanFile(file);
      reportFileEvent({ kind: "file", name: file.name, status: "cleaned", findings: result.count, detail: `${result.count} sensitive item(s)` });
      return result;
    });
    const cleanedFiles = results.map((result, index) => new File([result.blob], selected[index].name, {
      type: selected[index].type || result.blob.type || "application/octet-stream",
      lastModified: Date.now()
    }));
    const transfer = new DataTransfer();
    cleanedFiles.forEach(file => transfer.items.add(file));
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files");
    if (!descriptor || !descriptor.set) throw new Error("Browser cannot replace FileList");
    descriptor.set.call(inp, transfer.files);
    inp.dataset.pgSkipNextChange = "1";
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    inp.dispatchEvent(new Event("change", { bubbles: true }));
    removeBanner();
    showBatchResult(results);
  }

  function attachToInput(inp) {
    if (inp.__pg) return;
    inp.__pg = true;
    inp.addEventListener("click", () => { lastInput = inp; }, true);

    inp.addEventListener("change", async e => {
      if (inp.dataset.pgSkipNextChange === "1") {
        delete inp.dataset.pgSkipNextChange;
        return;
      }
      // File removed (input cleared) — cancel any active scan
      if (!inp.files || inp.files.length === 0) {
        cancelActiveScan("input cleared");
        return;
      }
      const files = Array.from(inp.files);
      lastInput = inp;
      if (!pgEnabled || !files.some(file => canIntercept(file.name))) return;
      // Stop the host app's change listener from seeing originals. The clean
      // FileList is dispatched after bounded-concurrency scanning completes.
      e.preventDefault();
      e.stopImmediatePropagation();
      try {
        await scanAndReplaceInput(inp, files);
      } catch (error) {
        inp.value = "";
        removeBanner();
        showOffline();
        console.warn("[PrivacyGate] Multi-file scan blocked upload", error);
      }
    }, true);
  }

  document.querySelectorAll('input[type="file"]').forEach(attachToInput);

  new MutationObserver(ms => {
    for (const m of ms) {
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.tagName === "INPUT" && n.type === "file") attachToInput(n);
        n.querySelectorAll && n.querySelectorAll('input[type="file"]').forEach(attachToInput);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  // ─────────────────────────────────────────────────────
  // 3. DRAG AND DROP
  // ─────────────────────────────────────────────────────

  document.addEventListener("dragover", e => {
    if (e.dataTransfer && e.dataTransfer.types.includes("Files")) {
      // no-op — just track target
    }
  }, true);

  document.addEventListener("drop", async e => {
    if (!pgEnabled || e.__privacyGateCleanDrop) return;
    const files = e.dataTransfer && Array.from(e.dataTransfer.files || []);
    if (!files.length || !files.some(file => canIntercept(file.name))) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    try {
      const selected = files.filter(file => canIntercept(file.name));
      selected.forEach(file => reportFileEvent({ kind: "file", name: file.name, status: "scanning", detail: "Scanning" }));
      const results = await mapWithLimit(selected, 2, async file => {
        const result = await scanFile(file);
        reportFileEvent({ kind: "file", name: file.name, status: "cleaned", findings: result.count, detail: `${result.count} sensitive item(s)` });
        return result;
      });
      const transfer = new DataTransfer();
      results.forEach((result, index) => transfer.items.add(new File([result.blob], selected[index].name, {
        type: selected[index].type || result.blob.type || "application/octet-stream",
        lastModified: Date.now()
      })));
      const cleanDrop = new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer });
      Object.defineProperty(cleanDrop, "__privacyGateCleanDrop", { value: true });
      e.target.dispatchEvent(cleanDrop);
      showBatchResult(results);
    } catch (error) {
      removeBanner();
      showOffline();
      console.warn("[PrivacyGate] Multi-file drop blocked", error);
    }
  }, true);

  // ─────────────────────────────────────────────────────
  // 4. XHR INTERCEPT
  // ─────────────────────────────────────────────────────

  const _XHRSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(body) {
    if (internalApiDepth > 0 || !pgEnabled || !(body instanceof FormData)) {
      return _XHRSend.apply(this, [body]);
    }
    let file = null;
    for (const [, v] of body.entries()) {
      if (v instanceof File && canIntercept(v.name)) { file = v; break; }
    }
    if (!file) return _XHRSend.apply(this, [body]);

    const xhr = this;
    const abortCtrl = new AbortController();
    const scanId    = newScanId();
    cancelActiveScan("xhr");
    activeScanId   = scanId;
    activeScanFile = file.name;

    showScanning(file.name);

    (async () => {
      try {
        const result = await scanFile(file, abortCtrl.signal);
        if (activeScanId !== scanId) return;
        activeScanId = null;
        removeBanner();

        if (result.count === 0) {
          showClean(file.name);
          _XHRSend.apply(xhr, [body]);
          return;
        }

        const newFD = new FormData();
        for (const [k, v] of body.entries()) {
          if (v instanceof File && v.name === file.name) {
            newFD.append(k, new File([result.blob], v.name, { type: v.type }), v.name);
          } else {
            newFD.append(k, v);
          }
        }

        showFileResult(result, file.name,
          async () => { _XHRSend.apply(xhr, [newFD]); return true; },
          ()      => {
            download(result.blob, `PrivacyGate_Cleaned_${file.name}`);
            _XHRSend.apply(xhr, [body]);
          }
        );
      } catch (e) {
        if (e.name === "AbortError") return;
        if (activeScanId !== scanId) return;
        activeScanId = null;
        removeBanner();
        _XHRSend.apply(xhr, [body]);
      }
    })();
  };

  // ─────────────────────────────────────────────────────
  // 5. FETCH INTERCEPT
  // ─────────────────────────────────────────────────────

  const _fetch = window.fetch.bind(window);
  window.fetch = async function(input, init) {
    if (internalApiDepth > 0 || !pgEnabled || !init || !(init.body instanceof FormData)) {
      return _fetch(input, init);
    }
    let file = null;
    for (const [, v] of init.body.entries()) {
      if (v instanceof File && canIntercept(v.name)) { file = v; break; }
    }
    if (!file) return _fetch(input, init);

    const abortCtrl = new AbortController();
    const scanId    = newScanId();
    cancelActiveScan("fetch");
    activeScanId   = scanId;
    activeScanFile = file.name;

    showScanning(file.name);

    try {
      const result = await scanFile(file, abortCtrl.signal);
      if (activeScanId !== scanId) return _fetch(input, init);
      activeScanId = null;
      removeBanner();

      if (result.count === 0) {
        showClean(file.name);
        return _fetch(input, init);
      }

      return new Promise(resolve => {
        const newFD = new FormData();
        for (const [k, v] of init.body.entries()) {
          if (v instanceof File && v.name === file.name) {
            newFD.append(k, new File([result.blob], v.name, { type: v.type }), v.name);
          } else {
            newFD.append(k, v);
          }
        }
        showFileResult(result, file.name,
          async () => { resolve(await _fetch(input, { ...init, body: newFD })); return true; },
          async () => {
            download(result.blob, `PrivacyGate_Cleaned_${file.name}`);
            resolve(await _fetch(input, init));
          }
        );
      });
    } catch (e) {
      if (activeScanId !== scanId) return _fetch(input, init);
      activeScanId = null;
      removeBanner();
      return _fetch(input, init);
    }
  };

  // ─────────────────────────────────────────────────────
  // MAIN-WORLD UPLOAD BRIDGE RELAY
  // page-bridge.js sends FormData files here because the page world cannot
  // access chrome APIs or the extension's isolated-world state.
  // ─────────────────────────────────────────────────────
  const PG_BRIDGE_SOURCE = "privacygate-v1";

  window.addEventListener("message", async e => {
    if (e.source !== window || !e.data || e.data.source !== PG_BRIDGE_SOURCE) return;
    const msg = e.data;
    if (!msg.token || msg.kind !== "privacygate-scan-request") return;
    if (!Array.isArray(msg.files) || !msg.files.length) return;

    try {
      if (!pgEnabled) throw new Error("PrivacyGate is disabled");
      const cleaned = await mapWithLimit(msg.files, 2, async file => {
        if (!(file instanceof File) && !(file instanceof Blob)) throw new Error("Invalid upload object");
        const named = file instanceof File ? file : new File([file], "upload", { type: file.type || "application/octet-stream" });
        reportFileEvent({ kind: "file", name: named.name, status: "scanning", detail: "Scanning" });
        showScanning(named.name);
        const result = await scanFile(named, undefined);
        const clean = new File([result.blob], named.name, {
          type: named.type || result.blob.type || "application/octet-stream",
          lastModified: Date.now()
        });
        reportFileEvent({ kind: "file", name: named.name, status: "cleaned", findings: result.count, detail: `${result.count} sensitive item(s)` });
        if (result.count === 0) showClean(named.name);
        return clean;
      });
      window.postMessage({
        source: PG_BRIDGE_SOURCE,
        token: msg.token,
        kind: "privacygate-scan-response",
        id: msg.id,
        files: cleaned
      }, "*");
    } catch (err) {
      removeBanner();
      showOffline();
      window.postMessage({
        source: PG_BRIDGE_SOURCE,
        token: msg.token,
        kind: "privacygate-scan-response",
        id: msg.id,
        error: err && err.message ? err.message : "PrivacyGate scan failed"
      }, "*");
    }
  }, true);

})();
