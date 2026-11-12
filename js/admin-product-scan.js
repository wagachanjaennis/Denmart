(() => {
  'use strict';
  const forms = Array.from(document.querySelectorAll('form')).filter(form => form.querySelector('input[name="barcode"]'));
  const norm = value => String(value || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
  function lookupCode(raw) {
    let code = String(raw || '').trim().replace(/[\r\n\t]/g, '');
    // Some 2D/GS1 scanners prefix a symbology identifier and transmit multiple
    // application identifiers. Prefer the GTIN from AI (01) when one is present.
    code = code.replace(/^\](?:C1|d2|Q3|A0)/i, '');
    const parenthesized = code.match(/\(01\)\s*(\d{14})/);
    if (parenthesized) return parenthesized[1];
    const gs1 = code.match(/(?:^|[\x1d])01(\d{14})/);
    if (gs1) return gs1[1];
    return code.replace(/[\x1d\x00-\x08\x0B\x0C\x0E-\x1F]/g, '').trim();
  }

  function field(form, name) { return form.querySelector(`[name="${name}"]`); }
  function statusNode(barcodeInput) {
    let node = barcodeInput.parentElement.querySelector('.barcode-autofill-status');
    if (!node) {
      node = document.createElement('div');
      node.className = 'barcode-autofill-status muted';
      node.setAttribute('role', 'status');
      node.style.cssText = 'margin-top:7px;font-size:12px;line-height:1.45;';
      barcodeInput.parentElement.appendChild(node);
    }
    return node;
  }
  function setStatus(node, message, kind = '') {
    node.textContent = message || '';
    node.className = `barcode-autofill-status ${kind}`.trim();
  }
  function setTextField(form, name, value, overwrite = true) {
    const input = field(form, name);
    if (!input || value === undefined || value === null || String(value) === '') return;
    if (!overwrite && String(input.value || '').trim()) return;
    input.value = String(value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function setCategory(form, data) {
    const select = field(form, 'category_id');
    if (!select) return;
    if (data.category_id && Array.from(select.options).some(option => option.value === data.category_id)) {
      select.value = data.category_id;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    if (data.category) {
      const found = Array.from(select.options).find(option => norm(option.textContent) === norm(data.category));
      if (found) {
        select.value = found.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  }
  function addEditLink(node, href, label) {
    if (!href) return;
    const link = document.createElement('a');
    link.href = href;
    link.textContent = label || 'Open existing product';
    link.style.cssText = 'display:inline-block;margin-top:5px;font-weight:700;';
    node.appendChild(document.createElement('br'));
    node.appendChild(link);
  }

  forms.forEach(form => {
    const barcodeInput = field(form, 'barcode');
    if (!barcodeInput) return;
    const status = statusNode(barcodeInput);
    const editMatch = window.location.pathname.match(/^\/control\/products\/([^/]+)\/edit\/?$/);
    const editingProductId = editMatch ? decodeURIComponent(editMatch[1]) : '';
    let timer = null;
    let latestValue = '';
    let lastInputAt = 0;
    let lastLength = 0;
    let fastBurst = false;
    let requestSequence = 0;

    async function lookupBarcode(rawValue) {
      const barcode = lookupCode(rawValue).replace(/\s+/g, '');
      if (barcode.length < 3 || barcode === latestValue) return;
      latestValue = barcode;
      if (barcodeInput.value.trim() !== barcode) { barcodeInput.value = barcode; barcodeInput.dispatchEvent(new Event('input', { bubbles: true })); }
      const seq = ++requestSequence;
      setStatus(status, 'Looking up barcode…');
      const store = field(form, 'store_id')?.value || new URLSearchParams(location.search).get('store_id') || '';
      const params = new URLSearchParams({ barcode });
      if (form.hasAttribute('data-quick-product')) params.set('fast', '1');
      if (store) params.set('store_id', store);
      try {
        const response = await fetch(`/control/api/products/barcode-lookup?${params}`, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } });
        const data = await response.json();
        if (seq !== requestSequence) return;
        if (!response.ok || !data.ok) throw new Error(data.message || 'Barcode lookup was not available.');
        if (!data.found) {
          setStatus(status, data.message || `No product details are stored for ${barcode}. The barcode is ready; enter the name and other details manually.`, 'scan-unknown');
          return;
        }

        // On an edit page, never replace one existing catalogue product with another
        // just because a scanner was pointed at a different item.
        if (editingProductId && data.product_id && data.product_id !== editingProductId) {
          setStatus(status, `${data.name} is already a different catalogue product. Your current product was not changed.` , 'scan-warning');
          addEditLink(status, data.edit_url, 'Open the scanned product instead');
          return;
        }

        setTextField(form, 'name', data.name);
        setTextField(form, 'brand', data.brand);
        setTextField(form, 'sku', data.sku);
        setTextField(form, 'unit', data.unit || 'unit');
        setTextField(form, 'pack_size', data.pack_size);
        setTextField(form, 'description', data.description);
        if (data.image_url) setTextField(form, 'image_url', data.image_url);
        setCategory(form, data);

        if (data.exists_in_selected_store && !editingProductId) {
          setStatus(status, `${data.name} is already in this mart. Prices/stock have not been overwritten; open its editor to change them.`, 'scan-warning');
          addEditLink(status, data.edit_url, 'Open existing product editor');
        } else {
          setStatus(status, `${data.name} found. Product details filled where available. Selling price, cost and quantity remain for you to enter.`, 'scan-found');
          if (data.exists_in_business && data.edit_url && !field(form, 'store_id')?.value) {
            addEditLink(status, data.edit_url, 'View existing product');
          }
        }
      } catch (error) {
        if (seq !== requestSequence) return;
        setStatus(status, error?.message || 'Barcode lookup failed. You can still enter the details manually.', 'scan-warning');
      }
    }

    barcodeInput.addEventListener('input', () => {
      const value = lookupCode(barcodeInput.value).replace(/\s+/g, '');
      if (timer) clearTimeout(timer);
      if (value.length < 5) return;
      const now = performance.now();
      const delta = value.length - lastLength;
      fastBurst = fastBurst || (lastInputAt && now - lastInputAt < 65 && delta >= 1 && value.length >= 7);
      lastInputAt = now;
      lastLength = value.length;
      timer = setTimeout(() => lookupBarcode(value), fastBurst ? 180 : 500);
    });
    barcodeInput.addEventListener('keydown', event => {
      const scannerTab = event.key === 'Tab' && barcodeInput.value.trim().length >= 5 && lastInputAt && performance.now() - lastInputAt < 250;
      if (event.key === 'Enter' || scannerTab) {
        if (event.key === 'Enter' || scannerTab) event.preventDefault();
        if (timer) clearTimeout(timer);
        lookupBarcode(barcodeInput.value);
        fastBurst = false;
      }
    });

    // Keyboard-wedge scanners type very quickly. If the user has moved focus into
    // Price/Cost/Quantity, capture a rapid scan burst and redirect it to Barcode
    // rather than allowing a 13-digit code to corrupt the field being edited.
    let globalScan = { buffer: '', target: null, originalValue: '', startAt: 0, lastAt: 0, fastHits: 0, timer: null };
    function resetGlobalScan() {
      if (globalScan.timer) clearTimeout(globalScan.timer);
      globalScan = { buffer: '', target: null, originalValue: '', startAt: 0, lastAt: 0, fastHits: 0, timer: null };
    }
    function finishGlobalScan() {
      const scan = globalScan;
      const elapsed = scan.startAt ? performance.now() - scan.startAt : 99999;
      const raw = scan.buffer;
      const target = scan.target;
      resetGlobalScan();
      if (raw.length < 8 || elapsed > 1400 || scan.fastHits < 4 || !/^[\]A-Za-z0-9._:/+%()\x1D-]+$/.test(raw)) return;
      const code = lookupCode(raw).replace(/\s+/g, '');
      if (target && target !== barcodeInput && 'value' in target) {
        target.value = scan.originalValue;
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.dispatchEvent(new Event('change', { bubbles: true }));
      }
      barcodeInput.value = code;
      latestValue = '';
      lookupBarcode(code);
    }
    document.addEventListener('keydown', event => {
      const target = event.target;
      if (!form.contains(target) || target === barcodeInput || event.ctrlKey || event.altKey || event.metaKey) return;
      if (event.key === 'Enter' || event.key === 'Tab') {
        if (globalScan.buffer.length >= 8 && globalScan.fastHits >= 4) {
          event.preventDefault(); event.stopImmediatePropagation(); finishGlobalScan();
        } else resetGlobalScan();
        return;
      }
      if (typeof event.key !== 'string' || event.key.length !== 1) return;
      const t = performance.now();
      if (!globalScan.target || globalScan.target !== target || t - globalScan.lastAt > 130) {
        resetGlobalScan(); globalScan.target = target;
        globalScan.originalValue = ('value' in target) ? String(target.value || '') : '';
        globalScan.startAt = t; globalScan.lastAt = t; globalScan.buffer = event.key; globalScan.fastHits = 0;
      } else {
        if (t - globalScan.lastAt <= 85) globalScan.fastHits++;
        globalScan.buffer += event.key; globalScan.lastAt = t;
      }
      if (globalScan.timer) clearTimeout(globalScan.timer);
      globalScan.timer = setTimeout(finishGlobalScan, 150);
    }, true);

    // Make opening the Add Product page ready for a scanner, but don't steal focus
    // when an administrator is already editing another field.
    if (!document.activeElement || document.activeElement === document.body) barcodeInput.focus({ preventScroll: true });
  });
})();
