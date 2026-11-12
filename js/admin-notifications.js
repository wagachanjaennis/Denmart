(() => {
  'use strict';
  if (!location.pathname.startsWith('/control')) return;
  const enableButton = document.getElementById('enableAdminAlerts');
  let audio = null, permissionAsked = false, prior = null, polling = false;
  const values = {payments:0, cash:0};
  function setBadges(selector, count) {
    document.querySelectorAll(`[data-notify-count="${selector}"]`).forEach(node => {
      node.textContent = String(count);
      node.hidden = count <= 0;
    });
  }
  function beep() {
    try {
      if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === 'suspended') audio.resume();
      const oscillator = audio.createOscillator();
      const gain = audio.createGain();
      oscillator.type = 'sine'; oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, audio.currentTime + 0.025);
      gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.28);
      oscillator.connect(gain); gain.connect(audio.destination);
      oscillator.start(); oscillator.stop(audio.currentTime + 0.3);
    } catch (_) { /* Sound is optional on unsupported browsers. */ }
  }
  async function poll() {
    if (polling || document.hidden) return;
    polling = true;
    try {
      const response = await fetch('/control/api/notifications', {credentials:'same-origin', cache:'no-store', headers:{'Accept':'application/json'}});
      if (!response.ok) return;
      const data = await response.json(); if (!data.ok) return;
      const p = Number(data.payments || 0), c = Number(data.cash_sales || 0);
      setBadges('payments', p); setBadges('cash', c);
      document.querySelectorAll('[data-notify-dot="operations"]').forEach(node => { node.hidden = p + c <= 0; });
      if (prior !== null && (p > prior.payments || c > prior.cash)) {
        beep();
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification(`${document.querySelector('meta[name=app-brand-name]')?.content || 'Denmart'} needs your attention`, {body: `${p > prior.payments ? 'Payment approval pending. ' : ''}${c > prior.cash ? 'A POS cash sale awaits approval.' : ''}`.trim(), icon:'/static/pwa/icon.svg', tag:'denmart-admin-approvals'});
        }
      }
      prior = {payments:p, cash:c};
    } catch (_) { /* No noisy failures while temporarily offline. */ }
    finally { polling = false; }
  }
  enableButton?.addEventListener('click', async () => {
    try { if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)(); if (audio.state === 'suspended') await audio.resume(); } catch (_) {}
    if ('Notification' in window && Notification.permission === 'default') {
      try { await Notification.requestPermission(); permissionAsked = true; } catch (_) {}
    }
    beep();
    if (enableButton) { enableButton.textContent = 'Sound alerts enabled'; enableButton.disabled = true; }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  poll(); window.setInterval(poll, 20000);
})();
