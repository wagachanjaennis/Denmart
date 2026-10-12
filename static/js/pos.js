const $=s=>document.querySelector(s);
const money=n=>Number(n||0).toFixed(2);
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
let cart=[];
const HOLD_KEY='denmart-held-sales-v7';
const VIEW_TITLES={sale:'New sale',catalogue:'Catalogue',held:'Held sales',summary:'Today',shift:'Shift'};
async function apiJSON(url,opts={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...opts});let d={};try{d=await r.json()}catch(_e){}return {r,d}}
function toast(msg){const el=$('#posToast');if(el){el.textContent=msg;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200)}}
function add(id,name,price){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before changing this basket.');const i=cart.find(x=>x.id===id);if(i)i.qty+=1;else cart.push({id,name,price:Number(price),qty:1});renderCart()}
function productButton(x){return `<button class="product-result" onclick="add('${esc(x.id)}','${esc(x.name)}',${Number(x.price||0)})"><span><strong>${esc(x.name)}</strong><small>${esc(x.barcode||'')}</small></span><b>KES ${money(x.price)}</b></button>`}
function renderCart(){const el=$('#saleLines'),totalEl=$('#saleTotal');if(!el)return;let total=0;el.innerHTML=cart.map((x,i)=>{const line=x.price*x.qty;total+=line;return `<div class="sale-line"><div><strong>${esc(x.name)}</strong><small>KES ${money(x.price)} each</small></div><div class="cart-qty"><button onclick="cartQty(${i},-1)">−</button><b>${x.qty}</b><button onclick="cartQty(${i},1)">+</button><strong>KES ${money(line)}</strong></div></div>`}).join('')||'<div class="muted">Basket is empty.</div>';if(totalEl)totalEl.textContent=money(total)}
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
      const z=await apiJSON('/api/pos/products/barcode/'+encodeURIComponent(q));
      if(z.r.ok&&z.d?.id){
        add(z.d.id,z.d.name,z.d.price);
        lastBarcodeHandled=q;lastBarcodeHandledAt=Date.now();
        renderProductResults([],`${z.d.name} added to basket.`);
        toast(`${z.d.name} added · KES ${money(z.d.price)}`);
        if(input){setTimeout(()=>{if(input.value.trim()===q)input.value='';},80)}
        return;
      }
      // A barcode is an identifier, not a text-search query. Never fall back to
      // fuzzy search here: that was what showed milk/bread for unrelated codes.
      renderProductResults([],`Barcode ${q} was not found in this mart's active POS catalogue. Add or link the product in Products first.`);
      toast('Barcode not found in this mart');
      return;
    }finally{barcodeRequestInFlight=''}
  }
  const z=await apiJSON('/api/pos/products/search?q='+encodeURIComponent(q));
  if(z.r.ok)renderProductResults(z.d.items||[]);else renderProductResults([],'Product search is temporarily unavailable.');
}
async function autoScanPOS(value){const q=String(value||'').trim();if(!q)return;lastScannerBurstAt=Date.now();await searchPOS({scanner:true})}
async function searchCatalogue(){const q=$('#catalogueSearch')?.value.trim()||'';const z=await apiJSON('/api/pos/products/search?q='+encodeURIComponent(q));const el=$('#catalogueResults');if(el)el.innerHTML=z.r.ok?(z.d.items||[]).map(productButton).join('')||'<div class="pos-empty">No matching product.</div>':'<div class="pos-empty">Catalogue unavailable.</div>'}
async function makeSale(){if(posPaymentPoll)return toast('An electronic payment is active. Wait for its receipt or administrator review before completing a cash sale.');if(!cart.length)return toast('Basket is empty');const z=await apiJSON('/api/pos/sales',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:cart.map(x=>({store_product_id:x.id,quantity:x.qty}))})});if(!z.r.ok)return toast(z.d.error||'Sale failed');toast('Cash sale complete · '+z.d.receipt_number);window.open('/merchant/receipt/'+encodeURIComponent(z.d.receipt_number),'_blank','noopener');cart=[];renderCart()}
async function openShift(){const z=await apiJSON('/api/pos/shifts/open',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});toast(z.r.ok?'Shift opened.':(z.d.error||'Could not open shift'));if(z.r.ok)location.reload()}
async function closeShift(){const z=await apiJSON('/api/pos/shifts/close',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});toast(z.r.ok?'Shift closed.':(z.d.error||'Could not close shift'));if(z.r.ok)setTimeout(()=>location.reload(),700)}
window.loadDaySummary=async()=>{const z=await apiJSON('/api/pos/day-summary');if(!z.r.ok)return toast(z.d.error||'Summary unavailable');const el=$('#summaryCards');if(el)el.innerHTML=`<div class="mini-stat"><small>Sales count</small><strong>${z.d.sales_count}</strong></div><div class="mini-stat"><small>Sales total</small><strong>KES ${money(z.d.sales_total)}</strong></div>`};
window.holdSale=function(){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before holding this basket.');if(!cart.length)return toast('Basket is empty');const h=JSON.parse(localStorage.getItem(HOLD_KEY)||'[]');h.push({at:new Date().toISOString(),items:cart});localStorage.setItem(HOLD_KEY,JSON.stringify(h));cart=[];renderCart();renderHeld();toast('Sale held on this till')};
window.resumeHeld=function(i){if(posPaymentPoll)return toast('An electronic payment is active. Resolve it before replacing this basket.');const h=JSON.parse(localStorage.getItem(HOLD_KEY)||'[]');const x=h.splice(i,1)[0];if(!x)return;cart=x.items||[];localStorage.setItem(HOLD_KEY,JSON.stringify(h));renderCart();renderHeld();document.querySelector('[data-view="sale"]')?.click();toast('Held sale recalled')};
window.renderHeld=function(){const el=$('#heldList');if(!el)return;const h=JSON.parse(localStorage.getItem(HOLD_KEY)||'[]');el.innerHTML=h.map((x,i)=>`<div class="activity-row"><div><strong>Held sale ${i+1}</strong><small>${new Date(x.at).toLocaleString()} · ${(x.items||[]).length} lines</small></div><button class="admin-action" onclick="resumeHeld(${i})">Recall</button></div>`).join('')||'<div class="muted">No held sales on this till.</div>'};
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
window.addEventListener('online',()=>{const s=$('#networkStatus');if(s)s.textContent='ONLINE'});window.addEventListener('offline',()=>{const s=$('#networkStatus');if(s)s.textContent='OFFLINE'});
setInterval(()=>{const c=$('#posSessionClock');if(c)c.textContent=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})},30000);
setupViews();renderCart();renderHeld();loadDaySummary();

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
