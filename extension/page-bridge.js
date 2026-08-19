/* PrivacyGate page-bridge.js — MAIN world only. */
(() => {
  'use strict';
  if (window.__privacyGatePageBridgeInstalled) return;
  window.__privacyGatePageBridgeInstalled = true;

  const SOURCE = 'privacygate-v1';
  const tokenKey = '__privacyGateToken';
  const token = window[tokenKey] || (window[tokenKey] = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`);
  const pending = new Map();
  let sequence = 0;

  const isUpload = value => value instanceof File || value instanceof Blob;
  const fileName = value => value instanceof File && value.name ? value.name : 'upload';
  const hasFiles = body => {
    if (!(body instanceof FormData)) return false;
    for (const [, value] of body.entries()) if (isUpload(value)) return true;
    return false;
  };

  function requestClean(files) {
    return new Promise((resolve, reject) => {
      const id = `${token}-${++sequence}`;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error('PrivacyGate scanner timed out'));
      }, 120000);
      pending.set(id, { resolve, reject, timer });
      window.postMessage({ source: SOURCE, token, kind: 'privacygate-scan-request', id, files }, '*');
    });
  }

  window.addEventListener('message', event => {
    if (event.source !== window || !event.data || event.data.source !== SOURCE) return;
    const message = event.data;
    if (message.token !== token || message.kind !== 'privacygate-scan-response') return;
    const item = pending.get(message.id);
    if (!item) return;
    clearTimeout(item.timer);
    pending.delete(message.id);
    if (message.error) item.reject(new Error(message.error));
    else item.resolve(message.files || []);
  });

  async function cleanedFormData(body) {
    if (!hasFiles(body)) return body;
    const entries = [...body.entries()];
    const uploads = entries.filter(([, value]) => isUpload(value)).map(([, value]) => {
      return value instanceof File ? value : new File([value], 'upload', { type: value.type || 'application/octet-stream' });
    });
    const cleaned = await requestClean(uploads);
    const result = new FormData();
    let index = 0;
    for (const [name, value] of entries) {
      if (isUpload(value)) {
        const replacement = cleaned[index++] || value;
        const fallback = fileName(value);
        result.append(name, replacement instanceof File ? replacement : new File([replacement], fallback, { type: replacement.type || value.type }), fallback);
      } else {
        result.append(name, value);
      }
    }
    return result;
  }

  const nativeFetch = window.fetch;
  window.fetch = async function privacyGateFetch(input, init) {
    const options = init ? { ...init } : {};
    let body = options.body;
    if (body === undefined && input instanceof Request) {
      try { body = input.clone().body; } catch (_) { body = undefined; }
    }
    if (!(body instanceof FormData) || !hasFiles(body)) {
      return nativeFetch.apply(this, arguments);
    }
    options.body = await cleanedFormData(body);
    if (options.headers instanceof Headers) options.headers.delete('content-type');
    if (input instanceof Request) return nativeFetch.call(this, new Request(input, options));
    return nativeFetch.call(this, input, options);
  };

  const nativeSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function privacyGateSend(body) {
    if (!(body instanceof FormData) || !hasFiles(body)) return nativeSend.call(this, body);
    const xhr = this;
    cleanedFormData(body).then(cleaned => nativeSend.call(xhr, cleaned)).catch(error => {
      console.error('[PrivacyGate] upload blocked:', error);
      try { xhr.dispatchEvent(new ProgressEvent('error')); } catch (_) {}
    });
  };
})();
