/**
 * content.js — PrivacyGate
 * Handles ALL input methods on ALL websites:
 * 1. Text paste (Ctrl+V)
 * 2. Image paste from clipboard (screenshot)
 * 3. File input change (<input type="file">)
 * 4. Drag and drop files
 * 5. XHR FormData intercept (ChatGPT, etc.)
 * 6. fetch() FormData intercept
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

  let pgEnabled    = true;
  let lastInput    = null;
  let dragTarget   = null;
  let isDragging   = false;
  let dragOffX     = 0;
  let dragOffY     = 0;

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

  const getExt        = n => (n||"").split(".").pop().toLowerCase();
  const canIntercept  = n => INTERCEPT_EXT.has(getExt(n));

  async function serviceOnline() {
    try {
      const r = await fetch(`${API_BASE}/status`, { signal: AbortSignal.timeout(2000) });
      return r.ok;
    } catch { return false; }
  }

  async function scanFile(file) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("sensitivity", "standard");
    const r = await fetch(`${API_BASE}/scan-file`, { method: "POST", body: fd });
    if (!r.ok) throw new Error(`API ${r.status}`);
    return {
      blob:     await r.blob(),
      count:    parseInt(r.headers.get("X-Findings-Count") || "0"),
      high:     parseInt(r.headers.get("X-High-Count")     || "0"),
      med:      parseInt(r.headers.get("X-Med-Count")      || "0"),
      low:      parseInt(r.headers.get("X-Low-Count")      || "0"),
      types:    r.headers.get("X-Types-Found")             || "",
      summary:  r.headers.get("X-Findings-Summary")        || "[]",
    };
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

  async function autoReplace(blob, name) {
    const inp = lastInput || document.querySelector('input[type="file"]');
    if (!inp) return false;
    try {
      const f  = new File([blob], name, { type: blob.type, lastModified: Date.now() });
      const dt = new DataTransfer();
      dt.items.add(f);
      Object.defineProperty(inp, "files", { value: dt.files, writable: true, configurable: true });
      inp.dispatchEvent(new Event("change", { bubbles: true }));
      inp.dispatchEvent(new Event("input",  { bubbles: true }));
      return true;
    } catch { return false; }
  }

  // ─────────────────────────────────────────────────────
  // BANNER
  // ─────────────────────────────────────────────────────

  const getBanner    = ()  => document.getElementById(BANNER_ID);
  const removeBanner = ()  => { const b = getBanner(); if(b) b.remove(); };

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

    // drag
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

  // ── Scanning ────────────────────────────────────────

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

  // ── Clean ───────────────────────────────────────────

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

  // ── Offline ─────────────────────────────────────────

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

  // ── Text result ─────────────────────────────────────

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

  // ── File result ─────────────────────────────────────

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
      st.style.color   = "#00f2ff";
      st.textContent   = "Replacing...";
      const ok = await onAuto();
      st.style.color   = ok ? "#00cc88" : "#ff9900";
      st.textContent   = ok ? "✓ Replaced — file is now clean!" : "Auto-replace failed — use Download instead.";
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
  // Called from every interception path
  // ─────────────────────────────────────────────────────

  async function handleFile(file, replaceInInput) {
    if (!pgEnabled || !canIntercept(file.name)) return;

    const online = await serviceOnline();
    if (!online) { showOffline(); return; }

    showScanning(file.name);

    try {
      const result = await scanFile(file);
      removeBanner();

      if (result.count === 0) { showClean(file.name); return; }

      const cleanName = `PrivacyGate_Cleaned_${file.name}`;

      showFileResult(result, file.name,
        async () => {
          // Auto-replace
          const ok = await autoReplace(result.blob, file.name);
          if (!ok && replaceInInput) await replaceInInput(result.blob, file.name);
          return ok;
        },
        () => download(result.blob, cleanName)
      );

    } catch (e) {
      removeBanner();
      console.error("PrivacyGate:", e);
      showOffline();
    }
  }

  // ─────────────────────────────────────────────────────
  // 1. TEXT PASTE
  // ─────────────────────────────────────────────────────

  document.addEventListener("paste", async e => {
    if (!pgEnabled) return;

    // Image paste (screenshot copied to clipboard)
    const items = Array.from((e.clipboardData || window.clipboardData).items || []);
    const imgItem = items.find(i => i.kind==="file" && i.type.startsWith("image/"));
    if (imgItem) {
      const file = imgItem.getAsFile();
      if (file) {
        e.preventDefault();
        e.stopPropagation();
        // Give the image a proper name
        const ext  = file.type.split("/")[1] || "png";
        const named = new File([file], `clipboard_image.${ext}`, { type: file.type });
        await handleFile(named, null);
        return;
      }
    }

    // Text paste
    const target = e.target;
    const isEditable = (
      target.tagName === "INPUT"    ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable      ||
      target.getAttribute("contenteditable") === "true"
    );
    if (!isEditable) return;

    let text = "";
    try { text = (e.clipboardData || window.clipboardData).getData("text/plain"); } catch { return; }
    if (!text || text.trim().length < 4) return;

    const findings = PrivacyGateScanner.scanText(text);
    if (findings.length === 0) return;

    e.preventDefault();
    e.stopPropagation();

    const cleaned = PrivacyGateScanner.cleanText(text, findings);

    try {
      await navigator.clipboard.writeText(cleaned);
    } catch {
      try { document.execCommand("insertText", false, cleaned); } catch {}
    }

    showTextResult(findings);
  }, true);

  // ─────────────────────────────────────────────────────
  // 2. FILE INPUT CHANGE
  // ─────────────────────────────────────────────────────

  function attachToInput(inp) {
    if (inp.__pg) return;
    inp.__pg = true;
    inp.addEventListener("click",  () => { lastInput = inp; }, true);
    inp.addEventListener("change", async e => {
      const f = inp.files && inp.files[0];
      if (f) await handleFile(f, null);
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
      dragTarget = e.target;
    }
  }, true);

  document.addEventListener("drop", async e => {
    if (!pgEnabled) return;
    const files = e.dataTransfer && e.dataTransfer.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    if (!canIntercept(file.name)) return;
    e.preventDefault();
    e.stopPropagation();
    await handleFile(file, null);
  }, true);

  // ─────────────────────────────────────────────────────
  // 4. XHR INTERCEPT
  // Wraps XMLHttpRequest.send — catches ChatGPT-style uploads
  // ─────────────────────────────────────────────────────

  const _XHRSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(body) {
    if (!pgEnabled || !(body instanceof FormData)) {
      return _XHRSend.apply(this, [body]);
    }
    let file = null;
    for (const [, v] of body.entries()) {
      if (v instanceof File && canIntercept(v.name)) { file = v; break; }
    }
    if (!file) return _XHRSend.apply(this, [body]);

    const xhr = this;
    (async () => {
      const online = await serviceOnline();
      if (!online) { showOffline(); _XHRSend.apply(xhr, [body]); return; }

      showScanning(file.name);
      try {
        const result = await scanFile(file);
        removeBanner();
        if (result.count === 0) { showClean(file.name); _XHRSend.apply(xhr, [body]); return; }

        // Replace file in FormData
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
          ()      => { download(result.blob, `PrivacyGate_Cleaned_${file.name}`);
                       _XHRSend.apply(xhr, [body]); }
        );
      } catch {
        removeBanner();
        _XHRSend.apply(xhr, [body]);
      }
    })();
  };

  // ─────────────────────────────────────────────────────
  // 5. FETCH INTERCEPT
  // Wraps window.fetch — catches modern React-based uploads
  // ─────────────────────────────────────────────────────

  const _fetch = window.fetch.bind(window);
  window.fetch = async function(input, init) {
    if (!pgEnabled || !init || !(init.body instanceof FormData)) {
      return _fetch(input, init);
    }
    let file = null;
    for (const [, v] of init.body.entries()) {
      if (v instanceof File && canIntercept(v.name)) { file = v; break; }
    }
    if (!file) return _fetch(input, init);

    const online = await serviceOnline();
    if (!online) { showOffline(); return _fetch(input, init); }

    showScanning(file.name);
    try {
      const result = await scanFile(file);
      removeBanner();
      if (result.count === 0) { showClean(file.name); return _fetch(input, init); }

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
    } catch {
      removeBanner();
      return _fetch(input, init);
    }
  };

})();