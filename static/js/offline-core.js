/* Denmart offline core: IndexedDB-first persistence, safe local unlock, and recoverable form drafts.
   This device cache is a working copy, not a replacement for server backups. */
(function () {
  'use strict';
  const DB_NAME = 'denmart-device-v2';
  const DB_VERSION = 1;
  const STORE = 'records';
  const idleWindowMs = 30 * 60 * 1000;
  let dbPromise;
  let initialized = false;

  function openDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      if (!('indexedDB' in window)) return reject(new Error('IndexedDB is unavailable'));
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: 'key' });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('Could not open local storage'));
      request.onblocked = () => reject(new Error('Local storage upgrade is blocked by another Denmart tab'));
    });
    return dbPromise;
  }
  async function get(key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(String(key));
      req.onsuccess = () => resolve(req.result ? req.result.value : undefined);
      req.onerror = () => reject(req.error || new Error('Could not read local data'));
    });
  }
  async function set(key, value) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put({ key: String(key), value, updatedAt: new Date().toISOString() });
      tx.oncomplete = () => resolve(true);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('Could not save local data'));
    });
  }
  async function remove(key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(String(key));
      tx.oncomplete = () => resolve(true);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('Could not remove local data'));
    });
  }
  async function list(prefix) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve((req.result || []).filter(row => String(row.key).startsWith(prefix)).map(row => ({ key: row.key, value: row.value, updatedAt: row.updatedAt })));
      req.onerror = () => reject(req.error || new Error('Could not list local data'));
    });
  }
  async function persistStorage() {
    try {
      let persistent = false;
      if (navigator.storage && navigator.storage.persist) persistent = await navigator.storage.persist();
      if (!persistent) {
        let alreadyWarned = false;
        try { alreadyWarned = sessionStorage.getItem('denmart-storage-warning-shown') === '1'; } catch (_) {}
        if (!alreadyWarned) {
          showNotice('For better protection against browser cleanup, keep this app installed and export POS backups regularly. This browser has not confirmed persistent storage; server backups remain essential.', 'warning', 11000);
          try { sessionStorage.setItem('denmart-storage-warning-shown', '1'); } catch (_) {}
        }
      }
      if (navigator.storage && navigator.storage.estimate) {
        const estimate = await navigator.storage.estimate();
        if (estimate.quota && estimate.usage / estimate.quota > 0.85) showNotice('Device storage is nearly full. Connect to sync pending POS sales and export important records.', 'warning', 11000);
      }
    } catch (_) { /* Browser decides whether persistent storage can be granted. */ }
  }
  function randomBytes(size) {
    const data = new Uint8Array(size);
    crypto.getRandomValues(data);
    return data;
  }
  function toHex(bytes) { return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join(''); }
  function fromHex(hex) { const out = new Uint8Array(hex.length / 2); for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16); return out; }
  async function passwordVerifier(password, salt) {
    if (!crypto || !crypto.subtle) throw new Error('Secure password hashing is unavailable. Use HTTPS and sign in online first.');
    const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']);
    const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt, iterations: 120000, hash: 'SHA-256' }, material, 256);
    return toHex(new Uint8Array(bits));
  }
  const norm = value => String(value || '').trim().toLocaleLowerCase();
  const credKey = (portal, username) => `offline:credential:${portal}:${norm(username)}`;
  const pendingKey = (portal, username) => `offline:pending-credential:${portal}:${norm(username)}`;
  const portalOwnerKey = portal => `offline:cache-owner:${portal}`;
  const sessionKey = portal => `offline:session:${portal}`;
  const portalOfPath = path => path.startsWith('/control2') ? 'control2' : path.startsWith('/control') ? 'admin' : path.startsWith('/merchant') ? 'pos' : '';
  const targetPath = portal => portal === 'admin' ? '/control/' : portal === 'control2' ? '/control2/' : '/merchant/on';

  async function stageCredential(portal, username, password) {
    const salt = randomBytes(16);
    const verifier = await passwordVerifier(password, salt);
    await set(pendingKey(portal, username), { portal, username: norm(username), salt: toHex(salt), verifier, createdAt: Date.now(), verified: false });
  }
  async function activateCredentialFromServer() {
    const userMeta = document.querySelector('meta[name="offline-access-user"]');
    const portalMeta = document.querySelector('meta[name="offline-access-portal"]');
    const storeMeta = document.querySelector('meta[name="offline-access-store"]');
    const username = norm(userMeta && userMeta.content);
    const portal = (portalMeta && portalMeta.content || '').trim();
    if (!username || !['admin', 'control2', 'pos'].includes(portal) || !navigator.onLine || location.pathname.endsWith('/offline-login')) return;
    try {
      const pending = await get(pendingKey(portal, username));
      if (pending && pending.createdAt && Date.now() - pending.createdAt < 10 * 60 * 1000) {
        pending.verified = true;
        pending.activatedAt = Date.now();
        pending.storeId = storeMeta && storeMeta.content || '';
        await set(credKey(portal, username), pending);
        await remove(pendingKey(portal, username));
        await set(portalOwnerKey(portal), { username, storeId: pending.storeId, verifiedAt: Date.now() });
        await set(sessionKey(portal), { username, lastActive: Date.now(), storeId: pending.storeId });
        showNotice('Offline access is now set up for this device. Use your normal username and password to unlock the saved workspace when disconnected.', 'success', 6500);
      }
    } catch (_) { /* Sign-in must continue even if the browser blocks local storage. */ }
  }
  async function offlineUnlock(portal, username, password) {
    if (!['admin', 'control2', 'pos'].includes(portal)) throw new Error('Offline sign-in is not available for this area.');
    const key = credKey(portal, username);
    const record = await get(key);
    if (!record || !record.verified || !record.verifier || !record.salt) throw new Error('This account has not signed in successfully online on this device yet. Connect once to enable offline unlock.');
    if (Date.now() - Number(record.activatedAt || 0) > 30 * 24 * 60 * 60 * 1000) throw new Error('Offline access has expired for safety. Reconnect and sign in online to renew it.');
    const owner = await get(portalOwnerKey(portal));
    if (!owner || owner.username !== norm(username)) throw new Error('The saved workspace belongs to a different account. Connect and sign in online as this user before using offline mode.');
    const actual = await passwordVerifier(password, fromHex(record.salt));
    if (actual !== record.verifier) throw new Error('Username or password is incorrect for this device.');
    await set(sessionKey(portal), { username: norm(username), lastActive: Date.now(), storeId: record.storeId || '' });
    return true;
  }
  async function pingServer() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2300);
    try {
      const response = await fetch('/api/offline/ping', { method: 'GET', cache: 'no-store', credentials: 'same-origin', signal: controller.signal, headers: { 'Accept': 'application/json' } });
      return response.ok;
    } catch (_) { return false; }
    finally { clearTimeout(timeout); }
  }
  function showNotice(message, kind = 'info', duration = 0) {
    let node = document.getElementById('denmartOfflineNotice');
    if (!node) {
      node = document.createElement('div'); node.id = 'denmartOfflineNotice'; node.className = 'denmart-offline-notice';
      node.setAttribute('role', 'status'); node.setAttribute('aria-live', 'polite');
      Object.assign(node.style, { position: 'fixed', zIndex: '100000', left: '12px', right: '12px', bottom: '12px', padding: '12px 15px', borderRadius: '12px', boxShadow: '0 6px 24px rgba(0,0,0,.18)', font: '600 14px/1.4 system-ui,sans-serif', maxWidth: '960px', margin: '0 auto' });
      document.body.appendChild(node);
    }
    node.textContent = message;
    node.style.background = kind === 'warning' ? '#fff1c2' : kind === 'success' ? '#e0f7e9' : '#e8f4ff';
    node.style.color = '#17212b';
    if (duration) setTimeout(() => { if (node && node.textContent === message) node.remove(); }, duration);
  }
  function ensureOfflineBanner() {
    if (navigator.onLine) return;
    const path = location.pathname;
    const portal = portalOfPath(path);
    const text = portal ? 'OFFLINE VIEW — showing the last saved page. Approvals, payment checks and inventory changes are not completed until the server confirms them. POS cash sales queue on this device.' : 'YOU ARE OFFLINE — cached products and your saved basket remain available. Orders and payments are not submitted until you reconnect.';
    let banner = document.getElementById('denmartOfflineBanner');
    if (banner) return;
    banner = document.createElement('div'); banner.id = 'denmartOfflineBanner'; banner.textContent = text;
    Object.assign(banner.style, { position: 'sticky', top: '0', zIndex: '9999', padding: '9px 12px', textAlign: 'center', font: '700 12px/1.4 system-ui,sans-serif', background: '#fff1c2', color: '#5d4300', borderBottom: '1px solid #ebcf74' });
    document.body.insertBefore(banner, document.body.firstChild);
  }
  async function touchSession() {
    const portal = portalOfPath(location.pathname);
    const grantPortal = document.querySelector('meta[name="offline-access-portal"]')?.content || '';
    const grantUser = norm(document.querySelector('meta[name="offline-access-user"]')?.content || '');
    if (!portal || grantPortal !== portal || !grantUser || location.pathname.endsWith('/offline-login')) return;
    try {
      const prior = await get(sessionKey(portal));
      const owner = await get(portalOwnerKey(portal));
      const cred = prior?.username ? await get(credKey(portal, prior.username)) : null;
      if (prior && prior.username === grantUser && owner?.username === grantUser && cred?.verified && Date.now() - Number(cred.activatedAt || 0) < 30 * 24 * 60 * 60 * 1000 && Date.now() - Number(prior.lastActive || 0) < idleWindowMs) {
        prior.lastActive = Date.now(); await set(sessionKey(portal), prior);
      }
    } catch (_) { }
  }
  let touchAt = 0;
  function touchThrottled() { if (Date.now() - touchAt < 15000) return; touchAt = Date.now(); touchSession(); }
  window.addEventListener('pointerdown', touchThrottled, { passive: true });
  window.addEventListener('keydown', touchThrottled, { passive: true });
  window.addEventListener('touchstart', touchThrottled, { passive: true });
  window.addEventListener('online', () => { const n = document.getElementById('denmartOfflineBanner'); if (n) n.remove(); });
  window.addEventListener('offline', ensureOfflineBanner);

  function formDraftKey(form) {
    const action = new URL(form.getAttribute('action') || location.href, location.href);
    const names = [...form.elements].map(e => e.name).filter(n => n && n !== 'csrf_token' && n !== 'password').sort().join(',');
    const owner = norm(document.querySelector('meta[name="offline-access-user"]')?.content || 'public');
    const portal = document.querySelector('meta[name="offline-access-portal"]')?.content || 'public';
    return `offline:draft:${portal}:${owner}:${location.pathname}:${action.pathname}:${names}`;
  }
  function snapshotForm(form) {
    const fields = [];
    for (const el of [...form.elements]) {
      if (!el.name || ['password', 'file', 'submit', 'button', 'reset'].includes((el.type || '').toLowerCase()) || el.name.toLowerCase().includes('csrf')) continue;
      if ((el.type || '').toLowerCase() === 'checkbox' || (el.type || '').toLowerCase() === 'radio') fields.push({ name: el.name, type: el.type, value: el.value, checked: !!el.checked });
      else fields.push({ name: el.name, type: el.type || 'text', value: el.value });
    }
    return { key: formDraftKey(form), path: location.pathname, action: new URL(form.getAttribute('action') || location.href, location.href).pathname, fields, savedAt: new Date().toISOString() };
  }
  async function saveDraft(form) {
    try { const draft = snapshotForm(form); await set(draft.key, draft); return draft; }
    catch (error) { showNotice('Could not save this form draft locally. Keep this page open and reconnect before continuing.', 'warning'); return null; }
  }
  async function restoreDraft(form, draft, quiet) {
    if (!draft || !Array.isArray(draft.fields)) return;
    for (const field of draft.fields) {
      const candidates = [...form.elements].filter(el => el.name === field.name);
      if (!candidates.length) continue;
      const matching = candidates.find(el => el.type === 'checkbox' || el.type === 'radio' ? el.value === field.value : true) || candidates[0];
      if (!matching || matching.type === 'file' || matching.type === 'password' || matching.name.toLowerCase().includes('csrf')) continue;
      if (matching.type === 'checkbox' || matching.type === 'radio') matching.checked = !!field.checked;
      else matching.value = field.value == null ? '' : field.value;
      matching.dispatchEvent(new Event('input', { bubbles: true })); matching.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (!quiet) showNotice('Saved draft restored from this device. Review every field before submitting.', 'success', 5500);
  }
  async function setupFormDrafts() {
    const forms = [...document.forms].filter(form => !form.matches('[data-offline-target]'));
    for (const form of forms) {
      if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') continue;
      const key = formDraftKey(form);
      try {
        const draft = await get(key);
        if (draft && draft.savedAt && Date.now() - Date.parse(draft.savedAt) < 30 * 24 * 60 * 60 * 1000) {
          const wrapper = document.createElement('div'); wrapper.className = 'offline-draft-restore';
          const button = document.createElement('button'); button.type = 'button'; button.textContent = `Restore saved draft (${new Date(draft.savedAt).toLocaleString()})`;
          Object.assign(button.style, { padding: '7px 10px', margin: '6px 0', borderRadius: '8px', border: '1px solid #8ca8bb', background: '#eef6fb', cursor: 'pointer', fontWeight: '600' });
          button.addEventListener('click', () => restoreDraft(form, draft, false)); wrapper.appendChild(button); form.parentNode.insertBefore(wrapper, form);
          if (!navigator.onLine && draft.path === location.pathname) await restoreDraft(form, draft, true);
        }
      } catch (_) { }
      let draftTimer;
      const persistInput = () => { clearTimeout(draftTimer); draftTimer = setTimeout(() => saveDraft(form), 250); };
      form.addEventListener('input', persistInput); form.addEventListener('change', persistInput);
      form.addEventListener('submit', async event => {
        const action = new URL(form.getAttribute('action') || location.href, location.href);
        if (action.pathname === '/logout') {
          event.preventDefault();
          const portal = document.querySelector('meta[name="offline-access-portal"]')?.content || portalOfPath(location.pathname);
          try { await remove(sessionKey(portal)); } catch (_) {}
          if (!navigator.onLine) { location.href = portal === 'admin' ? '/control/offline-login' : portal === 'control2' ? '/control2/offline-login' : '/merchant/offline-login'; }
          else { form.dataset.offlineSubmitting = '1'; form.submit(); }
          return;
        }
        if (navigator.onLine) return;
        event.preventDefault();
        await saveDraft(form);
        const hasFile = [...form.querySelectorAll('input[type="file"]')].some(input => input.files && input.files.length);
        showNotice(hasFile ? 'Text fields were saved as a local draft, but selected image/file uploads cannot be restored automatically. Keep this page open and reconnect before uploading files.' : 'Saved on this device as a draft. This action has NOT reached Denmart and will not run until you reconnect and submit it again.', 'warning', 10000);
      });
    }
  }
  async function setupLoginForm() {
    const form = document.querySelector('form[data-offline-target]');
    if (!form) return;
    form.addEventListener('submit', async event => {
      if (form.dataset.offlineSubmitting === '1') return;
      event.preventDefault();
      const portal = form.dataset.offlineTarget;
      const username = form.querySelector('[name="username"]')?.value.trim() || '';
      const passwordInput = form.querySelector('[name="password"]');
      const password = passwordInput?.value || '';
      const button = form.querySelector('button[type="submit"],button:not([type])');
      if (!username || !password) { showNotice('Enter both username and password.', 'warning', 4000); return; }
      if (button) { button.disabled = true; button.dataset.originalText ||= button.textContent; button.textContent = 'Checking secure sign-in…'; }
      try {
        if (navigator.onLine && await pingServer()) {
          try { await stageCredential(portal, username, password); } catch (_) { /* Regular online sign-in must still work. */ }
          form.dataset.offlineSubmitting = '1';
          form.submit();
          return;
        }
        await offlineUnlock(portal, username, password);
        showNotice('Offline access verified. Opening the saved workspace; changes requiring the server will wait until reconnecting.', 'success', 2500);
        location.href = targetPath(portal);
      } catch (error) {
        showNotice(error.message || 'Offline sign-in failed.', 'warning', 7500);
        if (button) { button.disabled = false; button.textContent = button.dataset.originalText || 'Sign in'; }
      }
    });
  }

  window.DenmartOffline = {
    get, set, remove, list, persistStorage,
    async mergeCatalogue(items, key = 'public:catalogue', limit = 12000) {
      const old = await get(key); const map = new Map((Array.isArray(old) ? old : []).map(x => [String(x.id), x]));
      for (const item of (items || [])) if (item && item.id != null) map.set(String(item.id), item);
      const rows = [...map.values()].slice(-limit); await set(key, rows); return rows;
    },
    async searchCatalogue(q, key = 'public:catalogue', limit = 50) {
      const rows = await get(key) || []; const text = String(q || '').trim().toLocaleLowerCase();
      const found = !text ? rows.slice(0, limit) : rows.filter(x => `${x.name || ''} ${x.barcode || ''} ${x.brand || ''} ${x.category || ''}`.toLocaleLowerCase().includes(text)).slice(0, limit);
      return found;
    },
    async activateFromServer() { await activateCredentialFromServer(); },
    async unlock(portal, username, password) { return offlineUnlock(portal, username, password); },
    async ping() { return pingServer(); },
    async setSession(portal, username, storeId = '') { await set(sessionKey(portal), { username: norm(username), lastActive: Date.now(), storeId }); },
    async clearSession(portal) { await remove(sessionKey(portal)); },
    async getSession(portal) { return get(sessionKey(portal)); },
    showNotice
  };

  async function initializeOnce() {
    if (initialized) return; initialized = true;
    await persistStorage();
    try { await activateCredentialFromServer(); } catch (_) {}
    await setupLoginForm();
    await setupFormDrafts();
    ensureOfflineBanner();
  }
  document.addEventListener('DOMContentLoaded', initializeOnce, { once: true });
  if (document.readyState !== 'loading') initializeOnce();
})();
