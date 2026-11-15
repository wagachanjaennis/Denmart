(function(){
  const KEY='denmart-cart-v14';
  let liveCart=null, cartWriteVersion=0;
  const read=()=>{if(Array.isArray(liveCart))return liveCart.map(x=>({...x}));try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch(e){return[]}};
  const save=c=>{const snapshot=(c||[]).map(x=>({...x}));liveCart=snapshot;cartWriteVersion++;let localSaved=false;try{localStorage.setItem(KEY,JSON.stringify(snapshot));localSaved=true}catch(_e){}let persistPromise=window.DenmartOffline?.set(KEY,snapshot);Promise.resolve(persistPromise).then(ok=>{if(!ok&&!localSaved)window.DenmartOffline?.showNotice('The basket could not be confirmed in device storage. Keep this page open and reconnect before leaving.','warning',9000)}).catch(()=>{if(!localSaved)window.DenmartOffline?.showNotice('The basket could not be confirmed in device storage. Keep this page open and reconnect before leaving.','warning',9000)});};
  async function hydrateCart(){const started=cartWriteVersion;try{const cached=await window.DenmartOffline?.get(KEY);if(cartWriteVersion!==started){await window.DenmartOffline?.set(KEY,read());return;}if(Array.isArray(cached)){liveCart=cached.map(x=>({...x}));try{localStorage.setItem(KEY,JSON.stringify(liveCart))}catch(_e){}}else{liveCart=read();await window.DenmartOffline?.set(KEY,liveCart);}}catch(_e){}updateCounts();renderCartPage();}
  const publicCatalogueKey=(storeId='',storeCode='')=>`public:catalogue:${storeId||storeCode||'default'}`;
  async function cacheRenderedProducts(){if(!window.DenmartOffline)return;try{const form=document.querySelector('.site-search');const key=publicCatalogueKey(form?.dataset.storeId||'',form?.dataset.storeCode||'');const items=[...document.querySelectorAll('.product-card[data-product-id]')].map(card=>({id:card.dataset.productId,name:card.dataset.productName||'',price:Number(card.dataset.productPrice||0),slug:card.dataset.productSlug||'',brand:card.dataset.productBrand||'',category:card.dataset.productCategory||'',image_url:card.dataset.productImage||'',in_stock:card.dataset.productInStock!=='false'}));if(items.length)await window.DenmartOffline.mergeCatalogue(items,key,12000);}catch(_e){}}
  const money=n=>'KES '+Number(n||0).toFixed(2);
  const escapeHtml=s=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  window.addToCart=function(id,name,price){const c=read();const i=c.find(x=>x.id===id);if(i)i.qty+=1;else c.push({id,name,price:Number(price),qty:1});save(c);updateCounts();toast(name+' added');};
  window.updateCounts=function(){document.querySelectorAll('[data-cart-count]').forEach(e=>e.textContent=read().reduce((s,x)=>s+x.qty,0));};
  window.toast=function(msg){let t=document.querySelector('.toast');if(!t){t=document.createElement('div');t.className='toast';document.body.appendChild(t)}t.textContent=msg;t.classList.add('show');clearTimeout(window._toast);window._toast=setTimeout(()=>t.classList.remove('show'),1800)};
  window.renderCartPage=function(){const wrap=document.getElementById('cartPage');if(!wrap)return;const c=read();let total=0;if(!c.length){wrap.innerHTML='<div class="empty-shop"><strong>Your basket is empty.</strong><a href="/shop">Find something to buy →</a></div>';const totalEl=document.getElementById('cartGrandTotal');if(totalEl)totalEl.textContent='0.00';return;}wrap.innerHTML=c.map((x,i)=>{const line=x.price*x.qty;total+=line;return `<article class="cart-row"><div class="cart-row-img"></div><div class="cart-row-main"><strong>${escapeHtml(x.name)}</strong><span>${money(x.price)}</span></div><div class="cart-qty"><button onclick="cartQty(${i},-1)">−</button><b>${x.qty}</b><button onclick="cartQty(${i},1)">+</button></div><strong>${money(line)}</strong><button class="remove" onclick="cartRemove(${i})">×</button></article>`}).join('');const totalEl=document.getElementById('cartGrandTotal');if(totalEl)totalEl.textContent=total.toFixed(2);};
  window.cartQty=function(i,d){const c=read();if(!c[i])return;c[i].qty+=d;if(c[i].qty<=0)c.splice(i,1);save(c);renderCartPage();updateCounts();};
  window.cartRemove=function(i){const c=read();c.splice(i,1);save(c);renderCartPage();updateCounts();};
  const reportClientError=(message,source='',line=0,column=0,code='CLIENT_ERROR')=>{try{const body=JSON.stringify({message:String(message||'Browser error').slice(0,900),source:String(source||'').slice(0,280),line,column,code});const url='/api/client-errors';if(navigator.sendBeacon)navigator.sendBeacon(url,new Blob([body],{type:'application/json'}));else fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true}).catch(()=>{});}catch(_e){}};
  window.addEventListener('error',event=>reportClientError(event.message,event.filename,event.lineno,event.colno,'WINDOW_ERROR'));
  window.addEventListener('unhandledrejection',event=>reportClientError(event.reason?.message||String(event.reason||'Unhandled promise rejection'),'','','','UNHANDLED_REJECTION'));
  const isStandalone=()=>window.matchMedia?.('(display-mode: standalone)').matches||window.navigator.standalone===true; const isIos=/iphone|ipad|ipod/i.test(navigator.userAgent||'');
  const installPrompt=document.getElementById('pwaInstallPrompt'),installButton=document.getElementById('pwaInstallButton'),installLink=document.getElementById('pwaInstallLink'),installDismiss=document.getElementById('pwaInstallDismiss'); let deferredInstallPrompt=null;
  const hideInstallUi=()=>{if(installPrompt)installPrompt.hidden=true;if(installLink)installLink.hidden=true}; const showInstallUi=()=>{if(!isStandalone()){if(installPrompt)installPrompt.hidden=false;if(installLink)installLink.hidden=false}};
  if(isStandalone()){document.documentElement.classList.add('pwa-standalone');document.body.classList.add('pwa-standalone');}
  window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();deferredInstallPrompt=e;showInstallUi()}); window.addEventListener('appinstalled',()=>{deferredInstallPrompt=null;hideInstallUi();toast('Denmart was installed as an app')});
  const startInstall=async()=>{if(deferredInstallPrompt){deferredInstallPrompt.prompt();const choice=await deferredInstallPrompt.userChoice.catch(()=>({outcome:'dismissed'}));if(choice.outcome==='accepted')hideInstallUi();deferredInstallPrompt=null;return;}if(isIos&&!isStandalone()){toast('On iPhone/iPad: tap Share, then Add to Home Screen');return;}toast('Use your browser menu and choose Install app or Add to Home Screen.')};
  installButton?.addEventListener('click',startInstall);installLink?.addEventListener('click',startInstall);installDismiss?.addEventListener('click',()=>{if(installPrompt)installPrompt.hidden=true;sessionStorage.setItem('denmart-install-dismissed','1')});
  if(isIos&&!isStandalone()&&installPrompt&&!sessionStorage.getItem('denmart-install-dismissed'))setTimeout(()=>{installPrompt.hidden=false;installButton.textContent='How to install'},4500);
  if(isStandalone()){let touchStartY=0;document.addEventListener('touchstart',e=>{if(e.touches.length===1)touchStartY=e.touches[0].clientY},{passive:true});document.addEventListener('touchmove',e=>{if(e.touches.length!==1||window.scrollY>0)return;if(e.touches[0].clientY-touchStartY>8)e.preventDefault()},{passive:false});}
  if('serviceWorker' in navigator)navigator.serviceWorker.ready.then(reg=>reg.update?.().catch(()=>{})).catch(()=>{});
  // Live public-catalogue search. Results are returned by the same ranked search
  // endpoint used by the rest of Denmart; relevance is never reordered by photos.
  const searchForms=[...document.querySelectorAll('.live-search-form')];
  const searchEsc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const searchMoney=n=>Number(n||0).toLocaleString('en-KE',{minimumFractionDigits:0,maximumFractionDigits:2});
  searchForms.forEach(form=>{
    const input=form.querySelector('input[name="q"]'), dropdown=form.querySelector('.live-search-dropdown');
    if(!input||!dropdown)return;
    let timer=null, requestId=0, controller=null;
    const isShopForm=form.id==='shopLiveSearch';
    const grid=isShopForm?document.getElementById('liveShopGrid'):null;
    const feedback=isShopForm?document.getElementById('liveSearchFeedback'):null;
    const originalGrid=grid?grid.innerHTML:'';
    const storeId=form.dataset.storeId||'';
    const storeCode=form.dataset.storeCode||'';
    const categoryId=form.dataset.categoryId||'';
    const hide=()=>{dropdown.hidden=true;dropdown.innerHTML='';};
    const productUrl=item=>'/product/'+encodeURIComponent(item.slug||'')+(storeCode?'?store='+encodeURIComponent(storeCode):'');
    const renderSuggestions=items=>{
      dropdown.innerHTML='';
      if(!items.length){const empty=document.createElement('div');empty.className='live-search-empty';empty.textContent='No matching products. Try another name, brand or barcode.';dropdown.appendChild(empty);dropdown.hidden=false;return;}
      items.slice(0,9).forEach(item=>{
        const option=document.createElement('button');option.type='button';option.className='live-search-option';option.setAttribute('role','option');
        const title=document.createElement('span');title.className='live-search-option-name';title.textContent=item.name||'Product';
        const meta=document.createElement('small');meta.textContent=(item.brand?item.brand+' · ':'')+'KES '+searchMoney(item.price);
        option.append(title,meta);option.addEventListener('click',()=>{window.location.href=productUrl(item)});dropdown.appendChild(option);
      });
      dropdown.hidden=false;
    };
    const renderShopGrid=items=>{
      if(!grid)return;
      grid.innerHTML='';
      if(!items.length){const empty=document.createElement('div');empty.className='empty-state';empty.innerHTML='<strong>No matching products.</strong><span>Try another product name, brand, SKU or barcode.</span>';grid.appendChild(empty);return;}
      items.forEach(item=>{
        const article=document.createElement('article');article.className='product-card';
        const link=document.createElement('a');link.className='product-image product-image-clean';link.href=productUrl(item);
        if(item.image_url){const image=document.createElement('img');image.loading='lazy';image.src=item.image_url;image.alt=item.name||'Product';image.referrerPolicy='no-referrer';image.addEventListener('error',()=>{image.remove();link.classList.add('image-unavailable');const label=document.createElement('span');label.className='image-unavailable-label';label.textContent='Image unavailable';link.appendChild(label)},{once:true});link.appendChild(image)}else{link.classList.add('image-unavailable');const label=document.createElement('span');label.className='image-unavailable-label';label.textContent='Image unavailable';link.appendChild(label)}
        const info=document.createElement('div');info.className='product-info';
        const brand=document.createElement('span');brand.className='product-brand';brand.textContent=item.brand||'Everyday';
        const title=document.createElement('a');title.className='product-title';title.href=productUrl(item);title.textContent=item.name||'Product';
        const bottom=document.createElement('div');bottom.className='product-bottom';const price=document.createElement('strong');price.textContent='KES '+searchMoney(item.price);
        const inStock=item.in_stock!==false;const add=document.createElement('button');add.type='button';add.textContent=inStock?'Add':'Unavailable';add.disabled=!inStock;add.setAttribute('aria-label',inStock?'Add '+(item.name||'product')+' to basket':'Out of stock');if(inStock)add.addEventListener('click',()=>window.addToCart(String(item.id),item.name||'Product',Number(item.price||0)));if(!inStock){const stock=document.createElement('span');stock.className='product-stock-status';stock.textContent='Out of stock';info.append(brand,title,stock)}else info.append(brand,title);
        bottom.append(price,add);info.append(bottom);article.append(link,info);grid.appendChild(article);
      });
    };
    const search=async()=>{
      const q=input.value.trim();
      if(q.length<2){hide();if(isShopForm){if(q===''){grid.innerHTML=originalGrid;if(feedback)feedback.textContent='Showing the catalogue. Start typing to filter products instantly.'}else{grid.innerHTML='<div class="empty-state"><strong>Keep typing…</strong><span>Enter at least two characters to search the catalogue.</span></div>';if(feedback)feedback.textContent='Enter at least two characters to search.'}}return;}
      const id=++requestId;if(controller)controller.abort();controller=new AbortController();
      const params=new URLSearchParams({q});if(storeId)params.set('store_id',storeId);else if(storeCode)params.set('store',storeCode);if(categoryId)params.set('category_id',categoryId);
      try{
        const response=await fetch('/api/products/search?'+params.toString(),{credentials:'same-origin',signal:controller.signal,headers:{'Accept':'application/json'}});
        if(!response.ok)throw new Error('Search temporarily unavailable');
        const data=await response.json();if(id!==requestId)return;
        const items=Array.isArray(data.items)?data.items:[];
        const catalogueKey=publicCatalogueKey(storeId,storeCode);try{await window.DenmartOffline?.mergeCatalogue(items.map(x=>({...x,price:Number(x.price||0)})),catalogueKey,12000)}catch(_e){}
        renderSuggestions(items);
        if(isShopForm){renderShopGrid(items);if(feedback)feedback.textContent=items.length?`${items.length} relevant match${items.length===1?'':'es'} for “${q}”`:`No matches for “${q}”. Try another name, brand or barcode.`;}
      }catch(error){if(error.name==='AbortError')return;if(id!==requestId)return;try{const cached=await window.DenmartOffline?.searchCatalogue(q,publicCatalogueKey(storeId,storeCode),80)||[];const filtered=categoryId?cached.filter(x=>String(x.category||'')===String(categoryId)):cached;if(filtered.length){renderSuggestions(filtered);if(isShopForm)renderShopGrid(filtered);if(feedback)feedback.textContent='Offline results from this device’s saved catalogue. Prices and availability must be confirmed online.';return;}}catch(_e){}hide();if(feedback)feedback.textContent='Search could not connect. Opened products and your basket remain saved on this device.';}
    };
    input.addEventListener('input',()=>{clearTimeout(timer);requestId++;if(controller)controller.abort();timer=setTimeout(search,110)});
    input.addEventListener('focus',()=>{if(input.value.trim().length>=2){clearTimeout(timer);timer=setTimeout(search,30)}});
    document.addEventListener('click',event=>{if(!form.contains(event.target))hide()});
    input.addEventListener('keydown',event=>{if(event.key==='Escape')hide();if(event.key==='ArrowDown'){const first=dropdown.querySelector('button');if(first){event.preventDefault();first.focus()}}});
  });

  // Keyboard-wedge scanners (USB/Bluetooth, 1D or 2D) type into ordinary inputs.
  // Prevent their common Enter suffix from accidentally submitting the whole form.
  document.querySelectorAll('input[name="barcode"]').forEach(input=>{
    input.setAttribute('autocomplete','off');input.setAttribute('spellcheck','false');
    input.addEventListener('keydown',event=>{
      if(event.key==='Enter'){event.preventDefault();input.classList.add('scanner-captured');input.dispatchEvent(new Event('change',{bubbles:true}));}
    });
    input.addEventListener('input',()=>{input.classList.remove('scanner-captured');input.dataset.lastBarcodeInput=String(Date.now())});
  });
  updateCounts();renderCartPage();cacheRenderedProducts();hydrateCart();if(!location.pathname.startsWith('/control')&&!location.pathname.startsWith('/merchant')&&'serviceWorker' in navigator)navigator.serviceWorker.register('/shop/sw.js',{scope:'/'}).catch(()=>{});
})();
function shareDenmartShop(){const data={title:'Denmart Online Shop',text:'Browse Denmart online',url:window.location.origin+'/shop'};if(navigator.share){navigator.share(data).catch(()=>{});return;}if(navigator.clipboard)navigator.clipboard.writeText(data.url).then(()=>alert('Denmart shop link copied.')).catch(()=>{});}
