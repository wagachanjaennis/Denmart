(function(){
  const KEY='denmart-cart-v13';
  const read=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch(e){return[]}};
  const save=c=>localStorage.setItem(KEY,JSON.stringify(c));
  const money=n=>'KES '+Number(n||0).toFixed(2);
  window.addToCart=function(id,name,price){const c=read();const i=c.find(x=>x.id===id);if(i)i.qty+=1;else c.push({id,name,price:Number(price),qty:1});save(c);updateCounts();toast(name+' added');};
  window.updateCounts=function(){document.querySelectorAll('[data-cart-count]').forEach(e=>e.textContent=read().reduce((s,x)=>s+x.qty,0));};
  window.toast=function(msg){let t=document.querySelector('.toast');if(!t){t=document.createElement('div');t.className='toast';document.body.appendChild(t)}t.textContent=msg;t.classList.add('show');clearTimeout(window._toast);window._toast=setTimeout(()=>t.classList.remove('show'),1800)};
  window.renderCartPage=function(){const wrap=document.getElementById('cartPage');if(!wrap)return;const c=read();let total=0;if(!c.length){wrap.innerHTML='<div class="empty-shop"><strong>Your basket is empty.</strong><a href="/shop">Find something to buy →</a></div>';document.getElementById('checkoutLink').classList.add('disabled');document.getElementById('cartGrandTotal').textContent='0.00';return;}wrap.innerHTML=c.map((x,i)=>{const line=x.price*x.qty;total+=line;return `<article class="cart-row"><div class="cart-row-img"></div><div class="cart-row-main"><strong>${escapeHtml(x.name)}</strong><span>${money(x.price)}</span></div><div class="cart-qty"><button onclick="cartQty(${i},-1)">−</button><b>${x.qty}</b><button onclick="cartQty(${i},1)">+</button></div><strong>${money(line)}</strong><button class="remove" onclick="cartRemove(${i})">×</button></article>`}).join('');document.getElementById('cartGrandTotal').textContent=total.toFixed(2);};
  window.cartQty=function(i,d){const c=read();if(!c[i])return;c[i].qty+=d;if(c[i].qty<=0)c.splice(i,1);save(c);renderCartPage();updateCounts();};
  window.cartRemove=function(i){const c=read();c.splice(i,1);save(c);renderCartPage();updateCounts();};
  const PENDING_CHECKOUT_KEY='denmart-pending-checkout-v1';
  const readPendingCheckout=()=>{try{return JSON.parse(sessionStorage.getItem(PENDING_CHECKOUT_KEY)||'null')}catch(_e){return null}};
  const savePendingCheckout=v=>{try{if(v)sessionStorage.setItem(PENDING_CHECKOUT_KEY,JSON.stringify(v));else sessionStorage.removeItem(PENDING_CHECKOUT_KEY)}catch(_e){}};
  const fetchJson=async (url,options={})=>{
    const response=await fetch(url,{credentials:'same-origin',...options});
    let data=null;
    try{data=await response.json();}catch(_e){}
    if(!response.ok){
      const err=new Error(data?.error||data?.message||`Request failed (${response.status})`);
      err.status=response.status;err.data=data;
      throw err;
    }
    return data||{};
  };
  const tillPaymentPayload=(pending,reference='')=>({
    order_id:pending.order_id,
    phone_number:pending.phone,
    mpesa_reference:reference,
    approval_mode:'AUTO',
    payment_destination_id:pending.payment_destination_id||window.DENMART_PAYMENT_DESTINATION_ID||''
  });

  async function submitTillPayment(pending){
    let lastError=null;
    for(let attempt=0;attempt<2;attempt++){
      try{
        const reference=document.getElementById('mpesaReference')?.value.trim()||pending.reference||'';
        return await fetchJson('/api/payments/till/submit',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(tillPaymentPayload(pending,reference))
        });
      }catch(e){
        lastError=e;
        if(attempt===0 && (!e.status || e.status===408 || e.status===429 || e.status>=500)){
          await new Promise(resolve=>setTimeout(resolve,700));
          continue;
        }
        break;
      }
    }
    throw lastError||new Error('Till payment could not be submitted');
  }

  window.placeOrder=async function(){
    const c=read();
    if(!c.length)return toast('Basket is empty');
    const paymentMethod=document.querySelector('input[name="paymentMethod"]:checked')?.value||'stk';
    const name=document.getElementById('custName')?.value.trim()||'';
    const phone=document.getElementById('custPhone')?.value.trim()||'';
    const email=document.getElementById('custEmail')?.value.trim()||'';
    const deliveryAddress=document.getElementById('deliveryAddress')?.value.trim()||'';
    if(!name||!phone)return toast('Name and phone are required');

    const button=document.getElementById('placeOrderButton')||document.querySelector('.checkout-form .primary-btn');
    const setBusy=(busy,label)=>{if(button){button.disabled=busy;button.textContent=label}};
    setBusy(true,'Preparing your order…');

    try{
      let pending=readPendingCheckout();
      const storeCode=new URLSearchParams(location.search).get('store')||window.DENMART_STORE||'';

      // A previous click may have created the order but lost the browser before
      // the payment step completed. Reuse that order instead of creating a duplicate.
      if(pending && pending.payment_method===paymentMethod && pending.phone===phone){
        if(paymentMethod==='till'){
          const pd=await submitTillPayment(pending);
          savePendingCheckout(null);save([]);
          location.href='/order/'+encodeURIComponent(pending.order_number)+'?payment='+encodeURIComponent(pd.payment_id);
          return;
        }
        try{
          const pd=await fetchJson('/api/payments/mpesa/initiate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:pending.order_id,amount:pending.total,phone_number:phone})});
          savePendingCheckout(null);save([]);
          location.href='/order/'+encodeURIComponent(pending.order_number)+'?payment='+encodeURIComponent(pd.payment_id);
          return;
        }catch(e){
          if(e.status!==404){
            setBusy(false,'Place order & continue to payment');
            return toast(e.message||'Payment could not be started. Please try again.');
          }
          savePendingCheckout(null);pending=null;
        }
      }

      const orderPayload={
        store_code,
        items:c.map(x=>({store_product_id:x.id,quantity:x.qty})),
        customer:{name,phone,email},
        delivery_address:deliveryAddress,
        delivery_notes:'',
        payment_method:paymentMethod
      };
      const d=await fetchJson('/api/orders',{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(orderPayload)
      });
      pending={order_id:d.order_id,order_number:d.order_number,total:d.total,phone,payment_method:paymentMethod,reference:'',payment_destination_id:window.DENMART_PAYMENT_DESTINATION_ID||''};
      savePendingCheckout(pending);

      if(paymentMethod==='till'){
        const pd=await submitTillPayment(pending);
        savePendingCheckout(null);save([]);
        location.href='/order/'+encodeURIComponent(d.order_number)+'?payment='+encodeURIComponent(pd.payment_id);
        return;
      }

      try{
        const pd=await fetchJson('/api/payments/mpesa/initiate',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({order_id:d.order_id,amount:d.total,phone_number:phone})
        });
        savePendingCheckout(null);save([]);
        location.href='/order/'+encodeURIComponent(d.order_number)+'?payment='+encodeURIComponent(pd.payment_id);
        return;
      }catch(e){
        // Existing automatic-Till fallback remains available, but the order is kept
        // in sessionStorage until a real payment step succeeds.
        if((e.status===503||e.status===502||e.status===504) && window.DENMART_TILL){
          try{
            pending.payment_method='till';savePendingCheckout(pending);
            const gd=await submitTillPayment(pending);
            savePendingCheckout(null);save([]);
            location.href='/order/'+encodeURIComponent(d.order_number)+'?payment='+encodeURIComponent(gd.payment_id);
            return;
          }catch(fallbackError){
            throw fallbackError;
          }
        }
        throw e;
      }
    }catch(e){
      setBusy(false,'Place order & continue to payment');
      reportClientError(e.message||'Checkout failed','','','', 'CHECKOUT_REQUEST_FAILED');
      toast(e.message||'Checkout failed. Your basket has been kept so you can retry.');
    }
  };

  const checkoutForm=document.getElementById('checkoutForm');
  const placeOrderButton=document.getElementById('placeOrderButton');
  if(checkoutForm){
    checkoutForm.addEventListener('submit',event=>{
      event.preventDefault();
      if(placeOrderButton?.disabled)return;
      window.placeOrder();
    });
  }else{
    placeOrderButton?.addEventListener('click',event=>{
      event.preventDefault();
      window.placeOrder();
    });
  }

  const tillFields=document.getElementById('tillFields');
  if(tillFields){
    const paintTillFields=()=>{tillFields.hidden=document.querySelector('input[name="paymentMethod"]:checked')?.value!=='till';};
    document.querySelectorAll('input[name="paymentMethod"]').forEach(r=>r.addEventListener('change',paintTillFields));
    paintTillFields();
  }


  function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}



  // Browser-side failures are useful operational evidence too. Keep the payload small and
  // never include form values, tokens, payment data, or customer details.
  const reportClientError=(message,source='',line=0,column=0,code='CLIENT_ERROR')=>{
    try{
      const body=JSON.stringify({message:String(message||'Browser error').slice(0,900),source:String(source||'').slice(0,280),line,column,code});
      const url='/api/client-errors';
      if(navigator.sendBeacon){navigator.sendBeacon(url,new Blob([body],{type:'application/json'}));}
      else{fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true}).catch(()=>{});}
    }catch(_e){}
  };
  window.addEventListener('error',event=>reportClientError(event.message,event.filename,event.lineno,event.colno,'WINDOW_ERROR'));
  window.addEventListener('unhandledrejection',event=>reportClientError(event.reason?.message||String(event.reason||'Unhandled promise rejection'),'','', '', 'UNHANDLED_REJECTION'));

  // PWA install experience: use the browser's real install prompt when available.
  const isStandalone = () => window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent || '');
  const installPrompt = document.getElementById('pwaInstallPrompt');
  const installButton = document.getElementById('pwaInstallButton');
  const installLink = document.getElementById('pwaInstallLink');
  const installDismiss = document.getElementById('pwaInstallDismiss');
  let deferredInstallPrompt = null;
  if (isStandalone()) { document.documentElement.classList.add('pwa-standalone'); document.body.classList.add('pwa-standalone'); }
  const hideInstallUi = () => { if (installPrompt) installPrompt.hidden = true; if (installLink) installLink.hidden = true; };
  const showInstallUi = () => { if (!isStandalone()) { if (installPrompt) installPrompt.hidden = false; if (installLink) installLink.hidden = false; } };
  window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); deferredInstallPrompt = event; showInstallUi(); });
  window.addEventListener('appinstalled', () => { deferredInstallPrompt = null; hideInstallUi(); toast('Denmart was installed as an app'); });
  const startInstall = async () => {
    if (deferredInstallPrompt) {
      deferredInstallPrompt.prompt();
      const choice = await deferredInstallPrompt.userChoice.catch(() => ({outcome:'dismissed'}));
      if (choice.outcome === 'accepted') hideInstallUi();
      deferredInstallPrompt = null;
      return;
    }
    if (isIos && !isStandalone()) {
      toast('On iPhone/iPad: tap Share, then Add to Home Screen');
      return;
    }
    toast('Use your browser menu and choose Install app or Add to Home Screen.');
  };
  installButton?.addEventListener('click', startInstall);
  installLink?.addEventListener('click', startInstall);
  installDismiss?.addEventListener('click', () => { if (installPrompt) installPrompt.hidden = true; });
  if (isIos && !isStandalone() && installPrompt && !sessionStorage.getItem('denmart-install-dismissed')) {
    setTimeout(() => { installPrompt.hidden = false; installButton.textContent = 'How to install'; }, 4500);
  }
  installDismiss?.addEventListener('click', () => sessionStorage.setItem('denmart-install-dismissed', '1'));

  // Installed storefronts should feel like apps rather than pull-to-refresh web pages.
  if (isStandalone()) {
    let touchStartY = 0;
    document.addEventListener('touchstart', e => { if (e.touches.length === 1) touchStartY = e.touches[0].clientY; }, {passive:true});
    document.addEventListener('touchmove', e => {
      if (e.touches.length !== 1 || window.scrollY > 0) return;
      const pullingDown = e.touches[0].clientY - touchStartY > 8;
      if (pullingDown) e.preventDefault();
    }, {passive:false});
  }
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.ready.then(reg => { if (reg.update) reg.update().catch(() => {}); }).catch(() => {});
  }

  // Product images are deterministic same-origin assets prepared at build time.
  updateCounts();renderCartPage();
  if(document.getElementById('checkoutSummary')){const c=read();document.getElementById('checkoutSummary').innerHTML=c.map(x=>`<div class="summary-line"><span>${escapeHtml(x.name)} × ${x.qty}</span><b>${money(x.price*x.qty)}</b></div>`).join('')||'<span class="muted">No items.</span>';document.getElementById('checkoutTotal').textContent=c.reduce((s,x)=>s+x.price*x.qty,0).toFixed(2);}
  if(!location.pathname.startsWith('/control')&&!location.pathname.startsWith('/merchant')&&'serviceWorker' in navigator){navigator.serviceWorker.register('/shop/sw.js',{scope:'/'}).catch(()=>{});}
})();


function shareDenmartShop(){
  const data={title:'Denmart Online Shop',text:'Shop Denmart online',url:window.location.origin+'/shop'};
  if(navigator.share){ navigator.share(data).catch(()=>{}); return; }
  if(navigator.clipboard){ navigator.clipboard.writeText(data.url).then(()=>alert('Denmart shop link copied.')).catch(()=>{}); }
}
