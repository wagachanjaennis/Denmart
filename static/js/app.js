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
  window.placeOrder=async function(){
    const c=read();if(!c.length)return toast('Basket is empty');
    const paymentMethod=document.querySelector('input[name="paymentMethod"]:checked')?.value||'stk';
    const payload={store_code:new URLSearchParams(location.search).get('store')||window.DENMART_STORE||'',items:c.map(x=>({store_product_id:x.id,quantity:x.qty})),customer:{name:document.getElementById('custName').value.trim(),phone:document.getElementById('custPhone').value.trim(),email:document.getElementById('custEmail').value.trim()},delivery_address:document.getElementById('deliveryAddress').value.trim()};
    if(!payload.customer.name||!payload.customer.phone)return toast('Name and phone are required');
    
    const button=document.querySelector('.checkout-form .primary-btn');if(button){button.disabled=true;button.textContent='Preparing your order…'}
    try{
      const r=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials:'same-origin'});const d=await r.json();if(!r.ok)throw new Error(d.error||'Order could not be placed');
      if(paymentMethod==='till'){
        const approvalMode=document.querySelector('input[name="approvalMode"]:checked')?.value||'AUTO';
        const p=await fetch('/api/payments/till/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:d.order_id,phone_number:payload.customer.phone,mpesa_reference:document.getElementById('mpesaReference')?.value.trim()||'',approval_mode:approvalMode}),credentials:'same-origin'});
        const pd=await p.json();
        save([]);
        if(!p.ok)throw new Error(pd.error||'Till payment could not be submitted');
        location.href='/order/'+encodeURIComponent(d.order_number)+'?payment='+encodeURIComponent(pd.payment_id);
        return;
      }
      const p=await fetch('/api/payments/mpesa/initiate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:d.order_id,amount:d.total,phone_number:payload.customer.phone}),credentials:'same-origin'});const pd=await p.json();
      if(p.ok){save([]);location.href='/order/'+encodeURIComponent(d.order_number)+'?payment='+encodeURIComponent(pd.payment_id);return;}
      // Backup plan: when the API/STK route is unavailable, switch to automatic Till monitoring.
      if((p.status===503||p.status===502) && window.DENMART_TILL){
        const g=await fetch('/api/payments/till/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:d.order_id,phone_number:payload.customer.phone,mpesa_reference:'',approval_mode:'AUTO'}),credentials:'same-origin'});
        const gd=await g.json();
        save([]);
        if(g.ok){location.href='/order/'+encodeURIComponent(d.order_number)+'?payment='+encodeURIComponent(gd.payment_id);return;}
      }
      save([]);location.href='/order/'+encodeURIComponent(d.order_number)+'?payment_error=1';
    }catch(e){toast(e.message||'Checkout failed');if(button){button.disabled=false;button.textContent='Place order & continue to payment'}}
  };

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

  // Product image recovery: missing catalogue photos render local artwork immediately,
  // then the first nearby cards quietly try the exact-photo resolver. This never delays
  // the storefront and never replaces a working photograph with placeholder art.
  const startProductImageRecovery=()=>{
    const found=[...document.querySelectorAll('img[data-product-resolve]')];
    if(!found.length || !window.fetch)return;
    const imgs=found.slice(0,36);
    let active=0, cursor=0;
    const next=()=>{
      while(active<2 && cursor<imgs.length){
        const img=imgs[cursor++];
        if(!img||img.dataset.resolving==='1')continue;
        active++; img.dataset.resolving='1';
        fetch(img.dataset.productResolve,{credentials:'same-origin',cache:'no-store'})
          .then(r=>r.ok?r.blob():null)
          .then(blob=>{
            if(!blob || !String(blob.type||'').startsWith('image/') || blob.type==='image/svg+xml')return;
            const objectUrl=URL.createObjectURL(blob);
            const probe=new Image();
            probe.onload=()=>{img.src=objectUrl;};
            probe.onerror=()=>URL.revokeObjectURL(objectUrl);
            probe.src=objectUrl;
          })
          .catch(()=>{})
          .finally(()=>{active--;next();});
      }
    };
    const visibleFirst=imgs;
    cursor=0;
    if('IntersectionObserver' in window){
      const io=new IntersectionObserver(entries=>{
        for(const entry of entries){
          if(entry.isIntersecting){
            const img=entry.target;
            const pos=imgs.indexOf(img);
            if(pos>=0 && pos<36){imgs.splice(pos,1);imgs.unshift(img);}
            io.unobserve(img);
            next();
          }
        }
      },{rootMargin:'500px 0px'});
      visibleFirst.forEach(img=>io.observe(img));
    }else{next();}
  };
  startProductImageRecovery();
  updateCounts();renderCartPage();
  if(document.getElementById('checkoutSummary')){const c=read();document.getElementById('checkoutSummary').innerHTML=c.map(x=>`<div class="summary-line"><span>${escapeHtml(x.name)} × ${x.qty}</span><b>${money(x.price*x.qty)}</b></div>`).join('')||'<span class="muted">No items.</span>';document.getElementById('checkoutTotal').textContent=c.reduce((s,x)=>s+x.price*x.qty,0).toFixed(2);}
  if(!location.pathname.startsWith('/control')&&!location.pathname.startsWith('/merchant')&&'serviceWorker' in navigator){navigator.serviceWorker.register('/shop/sw.js',{scope:'/'}).catch(()=>{});}
})();


function shareDenmartShop(){
  const data={title:'Denmart Online Shop',text:'Shop Denmart online',url:window.location.origin+'/shop'};
  if(navigator.share){ navigator.share(data).catch(()=>{}); return; }
  if(navigator.clipboard){ navigator.clipboard.writeText(data.url).then(()=>alert('Denmart shop link copied.')).catch(()=>{}); }
}
