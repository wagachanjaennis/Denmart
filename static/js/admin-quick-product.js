(() => {
  'use strict';
  const form = document.querySelector('[data-quick-product]');
  if (!form) return;
  const feedback = document.getElementById('quickProductFeedback');
  const saveButton = document.getElementById('quickSaveButton');
  const barcode = document.getElementById('quickBarcode');
  const name = document.getElementById('quickName');
  const clearButton = document.getElementById('quickClearButton');
  const csrf = form.querySelector('[name="csrf_token"]')?.value || document.querySelector('meta[name="csrf-token"]')?.content || '';
  let saving = false;
  function show(message, good = true) {
    if (!feedback) return;
    feedback.hidden = false; feedback.textContent = message;
    feedback.className = `quick-product-feedback ${good ? 'success' : 'error'}`;
  }
  function clearForNext() {
    for (const key of ['barcode','name','selling_price','cost_price','stock_quantity','brand','sku','pack_size','description']) {
      const field = form.elements.namedItem(key);
      if (field) field.value = key === 'pack_size' || key === 'brand' || key === 'sku' || key === 'description' ? '' : '';
    }
    const unit = form.elements.namedItem('unit'); if (unit) unit.value = 'unit';
    barcode?.focus();
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (saving) return;
    if (!name?.value.trim()) { name?.focus(); return show('Enter the product name first. A barcode by itself is not a product name.', false); }
    saving = true; if (saveButton) { saveButton.disabled = true; saveButton.textContent = 'Saving…'; }
    const payload = Object.fromEntries(new FormData(form).entries()); delete payload.csrf_token;
    try {
      const response = await fetch(form.action, {method:'POST', credentials:'same-origin', cache:'no-store', headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRFToken':csrf}, body:JSON.stringify(payload)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || data.error || 'The product could not be saved.');
      show(data.message || 'Product saved. Ready for the next item.');
      clearForNext();
    } catch (error) {
      show(error?.message || 'Connection failed. Your form values were kept so you can retry.', false);
    } finally {
      saving = false; if (saveButton) { saveButton.disabled = false; saveButton.textContent = 'Save & next item'; }
    }
  });
  clearButton?.addEventListener('click', () => { clearForNext(); if (feedback) feedback.hidden = true; });
})();
