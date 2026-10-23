(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const api = window.DenmartStudioAPI;
  if (!api || !$('adCreativeShell')) return;

  const shell = $('adCreativeShell');
  const stage = $('adStageShell');
  const overlay = $('adLayerOverlay');
  const host = $('adStageHost');
  const advanced = $('adAdvancedDrawer');
  const advancedContent = $('adAdvancedContent');
  const productDrawer = document.querySelector('.ad-product-drawer');
  const upload = $('designImageUpload');
  let currentState = api.getState();
  let activeScene = 0;
  let selectedLayer = null;
  let activeTool = 'select';
  let dragState = null;
  let statusMessage = '';
  let searchTimer = 0;
  const undoStack = [];
  const redoStack = [];
  let historyFocusKey = '';
  const elementNames = { text: 'Text', number: 'Number', image: 'Image', rect: 'Rectangle', circle: 'Circle', line: 'Line', badge: 'Price badge', sticker: 'Sticker', qr: 'Shop QR' };
  const elementSymbols = { text: 'T', number: '12', image: '▧', rect: '▰', circle: '◯', line: '／', badge: '¤', sticker: '✦', qr: '▦' };

  // Move the real preview, template/schedule controls and original upload/save controls into
  // the visual workspace. They still use the existing campaign endpoints and database rows.
  const oldFrame = $('advertPreviewFrame');
  if (oldFrame && host) host.appendChild(oldFrame);
  ['campaigns', 'settings', 'upload', 'ai'].forEach((key) => {
    const section = document.querySelector(`[data-ad-legacy-panel="${key}"]`);
    if (section && advancedContent) advancedContent.appendChild(section);
  });
  const actionsPanel = document.querySelector('.advert-actions-panel');
  if (actionsPanel && advancedContent) advancedContent.appendChild(actionsPanel);
  // Keep original form fields as the durable interface used by the existing save/publish code.
  const visibleName = $('adDesignCampaignName');
  const originalName = $('campaignName');
  if (visibleName && originalName) {
    visibleName.value = originalName.value;
    visibleName.addEventListener('input', () => { originalName.value = visibleName.value.slice(0, 120); });
    visibleName.addEventListener('change', () => api.refresh());
  }

  function state() { currentState = api.getState() || currentState || {}; return currentState; }
  function slides() { return Array.isArray(state().slides) ? state().slides : []; }
  function slide() { return slides()[Math.min(activeScene, Math.max(0, slides().length - 1))] || {}; }
  function design(create) {
    const s = slide();
    if (create && (!s.design || !Array.isArray(s.design.elements) || !s.design.enabled)) return api.ensureDesign(activeScene);
    return s.design || { enabled: false, elements: [] };
  }
  function elements() { const d = design(false); return Array.isArray(d.elements) ? d.elements : []; }
  function getLayer() { return elements().find((el) => String(el.id) === String(selectedLayer)) || null; }
  function uid() { return 'layer-' + (window.crypto && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)); }
  function setStatus(message, kind) {
    statusMessage = message || '';
    const node = $('adDesignStatus');
    if (node) { node.textContent = statusMessage; node.classList.remove('error', 'success'); if (kind) node.classList.add(kind); }
  }
  function syncPlayer(preserveTime) {
    currentState = api.getState() || currentState;
    if (visibleName && originalName) originalName.value = visibleName.value.slice(0, 120);
    if (window.DenmartAdPlayer) {
      window.DenmartAdPlayer.setCampaign(currentState, !!preserveTime);
      window.DenmartAdPlayer.setEditorScene(activeScene, true, !!preserveTime);
    }
  }
  function safeText(value) { return String(value == null ? '' : value); }
  function findLayerIndex(id) { return elements().findIndex((el) => String(el.id) === String(id)); }
  function makeSnapshot() {
    const s = slide();
    return { scene: activeScene, design: s.design ? JSON.parse(JSON.stringify(s.design)) : null, selected: selectedLayer };
  }
  function updateHistoryButtons() {
    const undo = $('adDesignUndo'), redo = $('adDesignRedo');
    if (undo) undo.disabled = !undoStack.length;
    if (redo) redo.disabled = !redoStack.length;
  }
  function checkpoint() {
    undoStack.push(makeSnapshot());
    if (undoStack.length > 80) undoStack.shift();
    redoStack.length = 0;
    updateHistoryButtons();
  }
  function restoreSnapshot(snapshot) {
    if (!snapshot || !slides()[snapshot.scene]) return;
    activeScene = snapshot.scene;
    const target = state().slides[activeScene];
    if (snapshot.design) target.design = JSON.parse(JSON.stringify(snapshot.design));
    else delete target.design;
    selectedLayer = snapshot.selected;
    api.refresh(); syncPlayer(false); renderAll(); updateHistoryButtons();
  }
  function undo() {
    if (!undoStack.length) return;
    redoStack.push(makeSnapshot()); restoreSnapshot(undoStack.pop()); setStatus('Last canvas change undone.');
  }
  function redo() {
    if (!redoStack.length) return;
    undoStack.push(makeSnapshot()); restoreSnapshot(redoStack.pop()); setStatus('Canvas change restored.');
  }
  $('adDesignUndo')?.addEventListener('click', undo);
  $('adDesignRedo')?.addEventListener('click', redo);
  shell.addEventListener('focusin', (event) => {
    const node = event.target;
    if (!node || !node.id || !inspectorFields[node.id]) return;
    const key = activeScene + ':' + selectedLayer + ':' + node.id;
    if (historyFocusKey !== key) { checkpoint(); historyFocusKey = key; }
  });
  shell.addEventListener('focusout', (event) => { if (event.target && inspectorFields[event.target.id]) historyFocusKey = ''; });
  document.addEventListener('keydown', (event) => {
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); return; }
    if (mod && event.key.toLowerCase() === 'y') { event.preventDefault(); redo(); return; }
    const tag = String(event.target && event.target.tagName || '').toLowerCase();
    const typing = ['input', 'textarea', 'select'].includes(tag) || event.target?.isContentEditable;
    if (!typing && (event.key === 'Delete' || event.key === 'Backspace') && selectedLayer) { event.preventDefault(); deleteLayer(); }
    if (!typing && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key) && selectedLayer) {
      const el = getLayer(); if (!el) return; event.preventDefault(); if (!event.repeat) checkpoint();
      const step = event.shiftKey ? 10 : 1;
      if (event.key === 'ArrowLeft') el.x = Math.max(-500, (Number(el.x)||0) - step);
      if (event.key === 'ArrowRight') el.x = Math.min(1920, (Number(el.x)||0) + step);
      if (event.key === 'ArrowUp') el.y = Math.max(-300, (Number(el.y)||0) - step);
      if (event.key === 'ArrowDown') el.y = Math.min(1080, (Number(el.y)||0) + step);
      syncPlayer(true); renderOverlay();
    }
  });

  function renderTimeline() {
    const track = $('adSceneTimeline');
    if (!track) return;
    track.replaceChildren();
    slides().forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'ad-scene-card' + (index === activeScene ? ' active' : '');
      const name = document.createElement('b'); name.textContent = 'Scene ' + (index + 1);
      const headline = document.createElement('span'); headline.textContent = safeText(item.headline || 'Untitled scene');
      const meta = document.createElement('span'); meta.textContent = Math.max(3, Number(item.duration) || 6) + ' sec · ' + ((item.design && item.design.enabled) ? (item.design.elements || []).length + ' layers' : 'basic scene');
      button.append(name, headline, meta);
      button.addEventListener('click', () => chooseScene(index));
      track.appendChild(button);
    });
  }
  function chooseScene(index) {
    activeScene = Math.max(0, Math.min(slides().length - 1, Number(index) || 0));
    selectedLayer = null;
    if (window.DenmartAdPlayer) window.DenmartAdPlayer.setEditorScene(activeScene, true);
    renderAll();
  }
  function renderLayers() {
    const list = $('adLayerList');
    if (!list) return;
    list.replaceChildren();
    const current = elements();
    if (!current.length) {
      const hint = document.createElement('p'); hint.className = 'ad-inspector-empty'; hint.textContent = 'This scene has no editable layers yet. Choose a tool on the left to add one.';
      list.appendChild(hint); return;
    }
    current.slice().reverse().forEach((el) => {
      const button = document.createElement('button'); button.type = 'button';
      button.className = 'ad-layer-list-row' + (String(el.id) === String(selectedLayer) ? ' active' : '');
      const symbol = document.createElement('span'); symbol.className = 'ad-layer-type'; symbol.textContent = elementSymbols[el.type] || '•';
      const title = document.createElement('strong'); title.textContent = safeText(el.text || el.product_name || elementNames[el.type] || el.type || 'Layer');
      button.append(symbol, title); button.addEventListener('click', () => selectLayer(el.id)); list.appendChild(button);
    });
  }
  function renderOverlay() {
    if (!overlay) return;
    overlay.replaceChildren();
    const d = design(false);
    const enabled = !!d.enabled;
    stage.classList.toggle('design-disabled', !enabled);
    if ($('adStartDesign')) $('adStartDesign').hidden = enabled;
    if (!enabled) return;
    elements().forEach((el) => {
      const box = document.createElement('button'); box.type = 'button'; box.className = 'ad-layer-handle' + (String(el.id) === String(selectedLayer) ? ' selected' : '');
      box.dataset.layerId = String(el.id); box.setAttribute('aria-label', 'Select ' + safeText(el.text || elementNames[el.type] || 'layer'));
      const x = Number(el.x) || 0, y = Number(el.y) || 0, w = Math.max(8, Number(el.w) || 300), h = Math.max(8, Number(el.h) || 100);
      box.style.left = (x / 1920 * 100) + '%'; box.style.top = (y / 1080 * 100) + '%'; box.style.width = (w / 1920 * 100) + '%'; box.style.height = (h / 1080 * 100) + '%';
      const name = document.createElement('span'); name.className = 'ad-layer-handle-name'; name.textContent = safeText(el.text || elementNames[el.type] || el.type || 'Layer'); box.appendChild(name);
      if (String(el.id) === String(selectedLayer)) { const resize = document.createElement('span'); resize.className = 'ad-layer-resize'; resize.setAttribute('aria-hidden', 'true'); resize.dataset.resizeHandle = '1'; box.appendChild(resize); }
      box.addEventListener('pointerdown', (event) => startDrag(event, el.id, !!event.target.closest('[data-resize-handle]')));
      box.addEventListener('click', (event) => { event.preventDefault(); event.stopPropagation(); selectLayer(el.id); });
      overlay.appendChild(box);
    });
  }
  const inspectorFields = {
    adPropText: ['text', String], adPropFontSize: ['font_size', Number], adPropWeight: ['weight', Number], adPropFont: ['font_family', String],
    adPropColor: ['color', String], adPropFill: ['fill', String], adPropStroke: ['stroke', String], adPropX: ['x', Number], adPropY: ['y', Number],
    adPropW: ['w', Number], adPropH: ['h', Number], adPropOpacity: ['opacity', (v) => Number(v) / 100], adPropRotation: ['rotation', Number],
    adPropRadius: ['radius', Number], adPropEffect: ['effect', String], adPropDelay: ['delay', Number], adPropDuration: ['motion_duration', Number], adPropShadow: ['shadow', (v) => !!v]
  };
  function renderInspector() {
    const el = getLayer(); const props = $('adLayerProperties'); const empty = $('adNoSelection');
    if (props) props.hidden = !el; if (empty) empty.hidden = !!el;
    const label = $('adSelectedLayerLabel'); if (label) label.textContent = el ? (elementNames[el.type] || 'Layer') + (el.text ? ' · ' + safeText(el.text).slice(0, 30) : '') : 'Select an element';
    if (!el) return;
    Object.entries(inspectorFields).forEach(([id, [key]]) => {
      const node = $(id); if (!node) return;
      if (node.type === 'checkbox') node.checked = !!el[key];
      else if (id === 'adPropOpacity') node.value = Math.round(Math.max(0, Math.min(1, Number(el[key] ?? 1))) * 100);
      else if (node.type === 'color') node.value = /^#[0-9a-f]{6}$/i.test(String(el[key] || '')) ? el[key] : (id === 'adPropColor' ? '#ffffff' : id === 'adPropFill' ? '#e63854' : '#10243a');
      else node.value = el[key] == null ? (id === 'adPropText' ? '' : '') : String(el[key]);
    });
    $('adPropOpacityOut').textContent = Math.round(Math.max(0, Math.min(1, Number(el.opacity ?? 1))) * 100) + '%';
    $('adPropDurationOut').textContent = (Number(el.motion_duration) || 1.2).toFixed(1) + 's';
    document.querySelectorAll('[data-ad-align]').forEach((b) => b.classList.toggle('active', b.dataset.adAlign === (el.align || 'left')));
  }
  function renderBackground() {
    const d = design(false);
    const vals = { adBgColor: d.background || '#10243a', adBgColor2: d.background2 || '#45264f', adVideoTint: d.video_tint || '#10243a', adVideoTintOpacity: Math.round(Math.max(0, Math.min(.75, Number(d.video_tint_opacity) || 0)) * 100) };
    Object.entries(vals).forEach(([id, value]) => { if ($(id)) $(id).value = value; });
    if ($('adBgGradient')) $('adBgGradient').checked = d.gradient !== false;
  }
  function renderAll() {
    updateHistoryButtons();
    currentState = api.getState() || currentState;
    activeScene = Math.max(0, Math.min(activeScene, Math.max(0, slides().length - 1)));
    if (visibleName && originalName) visibleName.value = currentState.name || originalName.value || '';
    renderTimeline(); renderLayers(); renderOverlay(); renderInspector(); renderBackground();
    if (window.DenmartAdPlayer) window.DenmartAdPlayer.setEditorScene(activeScene, true);
  }
  function selectLayer(id) { selectedLayer = id == null ? null : String(id); renderLayers(); renderOverlay(); renderInspector(); }

  function baseLayer(type, extra) {
    const defaults = {
      text: { text: 'Your text', x: 145, y: 150, w: 740, h: 140, font_size: 78, weight: 800, color: '#ffffff', fill: '#e63854' },
      number: { text: '01', x: 1420, y: 120, w: 300, h: 280, font_size: 180, weight: 900, color: '#ffffff', fill: '#ff7a21', align: 'center' },
      image: { text: '', image_url: '', x: 1120, y: 200, w: 520, h: 520, font_size: 48, weight: 700, color: '#ffffff', fill: '#ffffff', fit: 'contain', shadow: true },
      rect: { text: '', x: 120, y: 710, w: 520, h: 120, font_size: 24, weight: 800, color: '#ffffff', fill: '#e63854', radius: 18 },
      circle: { text: '', x: 1400, y: 690, w: 220, h: 220, font_size: 24, weight: 800, color: '#ffffff', fill: '#e63854' },
      line: { text: '', x: 100, y: 850, w: 680, h: 18, font_size: 24, weight: 700, color: '#ffffff', fill: '#ffffff', stroke_width: 9 },
      badge: { text: 'KES 99', x: 1390, y: 110, w: 300, h: 160, font_size: 56, weight: 900, color: '#ffffff', fill: '#e63854', align: 'center', radius: 34 },
      sticker: { text: '✦', x: 1500, y: 350, w: 180, h: 180, font_size: 150, weight: 900, color: '#ffdc41', fill: '#ffdc41', align: 'center' },
      qr: { text: '', image_url: '', x: 1590, y: 730, w: 190, h: 190, font_size: 24, weight: 800, color: '#ffffff', fill: '#ffffff', fit: 'contain' }
    };
    const layer = Object.assign({ id: uid(), type, stroke: '#ffffff', stroke_width: 0, opacity: 1, rotation: 0, align: 'left', effect: 'fade', delay: 0, motion_duration: 1.2, shadow: false, radius: 16 }, defaults[type] || defaults.text, extra || {});
    if (type === 'qr') layer.image_url = '';
    return layer;
  }
  function addLayer(type, extra) {
    checkpoint();
    const d = design(true); if (!d) return;
    const el = baseLayer(type, extra);
    d.enabled = true; d.elements = Array.isArray(d.elements) ? d.elements : []; d.elements.push(el); selectedLayer = el.id;
    shell.classList.remove('design-disabled'); syncPlayer(true); renderAll(); setStatus((elementNames[type] || 'Layer') + ' added. Drag it on the canvas to position it.');
  }
  function addCallToAction() {
    checkpoint();
    const d = design(true); if (!d) return;
    const back = baseLayer('rect', { x: 130, y: 760, w: 560, h: 112, fill: '#f5c943', radius: 24, stroke: '#ffffff', stroke_width: 0, effect: 'rise', motion_duration: 1.0, delay: .1 });
    const words = baseLayer('text', { text: 'SHOP NOW', x: 155, y: 784, w: 510, h: 70, font_size: 36, weight: 900, color: '#182538', fill: '#f5c943', align: 'center', effect: 'pop', motion_duration: .8, delay: .2 });
    d.enabled = true; d.elements.push(back, words); selectedLayer = words.id; syncPlayer(true); renderAll(); setStatus('CTA button added as two editable layers. Change the wording, colour and motion in the inspector.');
  }
  function mutateDesign(callback, refreshPlayer) {
    checkpoint();
    const d = design(true); if (!d) return;
    callback(d);
    if (refreshPlayer !== false) syncPlayer(true);
    renderOverlay(); renderLayers(); renderBackground();
  }
  function addImageLayer(url, label) {
    if (!url) return;
    addLayer('image', { image_url: url, text: label || '', x: 1080, y: 190, w: 600, h: 650, fit: 'contain', shadow: true, effect: 'zoom', motion_duration: 1.3 });
  }
  function chooseTool(tool) {
    activeTool = tool;
    document.querySelectorAll('[data-ad-tool]').forEach((button) => button.classList.toggle('active', button.dataset.adTool === tool));
    if (tool === 'image') { upload?.click(); return; }
    if (tool === 'product') { if (productDrawer) productDrawer.open = true; $('adDesignProductSearch')?.focus(); return; }
    if (tool === 'background') { if (!design(false).enabled) api.ensureDesign(activeScene); renderAll(); $('adBgColor')?.focus(); return; }
    if (tool === 'cta') { addCallToAction(); return; }
    if (['text', 'number', 'rect', 'circle', 'line', 'badge', 'sticker', 'qr'].includes(tool)) addLayer(tool);
    else setStatus('Select a layer, then drag it on the canvas or use the inspector.');
  }

  Object.entries(inspectorFields).forEach(([id, [key, convert]]) => {
    const node = $(id); if (!node) return;
    const commit = () => {
      const el = getLayer(); if (!el) return;
      const raw = node.type === 'checkbox' ? node.checked : node.value;
      const value = convert(raw);
      if (typeof value === 'number' && !Number.isFinite(value)) return;
      const limits = { x: [-500, 1920], y: [-300, 1080], w: [8, 1920], h: [8, 1080], font_size: [12, 220], weight: [400, 900], opacity: [0, 1], rotation: [-360, 360], radius: [0, 120], delay: [0, 8], motion_duration: [.2, 10] };
      el[key] = limits[key] && typeof value === 'number' ? Math.min(limits[key][1], Math.max(limits[key][0], value)) : value;
      if (id === 'adPropOpacity') $('adPropOpacityOut').textContent = Math.round(el.opacity * 100) + '%';
      if (id === 'adPropDuration') $('adPropDurationOut').textContent = Number(el.motion_duration).toFixed(1) + 's';
      syncPlayer(true); renderOverlay(); renderLayers();
      if (key === 'text') { const name = document.querySelector(`.ad-layer-handle[data-layer-id="${CSS.escape(String(el.id))}"] .ad-layer-handle-name`); if (name) name.textContent = safeText(el.text || elementNames[el.type]); }
    };
    node.addEventListener('input', commit); node.addEventListener('change', commit);
  });
  document.querySelectorAll('[data-ad-align]').forEach((button) => button.addEventListener('click', () => {
    const el = getLayer(); if (!el) return; el.align = button.dataset.adAlign; syncPlayer(true); renderInspector(); renderOverlay();
  }));

  function duplicateLayer() {
    const el = getLayer(); if (!el) return;
    const copy = JSON.parse(JSON.stringify(el)); copy.id = uid(); copy.x = Math.min(1800, (Number(copy.x) || 0) + 36); copy.y = Math.min(1000, (Number(copy.y) || 0) + 36); copy.text = copy.text ? String(copy.text) + ' copy' : copy.text;
    mutateDesign((d) => d.elements.push(copy)); selectedLayer = copy.id; renderAll(); setStatus('Layer duplicated.');
  }
  function deleteLayer() {
    if (!selectedLayer) return;
    mutateDesign((d) => { d.elements = (d.elements || []).filter((el) => String(el.id) !== String(selectedLayer)); }); selectedLayer = null; renderAll(); setStatus('Layer deleted.');
  }
  function moveLayer(amount) {
    const index = findLayerIndex(selectedLayer); if (index < 0) return;
    const next = Math.max(0, Math.min(elements().length - 1, index + amount)); if (next === index) return;
    mutateDesign((d) => { const item = d.elements.splice(index, 1)[0]; d.elements.splice(next, 0, item); }); renderAll();
  }
  $('adDuplicateLayer')?.addEventListener('click', duplicateLayer); $('adPropDuplicate')?.addEventListener('click', duplicateLayer);
  $('adDeleteLayer')?.addEventListener('click', deleteLayer); $('adPropDelete')?.addEventListener('click', deleteLayer);
  $('adLayerUp')?.addEventListener('click', () => moveLayer(1)); $('adLayerDown')?.addEventListener('click', () => moveLayer(-1));
  document.querySelectorAll('[data-ad-tool]').forEach((button) => button.addEventListener('click', () => chooseTool(button.dataset.adTool)));
  $('adStartDesign')?.addEventListener('click', () => {
    api.ensureDesign(activeScene); if (slides()[activeScene]?.design?.elements?.length) selectedLayer = slides()[activeScene].design.elements[0].id;
    api.refresh(); syncPlayer(true); renderAll(); setStatus('Scene editor enabled. Select any layer to recolour, resize, delete or animate it.', 'success');
  });
  $('adAddScene')?.addEventListener('click', () => {
    const before = slides().length; api.addScene();
    window.setTimeout(() => { state(); activeScene = Math.max(0, Math.min(slides().length - 1, slides().length > before ? slides().length - 1 : activeScene)); api.ensureDesign(activeScene); selectedLayer = slides()[activeScene]?.design?.elements?.[0]?.id || null; syncPlayer(true); renderAll(); }, 80);
  });

  function startDrag(event, layerId, resize) {
    if (event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    selectedLayer = String(layerId);
    renderLayers(); renderInspector();
    const activeBox = event.currentTarget;
    overlay.querySelectorAll('.ad-layer-handle.selected').forEach((node) => node.classList.remove('selected'));
    activeBox.classList.add('selected');
    if (!activeBox.querySelector('.ad-layer-resize')) {
      const handle = document.createElement('span'); handle.className = 'ad-layer-resize'; handle.dataset.resizeHandle = '1'; handle.setAttribute('aria-hidden', 'true'); activeBox.appendChild(handle);
    }
    const el = getLayer(); if (!el) return;
    checkpoint();
    dragState = { pointerId: event.pointerId, layerId, resize, sx: event.clientX, sy: event.clientY, x: Number(el.x) || 0, y: Number(el.y) || 0, w: Number(el.w) || 300, h: Number(el.h) || 100 };
    try { activeBox.setPointerCapture(event.pointerId); } catch (_) {}
  }
  overlay?.addEventListener('pointermove', (event) => {
    if (!dragState || (dragState.pointerId != null && event.pointerId !== dragState.pointerId)) return;
    const el = getLayer(); if (!el || String(el.id) !== String(dragState.layerId)) return;
    const rect = stage.getBoundingClientRect(); const dx = (event.clientX - dragState.sx) / Math.max(1, rect.width) * 1920; const dy = (event.clientY - dragState.sy) / Math.max(1, rect.height) * 1080;
    if (dragState.resize) { el.w = Math.max(8, Math.min(1920 - dragState.x, dragState.w + dx)); el.h = Math.max(8, Math.min(1080 - dragState.y, dragState.h + dy)); }
    else { el.x = Math.max(-500, Math.min(1920 - 8, dragState.x + dx)); el.y = Math.max(-300, Math.min(1080 - 8, dragState.y + dy)); }
    syncPlayer(true);
    const box = overlay.querySelector('.ad-layer-handle.selected');
    if (box) { box.style.left = (el.x / 1920 * 100) + '%'; box.style.top = (el.y / 1080 * 100) + '%'; box.style.width = (el.w / 1920 * 100) + '%'; box.style.height = (el.h / 1080 * 100) + '%'; }
  });
  function endDrag(event) {
    if (!dragState) return;
    if (event && dragState.pointerId != null && event.pointerId !== dragState.pointerId) return;
    dragState = null; renderAll(); setStatus('Position updated.');
  }
  overlay?.addEventListener('pointerup', endDrag); overlay?.addEventListener('pointercancel', endDrag);
  stage?.addEventListener('dragover', (event) => { event.preventDefault(); stage.classList.add('drop-ready'); });
  stage?.addEventListener('dragleave', (event) => { if (!stage.contains(event.relatedTarget)) stage.classList.remove('drop-ready'); });
  stage?.addEventListener('drop', async (event) => {
    event.preventDefault(); stage.classList.remove('drop-ready');
    const files = [...(event.dataTransfer?.files || [])].filter((file) => file.type.startsWith('image/'));
    if (files.length) { for (const file of files.slice(0, 10)) { const data = await compressImage(file); addImageLayer(data, file.name); } return; }
    const src = event.dataTransfer?.getData('application/x-denmart-image') || event.dataTransfer?.getData('text/uri-list') || event.dataTransfer?.getData('text/plain');
    if (src && /^(https?:|\/|data:image\/)/i.test(src)) addImageLayer(src, event.dataTransfer?.getData('application/x-denmart-name') || 'Product photo');
  });
  async function compressImage(file) {
    const bitmap = await new Promise((resolve, reject) => {
      const image = new Image(); image.onload = () => resolve(image); image.onerror = () => reject(new Error('This image could not be opened.')); image.src = URL.createObjectURL(file);
    });
    const url = bitmap.src;
    try {
      let scale = Math.min(1, 1500 / Math.max(bitmap.naturalWidth || bitmap.width, bitmap.naturalHeight || bitmap.height));
      let quality = .82; let out = '';
      for (let attempt = 0; attempt < 7; attempt++) {
        const c = document.createElement('canvas'); c.width = Math.max(1, Math.round((bitmap.naturalWidth || bitmap.width) * scale)); c.height = Math.max(1, Math.round((bitmap.naturalHeight || bitmap.height) * scale));
        const ctx = c.getContext('2d'); ctx.drawImage(bitmap, 0, 0, c.width, c.height);
        out = c.toDataURL('image/webp', quality);
        if (out.length <= 440000) break;
        if (quality > .56) quality -= .08; else scale *= .78;
      }
      if (out.length > 460000) throw new Error('This picture is too detailed to store in the campaign. Choose a smaller photo.');
      return out;
    } finally { URL.revokeObjectURL(url); }
  }
  upload?.addEventListener('change', async () => {
    const files = [...(upload.files || [])].slice(0, 10); if (!files.length) return;
    api.ensureDesign(activeScene);
    try {
      for (const file of files) { if (!file.type.startsWith('image/')) continue; const src = await compressImage(file); addImageLayer(src, file.name); }
      setStatus(files.length + ' image' + (files.length === 1 ? '' : 's') + ' added to this scene.', 'success');
    } catch (error) { setStatus(error.message || 'Could not add that image.', 'error'); }
    upload.value = '';
  });

  $('adApplyBackground')?.addEventListener('click', () => {
    mutateDesign((d) => { d.enabled = true; d.background = $('adBgColor').value; d.background2 = $('adBgColor2').value; d.gradient = $('adBgGradient').checked; d.video_tint = $('adVideoTint').value; d.video_tint_opacity = Number($('adVideoTintOpacity').value || 0) / 100; });
    syncPlayer(true); renderAll(); setStatus('Background and video colour updated.');
  });
  ['adBgColor', 'adBgColor2', 'adBgGradient', 'adVideoTint', 'adVideoTintOpacity'].forEach((id) => $(id)?.addEventListener('change', () => {
    mutateDesign((d) => { d.enabled = true; d.background = $('adBgColor').value; d.background2 = $('adBgColor2').value; d.gradient = $('adBgGradient').checked; d.video_tint = $('adVideoTint').value; d.video_tint_opacity = Number($('adVideoTintOpacity').value || 0) / 100; }, true);
  }));

  async function searchProducts() {
    const input = $('adDesignProductSearch'); const host = $('adDesignProductResults'); if (!input || !host) return;
    const q = input.value.trim(); if (!q) { host.textContent = 'Type a product name, brand or barcode to find saved catalogue items.'; return; }
    host.textContent = 'Searching the saved product and barcode catalogue…';
    try {
      const response = await fetch('/advertcontrol/api/products?q=' + encodeURIComponent(q), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } });
      const result = await response.json();
      if (response.status === 401 && result.login_url) { location.href = result.login_url; return; }
      if (!response.ok || !result.ok) throw new Error(result.error || 'Product search failed.');
      host.replaceChildren();
      if (!result.items || !result.items.length) { host.textContent = 'No saved products match this search. Try a barcode, brand or shorter name.'; return; }
      result.items.forEach((product) => {
        const card = document.createElement('article'); card.className = 'ad-design-product-card'; card.draggable = true;
        const image = document.createElement('img'); const src = product.image_url || (product.image_urls && product.image_urls[0]) || '';
        image.alt = safeText(product.name) + ' product photo'; image.loading = 'lazy'; image.draggable = false;
        if (src) image.src = src; else { image.src = '/static/images/product-unavailable.svg'; image.onerror = () => { image.onerror = null; image.removeAttribute('src'); image.alt = 'No verified photo'; }; }
        const details = document.createElement('div'); const title = document.createElement('strong'); title.textContent = safeText(product.name); const meta = document.createElement('small'); meta.textContent = [product.brand, product.barcode ? 'Barcode ' + product.barcode : ''].filter(Boolean).join(' · ') || 'Saved catalogue product';
        const add = document.createElement('button'); add.type = 'button'; add.textContent = src ? 'Add image' : 'Add item'; add.disabled = !src; add.addEventListener('click', () => addImageLayer(src, product.name));
        details.append(title, meta, add); card.append(image, details);
        card.addEventListener('dragstart', (event) => { if (!src) { event.preventDefault(); return; } event.dataTransfer.setData('application/x-denmart-image', src); event.dataTransfer.setData('application/x-denmart-name', safeText(product.name)); event.dataTransfer.setData('text/plain', src); event.dataTransfer.effectAllowed = 'copy'; });
        host.appendChild(card);
      });
      setStatus('Found ' + result.items.length + ' authentic catalogue entries. Photos are loaded from saved images or exact-barcode lookups.');
    } catch (error) { host.textContent = error.message || 'Could not search products.'; setStatus(error.message || 'Product lookup failed.', 'error'); }
  }
  $('adDesignProductSearchButton')?.addEventListener('click', searchProducts);
  $('adDesignProductSearch')?.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); searchProducts(); } });
  $('adDesignProductSearch')?.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(searchProducts, 350); });

  $('adDesignSave')?.addEventListener('click', () => { if (visibleName && originalName) originalName.value = visibleName.value; api.save(false); });
  $('adDesignPublish')?.addEventListener('click', () => { if (visibleName && originalName) originalName.value = visibleName.value; api.save(true); });
  $('adUploadFinishedVideo')?.addEventListener('click', () => { if (advanced) advanced.open = true; window.setTimeout(() => $('adVideoUpload')?.click(), 50); });
  $('adOpenAdvanced')?.addEventListener('click', () => { if (advanced) { advanced.open = !advanced.open; if (advanced.open) advanced.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } });
  $('adDesignExport')?.addEventListener('click', () => {
    if (window.DenmartAdPlayer) window.DenmartAdPlayer.setEditorScene(activeScene, false);
    $('exportVideo')?.click();
    const started = Date.now();
    const watcher = setInterval(() => {
      const progress = $('exportProgress'); const button = $('exportVideo');
      if ((progress && progress.hidden && button && !button.disabled && Date.now() - started > 700) || Date.now() - started > 180000) {
        clearInterval(watcher); if (window.DenmartAdPlayer) { window.DenmartAdPlayer.setCampaign(api.getState(), true); window.DenmartAdPlayer.setEditorScene(activeScene, true); }
      }
    }, 350);
  });
  const oldSave = $('saveDraft'); if (oldSave) oldSave.addEventListener('click', () => { if (visibleName && originalName) originalName.value = visibleName.value; });
  const oldPublish = $('publishAd'); if (oldPublish) oldPublish.addEventListener('click', () => { if (visibleName && originalName) originalName.value = visibleName.value; });

  const statusSource = $('studioStatus');
  if (statusSource && window.MutationObserver) new MutationObserver(() => {
    const value = statusSource.textContent.trim(); if (value) setStatus(value, statusSource.classList.contains('error') ? 'error' : statusSource.classList.contains('success') ? 'success' : '');
  }).observe(statusSource, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class'] });
  window.addEventListener('denmart:statechange', () => {
    const before = activeScene; currentState = api.getState() || currentState;
    if (visibleName && originalName) visibleName.value = currentState.name || originalName.value || '';
    activeScene = Math.max(0, Math.min(activeScene, Math.max(0, slides().length - 1)));
    if (before !== activeScene || !getLayer()) selectedLayer = null;
    renderTimeline(); renderLayers(); renderOverlay(); renderInspector(); renderBackground();
    if (window.DenmartAdPlayer) window.DenmartAdPlayer.setEditorScene(activeScene, true);
  });
  window.addEventListener('resize', renderOverlay);

  // A single public destination is kept in the visible top bar; legacy mini/resize preview
  // controls and secondary public-display links remain out of the everyday workspace.
  const publicLink = document.querySelector('.ad-studio-nav-actions a[href="/advertisement"]');
  if (publicLink) { publicLink.href = '/'; publicLink.target = '_blank'; publicLink.rel = 'noopener'; publicLink.textContent = 'Open public site ↗'; }
  renderAll();
  if (window.DenmartAdPlayer) window.DenmartAdPlayer.setEditorScene(0, true);
})();
