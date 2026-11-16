(() => {
  'use strict';

  const form = document.querySelector('[data-bulk-photo-products]');
  if (!form) return;

  const picker = document.getElementById('bulkProductImages');
  const dropzone = document.getElementById('bulkPhotoDropzone');
  const queue = document.getElementById('bulkPhotoQueue');
  const empty = document.getElementById('bulkPhotoEmpty');
  const count = document.getElementById('bulkPhotoCount');
  const summary = document.getElementById('bulkPhotoSummary');
  const feedback = document.getElementById('bulkPhotoFeedback');
  const saveButton = document.getElementById('bulkPhotoSave');
  const clearButton = document.getElementById('bulkPhotoClear');
  const storeSelect = document.getElementById('bulkProductStore');
  const categorySelect = document.getElementById('bulkProductCategory');
  const csrf = form.querySelector('[name="csrf_token"]')?.value
    || document.querySelector('meta[name="csrf-token"]')?.content || '';

  const MAX_FILES = 30;
  const MAX_FILE_SIZE = 8 * 1024 * 1024;
  const entries = [];
  let saving = false;

  function message(text, good = true) {
    if (!feedback) return;
    feedback.hidden = false;
    feedback.textContent = text;
    feedback.className = `bulk-photo-feedback ${good ? 'success' : 'error'}`;
  }

  function defaultName(filename, index) {
    const stem = String(filename || '').replace(/\\/g, '/').split('/').pop().replace(/\.[^.]+$/, '');
    const cleaned = stem.replace(/[\s_-]+/g, ' ').replace(/\s+/g, ' ').trim();
    return (cleaned || `New Product ${index + 1}`).slice(0, 240);
  }

  function makeField(labelText, type, className, placeholder, step) {
    const label = document.createElement('label');
    label.className = 'bulk-photo-field';
    const caption = document.createElement('span');
    caption.textContent = labelText;
    const input = document.createElement('input');
    input.className = 'admin-input wide';
    input.type = type;
    input.className += ` ${className}`;
    input.autocomplete = 'off';
    input.placeholder = placeholder;
    if (type === 'number') {
      input.min = '0';
      input.step = step || '0.01';
      input.inputMode = 'decimal';
    }
    label.append(caption, input);
    return { label, input };
  }

  function renderEntry(entry, index) {
    const card = document.createElement('article');
    card.className = 'bulk-photo-card';

    const imageWrap = document.createElement('div');
    imageWrap.className = 'bulk-photo-preview';
    const image = document.createElement('img');
    image.src = entry.previewUrl;
    image.alt = entry.file.name || `Product photo ${index + 1}`;
    image.loading = 'lazy';
    imageWrap.append(image);

    const body = document.createElement('div');
    body.className = 'bulk-photo-details';
    const top = document.createElement('div');
    top.className = 'bulk-photo-card-heading';
    const filename = document.createElement('span');
    filename.className = 'bulk-photo-filename';
    filename.textContent = entry.file.name;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'bulk-photo-remove';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', `Remove ${entry.file.name}`);
    remove.addEventListener('click', () => removeEntry(entry));
    top.append(filename, remove);

    const name = makeField('Product name', 'text', 'bulk-product-name', 'Name this product');
    name.input.maxLength = 240;
    name.input.value = entry.name;
    const price = makeField('Selling price (KES)', 'number', 'bulk-product-price', 'Optional', '0.01');
    const quantity = makeField('Opening quantity', 'number', 'bulk-product-quantity', 'Optional', '0.001');
    entry.nameInput = name.input;
    entry.priceInput = price.input;
    entry.quantityInput = quantity.input;
    body.append(top, name.label, price.label, quantity.label);
    card.append(imageWrap, body);
    entry.card = card;
    queue.append(card);
  }

  function updateCounts() {
    const total = entries.length;
    if (count) count.textContent = `${total} photo${total === 1 ? '' : 's'} added`;
    if (summary) summary.textContent = total ? `${total} product${total === 1 ? '' : 's'} ready to save` : 'No products waiting';
    if (empty) empty.hidden = total > 0;
    if (saveButton) saveButton.disabled = total === 0 || saving || !storeSelect?.value;
    if (clearButton) clearButton.disabled = total === 0 || saving;
    if (storeSelect) storeSelect.disabled = saving;
    if (categorySelect) categorySelect.disabled = saving;
    if (picker) picker.disabled = saving;
  }

  function removeEntry(entry) {
    const index = entries.indexOf(entry);
    if (index < 0) return;
    URL.revokeObjectURL(entry.previewUrl);
    entry.card?.remove();
    entries.splice(index, 1);
    updateCounts();
  }

  function addFiles(fileList) {
    const candidates = Array.from(fileList || []);
    if (!candidates.length) return;
    let added = 0;
    for (const file of candidates) {
      if (entries.length >= MAX_FILES) {
        message(`A batch can contain up to ${MAX_FILES} photos. Save this batch, then add the remaining photos.`, false);
        break;
      }
      if (!file.type || !file.type.toLowerCase().startsWith('image/')) {
        message(`${file.name || 'One selected file'} is not a recognised image. It was skipped.`, false);
        continue;
      }
      if (file.size > MAX_FILE_SIZE) {
        message(`${file.name} is larger than 8 MB. Choose a smaller image.`, false);
        continue;
      }
      const duplicate = entries.some(item => item.file.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified);
      if (duplicate) continue;
      const entry = {
        file,
        previewUrl: URL.createObjectURL(file),
        name: defaultName(file.name, entries.length),
        card: null,
      };
      entries.push(entry);
      renderEntry(entry, entries.length - 1);
      added += 1;
    }
    updateCounts();
    if (added) message(`Added ${added} photo${added === 1 ? '' : 's'}. Add names, prices or quantities where available, then save the batch.`);
  }

  function clearBatch(preserveFeedback = false) {
    for (const entry of entries) URL.revokeObjectURL(entry.previewUrl);
    entries.splice(0, entries.length);
    queue?.replaceChildren();
    if (picker) picker.value = '';
    if (feedback && !preserveFeedback) feedback.hidden = true;
    updateCounts();
  }

  picker?.addEventListener('change', () => {
    addFiles(picker.files);
    picker.value = '';
  });

  dropzone?.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      picker?.click();
    }
  });
  for (const eventName of ['dragenter', 'dragover']) {
    dropzone?.addEventListener(eventName, event => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.add('is-drag-over');
    });
  }
  for (const eventName of ['dragleave', 'drop']) {
    dropzone?.addEventListener(eventName, event => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.remove('is-drag-over');
    });
  }
  dropzone?.addEventListener('drop', event => addFiles(event.dataTransfer?.files));
  clearButton?.addEventListener('click', clearBatch);
  storeSelect?.addEventListener('change', updateCounts);

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving) return;
    if (!entries.length) return message('Add at least one product photo first.', false);
    if (!storeSelect?.value) return message('Choose the mart where these products should be saved.', false);

    for (const entry of entries) {
      if (!entry.nameInput?.value.trim()) {
        entry.nameInput?.focus();
        return message('Every photo needs a product name. The filename is filled in automatically, but you can change it.', false);
      }
      if (!entry.priceInput.checkValidity() || !entry.quantityInput.checkValidity()) {
        (entry.priceInput.checkValidity() ? entry.quantityInput : entry.priceInput).reportValidity();
        return message('Check the price and quantity values before saving.', false);
      }
    }

    const formData = new FormData();
    formData.append('csrf_token', csrf);
    formData.append('store_id', storeSelect.value);
    formData.append('category_id', categorySelect?.value || '');
    formData.append('items', JSON.stringify(entries.map(entry => ({
      name: entry.nameInput.value.trim(),
      selling_price: entry.priceInput.value.trim(),
      stock_quantity: entry.quantityInput.value.trim(),
    }))));
    for (const entry of entries) formData.append('images', entry.file, entry.file.name);

    saving = true;
    if (saveButton) saveButton.textContent = `Saving ${entries.length}…`;
    updateCounts();
    if (feedback) feedback.hidden = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': csrf },
        body: formData,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.message || result.error || 'The batch could not be saved.');
      const savedCount = Number(result.created || entries.length);
      const draftCount = Number(result.drafts || 0);
      message(`Successfully saved ${savedCount} products. ${draftCount} ${draftCount === 1 ? 'is' : 'are'} unpriced draft${draftCount === 1 ? '' : 's'} and can be priced later. Refreshing the catalogue…`);
      clearBatch(true);
      if (saveButton) saveButton.textContent = 'Saved';
      window.setTimeout(() => window.location.reload(), 1100);
    } catch (error) {
      message(error?.message || 'Connection failed. Your photos and details are still here; you can retry.', false);
      saving = false;
      if (saveButton) saveButton.textContent = 'Save all products';
      updateCounts();
    }
  });

  updateCounts();
})();
