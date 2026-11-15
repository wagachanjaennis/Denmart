const $=s=>document.querySelector(s);
const money=n=>Number(n||0).toFixed(2);
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
let cart=[];
const VIEW_TITLES={sale:'New sale',catalogue:'Catalogue',held:'Held sales',summary:'Today',shift:'Shift'};
async function apiJSON(url,opts={}){try{const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...opts});let d={};try{d=await r.json()}catch(_e){}return {r,d}}catch(error){return {r:{ok:false,status:0},d:{error:'connection_unavailable',message:'Connection unavailable.'}}}}
function toast(msg){const el=$('#posToast');if(el){el.textContent=msg;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2600)}}
const posStoreMeta=document.querySelector('meta[name="pos-store-id"]')?.content||'';
if(posStoreMeta){try{localStorage.setItem('denmart-pos-current-store',posStoreMeta)}catch(_e){}}
const posStoreId=posStoreMeta||(()=>{try{return localStorage.getItem('denmart-pos-current-store')||'default'}catch(_e){return 'default'}})();
const OFFLINE_CATALOG_KEY='denmart-pos-catalog-'+posStoreId;
const OFFLINE_SALES_KEY='denmart-pos-pending-cash-'+posStoreId;
const POS_CART_KEY='denmart-pos-current-cart-'+posStoreId;
const HOLD_KEY='denmart-held-sales-v8-'+posStoreId;
const MAX_OFFLINE_CATALOGUE=12000;
const deviceStore=window.DenmartOffline;
function localRead(key,fallback){try{const value=JSON.parse(localStorage.getItem(key)||'null');return value==null?fallback:value}catch(_e){return fallback}}
function localWrite(key,value){try{localStorage.setItem(key,JSON.stringify(value));return true}catch(_e){return false}}
async function readOfflineCatalogue(){let rows;try{rows=await deviceStore?.get(OFFLINE_CATALOG_KEY)}catch(_e){}if(Array.isArray(rows))return rows;rows=localRead(OFFLINE_CATALOG_KEY,[]);if(Array.isArray(rows)&&rows.length){try{await deviceStore?.set(OFFLINE_CATALOG_KEY,rows)}catch(_e){}}return Array.isArray(rows)?rows:[]}
async function writeOfflineCatalogue(rows){const safe=(rows||[]).slice(0,MAX_OFFLINE_CATALOGUE);try{if(deviceStore)await deviceStore.set(OFFLINE_CATALOG_KEY,safe);else if(!localWrite(OFFLINE_CATALOG_KEY,safe))throw new Error('local storage full');}catch(_e){toast('The offline catalogue could not be saved completely. Keep this till online and refresh the catalogue before working offline.');return false;}/* Small localStorage mirror only; IndexedDB holds the full catalogue. */localWrite(OFFLINE_CATALOG_KEY,safe.slice(0,500));return true}
let catalogueMergeChain=Promise.resolve();
function mergeOfflineCatalogue(rows){if(!Array.isArray(rows)||!rows.length)return Promise.resolve();catalogueMergeChain=catalogueMergeChain.then(async()=>{const current=await readOfflineCatalogue();const byId=new Map(current.map(x=>[String(x.id),x]));rows.forEach(x=>{if(x&&x.id!=null)byId.set(String(x.id),{id:x.id,name:x.name||'',barcode:x.barcode||'',price:Number(x.price||0),stock:Number(x.stock||0),available:Number(x.available??x.stock??0)})});await writeOfflineCatalogue([...byId.values()].sort((a,b)=>String(a.name).localeCompare(String(b.name))).slice(0,MAX_OFFLINE_CATALOGUE));});return catalogueMergeChain}
async function offlineFindBarcode(code){const q=normalizeScannedBarcode(code);return (await readOfflineCatalogue()).find(x=>normalizeScannedBarcode(x.barcode)===q)}
async function offlineSearch(q){const text=String(q||'').trim().toLocaleLowerCase();const rows=await readOfflineCatalogue();if(!text)return rows.slice(0,50);const exact=rows.filter(x=>normalizeScannedBarcode(x.barcode)===normalizeScannedBarcode(text));if(exact.length)return exact.slice(0,10);return rows.filter(x=>String(x.name||'').toLocaleLowerCase().includes(text)||String(x.barcode||'').toLocaleLowerCase().includes(text)).slice(0,50)}
let offlineWarmBusy=false;
async function warmOfflineCatalogue(){if(offlineWarmBusy||!navigator.onLine||!posStoreMeta)return;offlineWarmBusy=true;try{let offset=0,total=0;do{const z=await apiJSON('/api/pos/products/offline-catalogue?offset='+offset+'&limit=500');if(!z.r.ok||!z.d.ok)break;total=Number(z.d.total||0);await mergeOfflineCatalogue(z.d.items||[]);offset+=Number(z.d.items?.length||0);if(!z.d.items?.length||offset>=Math.min(total,MAX_OFFLINE_CATALOGUE))break;if(offset>0)await new Promise(resolve=>setTimeout(resolve,80));}while(offset<total);if(total>0)toast('Offline catalogue saved: '+Math.min(total,MAX_OFFLINE_CATALOGUE)+' products');}finally{offlineWarmBusy=false}}
async function readOfflineSales(){let rows;try{rows=await deviceStore?.get(OFFLINE_SALES_KEY)}catch(_e){}if(Array.isArray(rows))return rows;rows=localRead(OFFLINE_SALES_KEY,[]);if(!Array.isArray(rows))rows=[];if(rows.length)try{await deviceStore?.set(OFFLINE_SALES_KEY,rows)}catch(_e){}return rows}
async function saveOfflineSales(rows){try{if(deviceStore)await deviceStore.set(OFFLINE_SALES_KEY,rows);else if(!localWrite(OFFLINE_SALES_KEY,rows))throw new Error('local storage full');localWrite(OFFLINE_SALES_KEY,rows.slice(-30));return true}catch(_e){return false}}
async function updateOfflineQueueCount(){const n=(await readOfflineSales()).length;document.querySelectorAll('#offlineQueueCount').forEach(el=>{el.textContent=n?`${n} sale${n===1?'':'s'} waiting to sync`:'Offline queue clear'});}
async function queueOfflineCashSale(items,reason='Offline',clientRef=''){if(!Array.isArray(items)||!items.length)return false;const queue=await readOfflineSales();const ref=clientRef||('DM-OFF-'+Date.now().toString(36).toUpperCase()+'-'+cryptoRandom());if(queue.some(x=>x.client_ref===ref)){toast('This sale is already safely queued on this device.');return true;}if(queue.length>=1000){toast('Offline queue is at its safety limit. This sale was NOT saved; keep the basket and reconnect to sync existing sales.');return false;}const record={client_ref:ref,items:items.map(x=>({store_product_id:x.id,quantity:x.qty,unit_price:Number(x.price),product_name:String(x.name||'')})),queued_at:new Date().toISOString(),store_id:posStoreId};queue.push(record);const saved=await saveOfflineSales(queue);if(!saved){toast('Device storage could not confirm this sale was saved. The basket has been kept; do not clear it.');return false;}await updateOfflineQueueCount();toast(`${reason}: saved on this device, NOT completed; approval required`);const note=$('#posCashFeedback');if(note)note.textContent=`${queue.length} cash sale(s) waiting to sync. IndexedDB saved the queue locally. These are NOT completed or paid. Keep goods until the server receives and an administrator approves each sale.`;return true;}
let offlineSyncBusy=false;
async function syncOfflineSales(){if(offlineSyncBusy||!navigator.onLine)return;const queue=await readOfflineSales();if(!queue.length)return;offlineSyncBusy=true;try{let remaining=[...queue],sent=0;for(let start=0;start<queue.length;start+=50){const chunk=queue.slice(start,start+50);const z=await apiJSON('/api/pos/sync/offline',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sales:chunk})});if(!z.r.ok||!Array.isArray(z.d.results)){if(z.r.status===401||z.r.status===403){const note=$('#posCashFeedback');if(note)note.textContent='Offline sales remain safely stored on this device. Sign in to the till online, then sync again; no queued sale has been removed.';toast('Offline sales are safe. Sign in online to sync them.');}break;}const accepted=new Set();z.d.results.forEach((result,index)=>{if(result.ok)accepted.add(chunk[index]?.client_ref)});sent+=accepted.size;remaining=remaining.filter(x=>!accepted.has(x.client_ref));if(!accepted.size){const issue=(z.d.results||[]).find(r=>!r.ok);if(issue){const note=$('#posCashFeedback');if(note)note.textContent=issue.message||`Offline sale remains saved locally: ${issue.error||'server validation needs attention'}. Nothing was removed from the device queue.`;toast(issue.message||`Offline sale needs attention: ${issue.error||'validation failed'}`);}break;}}const saved=await saveOfflineSales(remaining);await updateOfflineQueueCount();if(!saved){toast('Warning: sync results could not be saved locally. Reopen this till online and check pending approvals before retrying.');return;}if(sent){const note=$('#posCashFeedback');if(note)note.textContent=`${sent} offline sale(s) reached the server and await administrator approval. They are NOT completed until approved.`;toast(`${sent} offline sale(s) synced · approval still required`);}}finally{offlineSyncBusy=false}}
function cryptoRandom(){try{return crypto.randomUUID().replace(/-/g,'').slice(0,12).toUpperCase()}catch(_e){return Math.random().toString(36).slice(2,14).toUpperCase()}}
function add(id,name,price){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before changing this basket.');const i=cart.find(x=>x.id===id);if(i)i.qty+=1;else cart.push({id,name,price:Number(price),qty:1});renderCart()}
function productButton(x){return `<button class="product-result" onclick="add('${esc(x.id)}','${esc(x.name)}',${Number(x.price||0)})"><span><strong>${esc(x.name)}</strong><small>${esc(x.barcode||'')}</small></span><b>KES ${money(x.price)}</b></button>`}
function renderCart(){const el=$('#saleLines'),totalEl=$('#saleTotal');if(!el)return;try{deviceStore?.set(POS_CART_KEY,cart.map(x=>({...x})));localWrite(POS_CART_KEY,cart.map(x=>({...x})));}catch(_e){}let total=0;el.innerHTML=cart.map((x,i)=>{const line=x.price*x.qty;total+=line;return `<div class="sale-line"><div><strong>${esc(x.name)}</strong><small>KES ${money(x.price)} each</small></div><div class="cart-qty"><button onclick="cartQty(${i},-1)">−</button><b>${x.qty}</b><button onclick="cartQty(${i},1)">+</button><strong>KES ${money(line)}</strong></div></div>`}).join('')||'<div class="muted">Basket is empty.</div>';if(totalEl)totalEl.textContent=money(total)}
function cartQty(i,d){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before changing this basket.');const x=cart[i];if(!x)return;x.qty+=d;if(x.qty<=0)cart.splice(i,1);renderCart()}
function renderProductResults(items, emptyMessage='No matching product.') {const el=$('#productResults');if(el)el.innerHTML=(items||[]).map(productButton).join('')||`<div class="pos-empty">${esc(emptyMessage)}</div>`}
function normalizeScannedBarcode(raw){let code=String(raw||'').trim().replace(/[\r\n\t]/g,'').replace(/^\](?:C1|d2|Q3|A0)/i,'');const parenthesized=code.match(/\(01\)\s*(\d{14})/);if(parenthesized)return parenthesized[1];const gs1=code.match(/(?:^|[\x1d])01(\d{14})/);if(gs1)return gs1[1];return code.replace(/[\x1d\x00-\x08\x0B\x0C\x0E-\x1F]/g,'').trim()}
const numericBarcode=q=>/^\d{8,14}$/.test(normalizeScannedBarcode(q));
let lastScannerBurstAt=0, lastBarcodeHandled='', lastBarcodeHandledAt=0, barcodeRequestInFlight='';
async function searchPOS(options={}){
  const input=$('#posSearch');const raw=(input?.value||'').trim();if(!raw)return;const q=normalizeScannedBarcode(raw);
  const barcode=numericBarcode(raw)||(/^[A-Za-z0-9._:/+%-]{10,80}$/.test(raw)&&!raw.includes(' ')&&(options.scanner===true||Date.now()-lastScannerBurstAt<1400));
  if(barcode){
    if(barcodeRequestInFlight===q)return;
    if(lastBarcodeHandled===q&&Date.now()-lastBarcodeHandledAt<700)return;
    lastBarcodeHandled=q;lastBarcodeHandledAt=Date.now();
    barcodeRequestInFlight=q;
    try{
      if(!navigator.onLine){const cached=await offlineFindBarcode(q);if(cached){add(cached.id,cached.name,cached.price);renderProductResults([],`${cached.name} found in the offline catalogue.`);toast(`${cached.name} added from offline catalogue`);if(input)input.value='';}else{renderProductResults([],`Barcode ${q} is not in this device's cached catalogue. Reconnect or add it to Products first.`);toast('Barcode not available offline');}return;}
      const z=await apiJSON('/api/pos/products/barcode/'+encodeURIComponent(q));
      if(z.r.ok&&z.d?.id){await mergeOfflineCatalogue([{...z.d,available:z.d.stock??0}]);add(z.d.id,z.d.name,z.d.price);lastBarcodeHandled=q;lastBarcodeHandledAt=Date.now();renderProductResults([],`${z.d.name} added to basket.`);toast(`${z.d.name} added · KES ${money(z.d.price)}`);if(input){setTimeout(()=>{if(input.value.trim()===q)input.value='';},80)}return;}
      const cached=await offlineFindBarcode(q);if(z.r.status===0&&cached){add(cached.id,cached.name,cached.price);renderProductResults([],`${cached.name} found in the offline catalogue.`);toast(`${cached.name} added from offline catalogue`);return;}
      renderProductResults([],z.r.status===0?`Could not reach the server and barcode ${q} is not cached on this device.`:`Barcode ${q} was not found in this mart's active POS catalogue. Add or link the product in Products first.`);toast('Barcode not found');return;
    }finally{barcodeRequestInFlight=''}
  }
  if(!navigator.onLine){const cached=await offlineSearch(q);renderProductResults(cached,cached.length?'Offline catalogue results. Stock/price must be confirmed when syncing.':'No cached match. Reconnect to search the full catalogue.');return;}
  const z=await apiJSON('/api/pos/products/search?q='+encodeURIComponent(q));
  if(z.r.ok){await mergeOfflineCatalogue(z.d.items||[]);renderProductResults(z.d.items||[])}else{const cached=await offlineSearch(q);if(cached.length)renderProductResults(cached,'Connection unavailable · showing saved catalogue matches.');else renderProductResults([],'Product search is temporarily unavailable.');}
}
async function autoScanPOS(value){const q=String(value||'').trim();if(!q)return;lastScannerBurstAt=Date.now();await searchPOS({scanner:true})}
async function searchCatalogue(){const q=$('#catalogueSearch')?.value.trim()||'';const el=$('#catalogueResults');if(!navigator.onLine){const rows=await offlineSearch(q);if(el)el.innerHTML=rows.map(productButton).join('')||'<div class="pos-empty">No cached match available offline.</div>';return}const z=await apiJSON('/api/pos/products/search?q='+encodeURIComponent(q));if(z.r.ok){await mergeOfflineCatalogue(z.d.items||[]);if(el)el.innerHTML=(z.d.items||[]).map(productButton).join('')||'<div class="pos-empty">No matching product.</div>'}else{const rows=await offlineSearch(q);if(el)el.innerHTML=rows.map(productButton).join('')||'<div class="pos-empty">Catalogue unavailable.</div>'}}
async function makeSale(){if(posPaymentPoll)return toast('An electronic payment is active. Wait for its receipt or administrator review before submitting a cash sale.');if(!cart.length)return toast('Basket is empty');const snapshot=cart.map(x=>({...x}));if(!navigator.onLine&&!String(document.querySelector('.agent-shift-chip')?.textContent||'').includes('OPEN'))return toast('This till has no confirmed open shift in its saved state. Reconnect and open a shift before accepting offline cash sales.');const clientRef='DM-LOCAL-'+Date.now().toString(36).toUpperCase()+'-'+cryptoRandom();if(!navigator.onLine){if(await queueOfflineCashSale(snapshot,'Offline',clientRef)){cart=[];renderCart()}return}const z=await apiJSON('/api/pos/sales',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_ref:clientRef,items:snapshot.map(x=>({store_product_id:x.id,quantity:x.qty,unit_price:Number(x.price),product_name:String(x.name||'')}))})});if(z.r.status===0){if(await queueOfflineCashSale(snapshot,'Connection lost',clientRef)){cart=[];renderCart()}return}if(!z.r.ok)return toast(z.d.message||z.d.error||'Sale was not submitted; basket kept on this device');if(z.d.status==='PENDING_APPROVAL'||z.d.approval_required){const note=$('#posCashFeedback');if(note)note.textContent=`Cash sale ${z.d.receipt_number||''} submitted. Awaiting administrator approval. This sale is NOT completed; stock is reserved until approval, and no receipt is available yet.`;toast('Cash sale submitted · awaiting approval');cart=[];renderCart();return}toast('Sale status: '+(z.d.status||'unknown'));}

async function openShift(){const z=await apiJSON('/api/pos/shifts/open',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});toast(z.r.ok?'Shift opened.':(z.d.error||'Could not open shift'));if(z.r.ok)location.reload()}
async function closeShift(){const z=await apiJSON('/api/pos/shifts/close',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});toast(z.r.ok?'Shift closed.':(z.d.error||'Could not close shift'));if(z.r.ok)setTimeout(()=>location.reload(),700)}
window.loadDaySummary=async()=>{const z=await apiJSON('/api/pos/day-summary');if(!z.r.ok)return toast(z.d.error||'Summary unavailable');const el=$('#summaryCards');if(el)el.innerHTML=`<div class="mini-stat"><small>Sales count</small><strong>${z.d.sales_count}</strong></div><div class="mini-stat"><small>Sales total</small><strong>KES ${money(z.d.sales_total)}</strong></div>`};
window.holdSale=async function(){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before holding this basket.');if(!cart.length)return toast('Basket is empty');let h=[];try{h=await deviceStore?.get(HOLD_KEY)||localRead(HOLD_KEY,[])}catch(_e){h=localRead(HOLD_KEY,[])}h.push({at:new Date().toISOString(),items:cart.map(x=>({...x}))});try{if(deviceStore)await deviceStore.set(HOLD_KEY,h);else if(!localWrite(HOLD_KEY,h))throw new Error('storage full');localWrite(HOLD_KEY,h.slice(-100));cart=[];renderCart();await renderHeld();toast('Sale held safely on this till')}catch(_e){toast('Could not confirm the held sale was saved. Basket kept.');}};
window.resumeHeld=async function(i){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before replacing this basket.');let h=[];try{h=await deviceStore?.get(HOLD_KEY)||localRead(HOLD_KEY,[])}catch(_e){h=localRead(HOLD_KEY,[])}const x=h.splice(i,1)[0];if(!x)return;cart=x.items||[];try{if(deviceStore)await deviceStore.set(HOLD_KEY,h);localWrite(HOLD_KEY,h)}catch(_e){}renderCart();await renderHeld();document.querySelector('[data-view="sale"]')?.click();toast('Held sale recalled')};
window.renderHeld=async function(){const el=$('#heldList');if(!el)return;let h=[];try{h=await deviceStore?.get(HOLD_KEY)||localRead(HOLD_KEY,[])}catch(_e){h=localRead(HOLD_KEY,[])}el.innerHTML=h.map((x,i)=>`<div class="activity-row"><div><strong>Held sale ${i+1}</strong><small>${new Date(x.at).toLocaleString()} · ${(x.items||[]).length} lines</small></div><button class="admin-action" onclick="resumeHeld(${i})">Recall</button></div>`).join('')||'<div class="muted">No held sales on this till.</div>'};
window.exportOfflineBackup=async function(){try{const payload={format:'DenmartOfflineBackup',version:1,exported_at:new Date().toISOString(),store_id:posStoreId,pending_cash_sales:await readOfflineSales(),held_sales:await deviceStore?.get(HOLD_KEY)||localRead(HOLD_KEY,[]),current_basket:cart.map(x=>({...x})),catalogue:await readOfflineCatalogue()};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='denmart-offline-backup-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Offline backup exported. Store it somewhere safe.');}catch(_e){toast('Could not export the device backup. Keep this till open and reconnect.');}};
window.syncOfflineSalesNow=async function(){if(!navigator.onLine){toast('You are offline. Queued sales remain on this device; reconnect to sync.');return;}await syncOfflineSales();if(!(await readOfflineSales()).length)toast('No offline sales remain in the device queue.');};
function renderHeld(){window.renderHeld()}
function setupViews(){document.querySelectorAll('.agent-nav-link').forEach(btn=>btn.addEventListener('click',()=>{const view=btn.dataset.view;document.querySelectorAll('.agent-nav-link').forEach(b=>b.classList.toggle('active',b===btn));document.querySelectorAll('.agent-view').forEach(p=>p.classList.toggle('active',p.dataset.panel===view));const title=$('#agentTitle');if(title)title.textContent=VIEW_TITLES[view]||'Merchant Till';if(view==='held')renderHeld();if(view==='summary')loadDaySummary();if(view==='catalogue')searchCatalogue()}))}
let scanBuffer='',scanTimer=null;
function handleKeyboardScanner(e){const active=document.activeElement;if(['INPUT','TEXTAREA','SELECT'].includes(active?.tagName))return;if(/^\d$/.test(e.key)){scanBuffer+=e.key;clearTimeout(scanTimer);scanTimer=setTimeout(()=>scanBuffer='',180);return}if(e.key==='Enter'&&scanBuffer.length>=8){const code=scanBuffer;scanBuffer='';lastScannerBurstAt=Date.now();e.preventDefault();const input=$('#posSearch');if(input)input.value=code;autoScanPOS(code)}if(e.key==='Escape'){scanBuffer='';cart=[];renderCart()}}
window.addEventListener('keydown',handleKeyboardScanner);
const posSearchInput=$('#posSearch');
if(posSearchInput){
  let inputTimer=null, burstStart=0, previousLength=0, burstChars=0;
  posSearchInput.addEventListener('input',()=>{
    const q=posSearchInput.value.trim();const t=performance.now();
    if(q.length>previousLength&&t-(window.__denmartLastPosInputAt||0)<80)burstChars+=q.length-previousLength;else if(q.length<=previousLength||t-(window.__denmartLastPosInputAt||0)>180)burstChars=0;
    window.__denmartLastPosInputAt=t;previousLength=q.length;
    if(inputTimer)clearTimeout(inputTimer);
    if(numericBarcode(q)) {inputTimer=setTimeout(()=>autoScanPOS(q),180);return;}
    if(q.length>=10&&!q.includes(' ')&&burstChars>=5){lastScannerBurstAt=Date.now();inputTimer=setTimeout(()=>autoScanPOS(q),180);return;}
    // Do not auto-run normal text queries: the operator can review results as they type or press Find.
  });
  posSearchInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();const q=posSearchInput.value.trim();if(numericBarcode(q)||(!q.includes(' ')&&q.length>=10&&(burstChars>=5||Date.now()-lastScannerBurstAt<1400))){lastScannerBurstAt=Date.now();autoScanPOS(q)}else searchPOS();}});
}
window.addEventListener('online',()=>{const s=$('#networkStatus');if(s)s.textContent='ONLINE';syncOfflineSales();warmOfflineCatalogue()});window.addEventListener('offline',()=>{const s=$('#networkStatus');if(s)s.textContent='OFFLINE'});
setInterval(()=>{const c=$('#posSessionClock');if(c)c.textContent=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})},30000);
setupViews();(async()=>{try{await deviceStore?.persistStorage();let saved=await deviceStore?.get(POS_CART_KEY);if(!Array.isArray(saved))saved=localRead(POS_CART_KEY,[]);if(Array.isArray(saved))cart=saved;const localCatalog=localRead(OFFLINE_CATALOG_KEY,[]);if(Array.isArray(localCatalog)&&localCatalog.length){const existing=await readOfflineCatalogue();if(existing.length<localCatalog.length)await mergeOfflineCatalogue(localCatalog)}renderCart();await renderHeld();await updateOfflineQueueCount();if(navigator.onLine){warmOfflineCatalogue();syncOfflineSales()}else{const n=(await readOfflineSales()).length;const note=$('#posCashFeedback');if(note&&n)note.textContent=`${n} offline sale(s) are stored locally. They are NOT completed. Reconnect to sync and wait for approval.`}}catch(_e){toast('Offline storage could not be checked. Keep this till open and reconnect before accepting more sales.')}loadDaySummary()})();

let posPaymentPoll=null, posPaymentPollBusy=false, posPaymentCreateBusy=false;
function paymentFeedback(message, kind='') {const el=$('#posPaymentFeedback');if(el){el.textContent=message||'';el.className=`tiny-help pos-payment-feedback ${kind}`.trim()}}
function paymentInstructions(data) {
  const el=$('#posPaymentInstructions');if(!el)return;
  if(!data){el.textContent='';return;}
  const bits=[];
  if(data.label)bits.push(String(data.label));
  if(data.method==='PAYBILL'){if(data.paybill_number)bits.push(`PayBill: ${data.paybill_number}`);if(data.account_name)bits.push(`Account: ${data.account_name}`)}
  if(data.method==='BUY_GOODS'&&data.till_number)bits.push(`M-PESA Till: ${data.till_number}`);
  if(data.method==='BANK_TRANSFER'){if(data.account_name)bits.push(`Account holder: ${data.account_name}`);if(data.account_number)bits.push(`Account number: ${data.account_number}`)}
  if(data.instructions)bits.push(String(data.instructions));
  el.textContent=bits.join(' · ');
}
window.clearCart=function(){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before clearing this basket.');cart=[];renderCart()};
window.startPosPayment=function(){if(posPaymentPoll)return toast('An electronic payment is already active for this basket.');if(!cart.length)return toast('Basket is empty');const box=$('#posPayBox');if(box)box.hidden=false;const link=$('#posPaymentReceiptLink');if(link){link.hidden=true;link.textContent='';}paymentFeedback('Choose M-PESA or bank transfer. The payer name will be read from the gateway receipt automatically.');paymentInstructions(null)};
window.createPOSPayment=async function(){
  if(posPaymentCreateBusy)return;
  if(posPaymentPoll)return toast('A payment request is already active for this till. Wait for the receipt or ask the administrator to review it.');
  if(!cart.length)return toast('Basket is empty');
  const method=$('#posPaymentMethod')?.value||'MPESA';
  const basketSnapshot=cart.map(x=>({...x}));
  posPaymentCreateBusy=true;const btn=$('#posPaymentStart');if(btn)btn.disabled=true;
  try{
    const z=await apiJSON('/api/pos/pay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payment_method:method,items:basketSnapshot.map(x=>({store_product_id:x.id,quantity:x.qty}))})});
    if(!z.r.ok){paymentFeedback(z.d.error||'Could not create payment.');return toast(z.d.error||'Could not create payment')}
    paymentInstructions(z.d.payment_instructions);
    paymentFeedback(`Waiting for an incoming ${method==='BANK_TRANSFER'?'bank credit':'M-PESA'} receipt matching KES ${money(z.d.amount)}. Do not ask the customer for their name or phone.`, 'is-waiting');
    toast('Waiting for automatic payment matching');
    if(posPaymentPoll)clearInterval(posPaymentPoll);
    const poll=async()=>{
      if(posPaymentPollBusy)return;posPaymentPollBusy=true;
      try{
        const s=await apiJSON('/api/pos/pay/'+encodeURIComponent(z.d.payment_id));if(!s.r.ok)return;
        const status=s.d.payment_status;
        if(status==='PAID'&&s.d.receipt_number){
          clearInterval(posPaymentPoll);posPaymentPoll=null;cart=[];renderCart();const box=$('#posPayBox');if(box)box.hidden=true;
          paymentFeedback(s.d.confirmation_message||`Payment confirmed. Receipt ${s.d.receipt_number}.`, 'is-success');
          if(btn)btn.disabled=false;
          const link=$('#posPaymentReceiptLink');if(link){link.href='/merchant/receipt/'+encodeURIComponent(s.d.receipt_number);link.hidden=false;link.textContent=`Open receipt ${s.d.receipt_number}`;}
          toast('Payment confirmed · sale completed');
        } else if(status==='MANUAL_REVIEW') {
          const payer=s.d.payer_name?`${s.d.payer_name} `:'';const amt=s.d.receipt_amount?`KES ${money(s.d.receipt_amount)} `:'';
          paymentFeedback(s.d.confirmation_message||`${payer}${amt}receipt requires administrator review. The basket is held until approval.`, 'is-review');
        } else if(status==='EXPIRED'||status==='PAYMENT_UNMATCHED') {
          clearInterval(posPaymentPoll);posPaymentPoll=null;if(btn)btn.disabled=false;
          paymentFeedback(s.d.confirmation_message||'No safe matching payment was found. Check the gateway messages or ask the administrator to review.', 'is-review');
        } else {
          paymentFeedback(s.d.confirmation_message||`Waiting for ${method==='BANK_TRANSFER'?'bank':'M-PESA'} receipt · KES ${money(z.d.amount)}.`, 'is-waiting');
        }
      } finally {posPaymentPollBusy=false}
    };
    posPaymentPoll=setInterval(poll,2500);poll();
  } finally {posPaymentCreateBusy=false;if(btn)btn.disabled=Boolean(posPaymentPoll);}
};
const paymentMethodSelect=$('#posPaymentMethod');if(paymentMethodSelect)paymentMethodSelect.addEventListener('change',()=>{paymentInstructions(null);paymentFeedback(paymentMethodSelect.value==='BANK_TRANSFER'?'Bank receipt auto-matching requires the administrator to configure the bank account number and instructions.':'M-PESA receipt auto-matching is ready. Customer name and phone are not required.');});
