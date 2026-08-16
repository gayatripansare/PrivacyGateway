/**
 * content.js
 * PrivacyGate — Content Script
 *
 * Runs on every website, every page.
 * Intercepts:
 *   - Text paste (Ctrl+V) on any input / contenteditable
 *   - File uploads (<input type="file">)
 *   - Drag and drop files onto any element
 *
 * For text: scans locally using scanner.js, replaces clipboard with clean version
 * For files: sends to PrivacyGate service at localhost:8000/scan-file
 *            shows banner with:
 *              - What was found and cleaned
 *              - AUTO-REPLACE button (DataTransfer trick)
 *              - DOWNLOAD button (always works)
 */

(() => {
  "use strict";

  const API_BASE    = "http://127.0.0.1:8000";
  const BANNER_ID   = "privacygate-banner";
  const STORAGE_KEY = "privacygate_enabled";

  // ─────────────────────────────────────────────────────
  // STATE
  // ─────────────────────────────────────────────────────

  let pgEnabled       = true;   // toggled from popup
  let lastFileInput   = null;   // the <input type="file"> the user clicked
  let dragTargetInput = null;   // the element being dragged onto
  let bannerDragging  = false;
  let bannerDragOffX  = 0;
  let bannerDragOffY  = 0;

  // Load enabled state from storage
  chrome.storage.local.get([STORAGE_KEY], (res) => {
    pgEnabled = res[STORAGE_KEY] !== false; // default true
  });

  chrome.storage.onChanged.addListener((changes) => {
    if (changes[STORAGE_KEY]) {
      pgEnabled = changes[STORAGE_KEY].newValue !== false;
    }
  });

  // ─────────────────────────────────────────────────────
  // SERVICE AVAILABILITY CHECK
  // ─────────────────────────────────────────────────────

  async function isServiceRunning() {
    try {
      const res = await fetch(`${API_BASE}/status`, {
        signal: AbortSignal.timeout(2000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  // ─────────────────────────────────────────────────────
  // BANNER — floating, draggable
  // ─────────────────────────────────────────────────────

  function getBanner() {
    return document.getElementById(BANNER_ID);
  }

  function removeBanner() {
    const b = getBanner();
    if (b) b.remove();
  }

  function createBanner() {
    removeBanner();

    const banner = document.createElement("div");
    banner.id = BANNER_ID;
    banner.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 2147483647;
      width: 340px;
      background: #0a0a0a;
      border: 1px solid #00f2ff;
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,242,255,0.15), 0 2px 8px rgba(0,0,0,0.8);
      font-family: 'Segoe UI', Arial, sans-serif;
      font-size: 13px;
      color: #ffffff;
      overflow: hidden;
      user-select: none;
    `;

    document.body.appendChild(banner);
    return banner;
  }

  function makeBannerDraggable(banner) {
    const header = banner.querySelector(".pg-drag-handle");
    if (!header) return;

    header.addEventListener("mousedown", (e) => {
      bannerDragging = true;
      const rect = banner.getBoundingClientRect();
      bannerDragOffX = e.clientX - rect.left;
      bannerDragOffY = e.clientY - rect.top;
      e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
      if (!bannerDragging) return;
      const x = e.clientX - bannerDragOffX;
      const y = e.clientY - bannerDragOffY;
      banner.style.left  = `${Math.max(0, x)}px`;
      banner.style.top   = `${Math.max(0, y)}px`;
      banner.style.right = "auto";
    });

    document.addEventListener("mouseup", () => {
      bannerDragging = false;
    });
  }

  // ─────────────────────────────────────────────────────
  // SHOW SCAN RESULT BANNER
  // Used for both text and file scan results
  // ─────────────────────────────────────────────────────

  function showTextBanner(findings, cleanedText) {
    const banner = createBanner();

    const high = findings.filter(f => f.risk === "HIGH").length;
    const med  = findings.filter(f => f.risk === "MED").length;
    const low  = findings.filter(f => f.risk === "LOW").length;

    const headerColor = high > 0 ? "#ff4444" : med > 0 ? "#ff9900" : "#00f2ff";

    banner.innerHTML = `
      <div class="pg-drag-handle" style="
        background: #111;
        padding: 10px 14px;
        cursor: move;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #222;
      ">
        <span style="color: #00f2ff; font-weight: 700; font-size: 13px;">
          🛡️ PrivacyGate
        </span>
        <button id="pg-close" style="
          background: none; border: none; color: #666;
          font-size: 16px; cursor: pointer; padding: 0 4px;
        ">×</button>
      </div>

      <div style="padding: 12px 14px;">
        <div style="
          color: ${headerColor};
          font-weight: 700;
          font-size: 14px;
          margin-bottom: 8px;
        ">
          ⚠ ${findings.length} sensitive item${findings.length !== 1 ? "s" : ""} found & cleaned
        </div>

        <div style="
          display: flex; gap: 8px; margin-bottom: 10px;
          font-size: 11px;
        ">
          ${high > 0 ? `<span style="background:#ff444422;color:#ff4444;padding:2px 8px;border-radius:4px;">HIGH: ${high}</span>` : ""}
          ${med  > 0 ? `<span style="background:#ff990022;color:#ff9900;padding:2px 8px;border-radius:4px;">MED: ${med}</span>`  : ""}
          ${low  > 0 ? `<span style="background:#00cc8822;color:#00cc88;padding:2px 8px;border-radius:4px;">LOW: ${low}</span>`  : ""}
        </div>

        <div style="
          max-height: 110px;
          overflow-y: auto;
          margin-bottom: 10px;
          background: #111;
          border-radius: 6px;
          padding: 6px 10px;
        ">
          ${findings.map(f => `
            <div style="
              display: flex;
              justify-content: space-between;
              padding: 3px 0;
              border-bottom: 1px solid #1a1a1a;
              font-size: 11px;
            ">
              <span style="color: ${PrivacyGateScanner.riskColor(f.risk)}; font-weight: 600;">
                ${f.type}
              </span>
              <span style="color: #555; font-size: 10px; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                ${f.value.substring(0, 30)}${f.value.length > 30 ? "…" : ""}
              </span>
              <span style="color: #00f2ff; font-size: 10px;">→ ${f.replace}</span>
            </div>
          `).join("")}
        </div>

        <div style="
          background: #0d1f1f;
          border: 1px solid #00f2ff33;
          border-radius: 6px;
          padding: 8px 10px;
          margin-bottom: 10px;
          font-size: 11px;
          color: #00cc88;
        ">
          ✓ Clipboard replaced with clean version — paste again (Ctrl+V)
        </div>

        <button id="pg-dismiss" style="
          width: 100%;
          background: transparent;
          border: 1px solid #333;
          color: #666;
          border-radius: 6px;
          padding: 6px;
          cursor: pointer;
          font-size: 11px;
        ">Dismiss</button>
      </div>
    `;

    makeBannerDraggable(banner);

    banner.querySelector("#pg-close").addEventListener("click", removeBanner);
    banner.querySelector("#pg-dismiss").addEventListener("click", removeBanner);

    // Auto-dismiss after 15 seconds
    setTimeout(removeBanner, 15000);
  }

  function showFileBanner(findings, cleanedFileBlob, originalFilename, summary) {
    const banner = createBanner();

    const high = summary.high_count || 0;
    const med  = summary.med_count  || 0;
    const low  = summary.low_count  || 0;
    const total = summary.findings_count || 0;

    const headerColor = high > 0 ? "#ff4444" : med > 0 ? "#ff9900" : "#00f2ff";
    const cleanFilename = `PrivacyGate_Cleaned_${originalFilename}`;

    // Create object URL for the cleaned file blob
    const cleanedUrl = URL.createObjectURL(cleanedFileBlob);

    // Parse findings summary from header
    let findingsList = [];
    try {
      findingsList = JSON.parse(summary.findings_summary || "[]");
    } catch { findingsList = []; }

    banner.innerHTML = `
      <div class="pg-drag-handle" style="
        background: #111;
        padding: 10px 14px;
        cursor: move;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #222;
      ">
        <span style="color: #00f2ff; font-weight: 700; font-size: 13px;">
          🛡️ PrivacyGate
        </span>
        <button id="pg-close" style="
          background: none; border: none; color: #666;
          font-size: 16px; cursor: pointer; padding: 0 4px;
        ">×</button>
      </div>

      <div style="padding: 12px 14px;">
        <div style="
          color: ${headerColor};
          font-weight: 700;
          font-size: 14px;
          margin-bottom: 6px;
        ">
          ⚠ ${total} sensitive item${total !== 1 ? "s" : ""} found in file
        </div>

        <div style="color: #888; font-size: 11px; margin-bottom: 8px;">
          📄 ${originalFilename}
        </div>

        <div style="
          display: flex; gap: 8px; margin-bottom: 10px;
          font-size: 11px;
        ">
          ${high > 0 ? `<span style="background:#ff444422;color:#ff4444;padding:2px 8px;border-radius:4px;">HIGH: ${high}</span>` : ""}
          ${med  > 0 ? `<span style="background:#ff990022;color:#ff9900;padding:2px 8px;border-radius:4px;">MED: ${med}</span>`  : ""}
          ${low  > 0 ? `<span style="background:#00cc8822;color:#00cc88;padding:2px 8px;border-radius:4px;">LOW: ${low}</span>`  : ""}
        </div>

        ${findingsList.length > 0 ? `
        <div style="
          max-height: 90px;
          overflow-y: auto;
          margin-bottom: 10px;
          background: #111;
          border-radius: 6px;
          padding: 6px 10px;
        ">
          ${findingsList.map(f => `
            <div style="
              display: flex;
              justify-content: space-between;
              padding: 3px 0;
              border-bottom: 1px solid #1a1a1a;
              font-size: 11px;
            ">
              <span style="color: ${f.risk === "HIGH" ? "#ff4444" : f.risk === "MED" ? "#ff9900" : "#00cc88"}; font-weight: 600;">
                ${f.type}
              </span>
              <span style="color: #00f2ff; font-size: 10px;">→ ${f.replace}</span>
            </div>
          `).join("")}
        </div>` : ""}

        <div style="
          font-size: 11px;
          color: #888;
          margin-bottom: 10px;
          padding: 6px 10px;
          background: #111;
          border-radius: 6px;
        ">
          Choose how to use the cleaned file:
        </div>

        <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px;">

          <button id="pg-auto-replace" style="
            background: #00f2ff;
            border: none;
            color: #000;
            border-radius: 8px;
            padding: 9px 14px;
            cursor: pointer;
            font-weight: 700;
            font-size: 12px;
            text-align: left;
          ">
            ⚡ Auto-Replace — Use clean file in upload
          </button>

          <a id="pg-download" href="${cleanedUrl}" download="${cleanFilename}" style="
            display: block;
            background: #0d1f1f;
            border: 1px solid #00f2ff44;
            color: #00f2ff;
            border-radius: 8px;
            padding: 9px 14px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            text-decoration: none;
            text-align: left;
          ">
            ↓ Download Clean File — Upload it manually
          </a>

        </div>

        <div id="pg-replace-status" style="
          font-size: 11px;
          color: #666;
          text-align: center;
          min-height: 16px;
          margin-bottom: 6px;
        "></div>

        <button id="pg-dismiss" style="
          width: 100%;
          background: transparent;
          border: 1px solid #333;
          color: #666;
          border-radius: 6px;
          padding: 6px;
          cursor: pointer;
          font-size: 11px;
        ">Dismiss</button>
      </div>
    `;

    makeBannerDraggable(banner);

    banner.querySelector("#pg-close").addEventListener("click", () => {
      URL.revokeObjectURL(cleanedUrl);
      removeBanner();
    });

    banner.querySelector("#pg-dismiss").addEventListener("click", () => {
      URL.revokeObjectURL(cleanedUrl);
      removeBanner();
    });

    // AUTO-REPLACE button
    banner.querySelector("#pg-auto-replace").addEventListener("click", async () => {
      const statusEl = banner.querySelector("#pg-replace-status");
      statusEl.style.color = "#00f2ff";
      statusEl.textContent = "Replacing file...";

      const success = await autoReplaceFile(cleanedFileBlob, originalFilename);

      if (success) {
        statusEl.style.color = "#00cc88";
        statusEl.textContent = "✓ File replaced successfully!";
        setTimeout(() => {
          URL.revokeObjectURL(cleanedUrl);
          removeBanner();
        }, 2000);
      } else {
        statusEl.style.color = "#ff9900";
        statusEl.textContent = "Auto-replace failed — please use Download instead.";
      }
    });

    // Auto-dismiss after 30 seconds
    setTimeout(() => {
      URL.revokeObjectURL(cleanedUrl);
      removeBanner();
    }, 30000);
  }

  function showCleanBanner(source) {
    const banner = createBanner();
    banner.innerHTML = `
      <div class="pg-drag-handle" style="
        background: #111;
        padding: 10px 14px;
        cursor: move;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #222;
      ">
        <span style="color: #00f2ff; font-weight: 700; font-size: 13px;">
          🛡️ PrivacyGate
        </span>
        <button id="pg-close" style="
          background: none; border: none; color: #666;
          font-size: 16px; cursor: pointer; padding: 0 4px;
        ">×</button>
      </div>
      <div style="padding: 12px 14px;">
        <div style="color: #00cc88; font-weight: 700; font-size: 14px; margin-bottom: 4px;">
          ✓ No sensitive data found
        </div>
        <div style="color: #555; font-size: 11px;">
          ${source} scanned — all clear.
        </div>
      </div>
    `;
    makeBannerDraggable(banner);
    banner.querySelector("#pg-close").addEventListener("click", removeBanner);
    setTimeout(removeBanner, 4000);
  }

  function showOfflineBanner() {
    const banner = createBanner();
    banner.innerHTML = `
      <div class="pg-drag-handle" style="
        background: #111;
        padding: 10px 14px;
        cursor: move;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #222;
      ">
        <span style="color: #00f2ff; font-weight: 700; font-size: 13px;">
          🛡️ PrivacyGate
        </span>
        <button id="pg-close" style="
          background: none; border: none; color: #666;
          font-size: 16px; cursor: pointer; padding: 0 4px;
        ">×</button>
      </div>
      <div style="padding: 12px 14px;">
        <div style="color: #ff9900; font-weight: 700; font-size: 13px; margin-bottom: 4px;">
          ⚠ PrivacyGate service offline
        </div>
        <div style="color: #555; font-size: 11px;">
          File scanning requires the PrivacyGate app to be running.<br>
          Text scanning still works locally.
        </div>
      </div>
    `;
    makeBannerDraggable(banner);
    banner.querySelector("#pg-close").addEventListener("click", removeBanner);
    setTimeout(removeBanner, 6000);
  }

  // ─────────────────────────────────────────────────────
  // AUTO-REPLACE FILE IN INPUT
  // DataTransfer trick — works on most sites including React
  // ─────────────────────────────────────────────────────

  async function autoReplaceFile(cleanedBlob, originalFilename) {
    const input = lastFileInput || dragTargetInput;

    if (!input) {
      // Try to find the most recently interacted file input on the page
      const inputs = document.querySelectorAll('input[type="file"]');
      if (inputs.length === 0) return false;
      lastFileInput = inputs[inputs.length - 1];
    }

    const targetInput = lastFileInput || dragTargetInput;
    if (!targetInput) return false;

    try {
      // Create a File object from the cleaned blob
      const cleanedFile = new File([cleanedBlob], originalFilename, {
        type: cleanedBlob.type || "application/octet-stream",
        lastModified: Date.now(),
      });

      // Method 1: DataTransfer — works on most standard inputs
      try {
        const dt = new DataTransfer();
        dt.items.add(cleanedFile);

        // Set files on the input
        Object.defineProperty(targetInput, "files", {
          value: dt.files,
          writable: true,
          configurable: true,
        });

        // Fire change event so React/Vue/Angular pick it up
        targetInput.dispatchEvent(new Event("change", { bubbles: true }));
        targetInput.dispatchEvent(new Event("input",  { bubbles: true }));

        return true;
      } catch (e1) {
        // Method 2: Simulate drop event (React file drop zones)
        try {
          const dt2 = new DataTransfer();
          dt2.items.add(cleanedFile);

          const dropTarget = dragTargetInput || targetInput.closest("[data-testid]") || targetInput;

          const dropEvent = new DragEvent("drop", {
            bubbles: true,
            cancelable: true,
            dataTransfer: dt2,
          });

          dropTarget.dispatchEvent(new DragEvent("dragenter", { bubbles: true, dataTransfer: dt2 }));
          dropTarget.dispatchEvent(new DragEvent("dragover",  { bubbles: true, dataTransfer: dt2 }));
          dropTarget.dispatchEvent(dropEvent);

          return true;
        } catch (e2) {
          return false;
        }
      }
    } catch (e) {
      return false;
    }
  }

  // ─────────────────────────────────────────────────────
  // TEXT PASTE INTERCEPTION
  // ─────────────────────────────────────────────────────

  async function handlePaste(e) {
    if (!pgEnabled) return;

    const target = e.target;
    const isInput = (
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable ||
      target.getAttribute("contenteditable") === "true"
    );

    if (!isInput) return;

    // Get text from clipboard
    let text = "";
    try {
      text = (e.clipboardData || window.clipboardData).getData("text/plain");
    } catch {
      return;
    }

    if (!text || text.trim().length < 5) return;

    // Scan locally — no API needed
    const findings = PrivacyGateScanner.scanText(text);

    if (findings.length === 0) {
      // Clean — let paste go through normally
      return;
    }

    // PII found — prevent default paste
    e.preventDefault();
    e.stopPropagation();

    // Clean the text
    const cleanedText = PrivacyGateScanner.cleanText(text, findings);

    // Replace clipboard with cleaned text
    try {
      await navigator.clipboard.writeText(cleanedText);
    } catch {
      // Fallback: insert directly into target
      try {
        document.execCommand("insertText", false, cleanedText);
      } catch { }
    }

    // Show banner
    showTextBanner(findings, cleanedText);
  }

  // ─────────────────────────────────────────────────────
  // FILE UPLOAD INTERCEPTION
  // ─────────────────────────────────────────────────────

  async function handleFileInput(e) {
    if (!pgEnabled) return;

    const input = e.target;
    if (!input || input.type !== "file") return;

    const files = input.files;
    if (!files || files.length === 0) return;

    lastFileInput = input;
    const file    = files[0];

    await processFile(file, input);
  }

  async function processFile(file, sourceInput) {
    if (!file) return;

    // Check if service is running
    const online = await isServiceRunning();
    if (!online) {
      showOfflineBanner();
      return;
    }

    // Show scanning indicator
    const scanningBanner = createBanner();
    scanningBanner.innerHTML = `
      <div style="padding: 14px; display: flex; align-items: center; gap: 10px;">
        <span style="color: #00f2ff; font-size: 18px;">🛡️</span>
        <div>
          <div style="color: #fff; font-weight: 700; font-size: 13px;">Scanning file...</div>
          <div style="color: #555; font-size: 11px;">${file.name}</div>
        </div>
      </div>
    `;

    // Build form data
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("sensitivity", "standard");

    try {
      const response = await fetch(`${API_BASE}/scan-file`, {
        method: "POST",
        body:   formData,
      });

      if (!response.ok) {
        throw new Error(`Service error: ${response.status}`);
      }

      // Read response headers for scan report
      const findingsCount  = parseInt(response.headers.get("X-Findings-Count") || "0");
      const typesFound     = response.headers.get("X-Types-Found") || "";
      const highCount      = parseInt(response.headers.get("X-High-Count")  || "0");
      const medCount       = parseInt(response.headers.get("X-Med-Count")   || "0");
      const lowCount       = parseInt(response.headers.get("X-Low-Count")   || "0");
      const durationMs     = parseInt(response.headers.get("X-Duration-Ms") || "0");
      const findingsSummary = response.headers.get("X-Findings-Summary") || "[]";

      // Get cleaned file as blob
      const cleanedBlob = await response.blob();

      removeBanner(); // remove scanning indicator

      if (findingsCount === 0) {
        showCleanBanner(file.name);
        return;
      }

      // Show result banner with both options
      showFileBanner(
        [],  // findings list (we use summary from headers)
        cleanedBlob,
        file.name,
        {
          findings_count:   findingsCount,
          types_found:      typesFound.split(",").filter(Boolean),
          high_count:       highCount,
          med_count:        medCount,
          low_count:        lowCount,
          duration_ms:      durationMs,
          findings_summary: findingsSummary,
        }
      );

    } catch (err) {
      removeBanner();
      showOfflineBanner();
      console.error("PrivacyGate scan error:", err);
    }
  }

  // ─────────────────────────────────────────────────────
  // DRAG AND DROP INTERCEPTION
  // ─────────────────────────────────────────────────────

  function handleDragOver(e) {
    if (!pgEnabled) return;
    if (e.dataTransfer && e.dataTransfer.types.includes("Files")) {
      dragTargetInput = e.target;
    }
  }

  async function handleDrop(e) {
    if (!pgEnabled) return;

    const files = e.dataTransfer && e.dataTransfer.files;
    if (!files || files.length === 0) return;

    dragTargetInput = e.target;
    const file = files[0];

    // Prevent the default drop (we'll re-inject the cleaned file)
    e.preventDefault();
    e.stopPropagation();

    await processFile(file, dragTargetInput);
  }

  // ─────────────────────────────────────────────────────
  // FILE INPUT CLICK TRACKING
  // Track which file input was last clicked so auto-replace works
  // ─────────────────────────────────────────────────────

  function trackFileInputs() {
    // Track existing inputs
    document.querySelectorAll('input[type="file"]').forEach(inp => {
      inp.addEventListener("click", () => { lastFileInput = inp; }, true);
      inp.addEventListener("change", handleFileInput, true);
    });

    // Watch for dynamically added inputs (React creates them on-the-fly)
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType !== 1) continue;

          if (node.tagName === "INPUT" && node.type === "file") {
            node.addEventListener("click",  () => { lastFileInput = node; }, true);
            node.addEventListener("change", handleFileInput, true);
          }

          // Also check children
          node.querySelectorAll && node.querySelectorAll('input[type="file"]').forEach(inp => {
            inp.addEventListener("click",  () => { lastFileInput = inp; }, true);
            inp.addEventListener("change", handleFileInput, true);
          });
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  // ─────────────────────────────────────────────────────
  // INIT
  // ─────────────────────────────────────────────────────

  function init() {
    // Text paste
    document.addEventListener("paste", handlePaste, true);

    // Drag and drop
    document.addEventListener("dragover", handleDragOver, true);
    document.addEventListener("drop",     handleDrop,     true);

    // File inputs
    trackFileInputs();
  }

  // Wait for DOM
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();