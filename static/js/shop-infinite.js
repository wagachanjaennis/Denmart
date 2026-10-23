(function () {
  'use strict';
  const grid = document.getElementById('liveShopGrid') || document.getElementById('homeProductGrid');
  if (!grid || !('IntersectionObserver' in window)) return;
  const form = document.getElementById('shopLiveSearch');
  const params = new URLSearchParams(location.search);
  const storeCode = (form && form.dataset.storeCode) || grid.dataset.storeCode || params.get('store') || '';
  const query = (form && form.querySelector('[name="q"]')?.value) || params.get('q') || '';
  const category = (form && form.querySelector('[name="category"]')?.value) || params.get('category') || '';
  const initialCards = [...grid.querySelectorAll('.product-card')];
  const seen = new Set(initialCards.map((card) => String(card.dataset.productId || '')).filter(Boolean));
  let page = initialCards.length ? (query ? Math.floor(initialCards.length / 60) : 1) : 0;
  let loading = false;
  let ended = false;
  let loaded = initialCards.length;
  const sentinel = document.getElementById('homeShopLoadMore') || document.createElement('div');
  sentinel.id = 'shopLoadMore'; sentinel.className = 'shop-load-more'; sentinel.setAttribute('role', 'status'); sentinel.setAttribute('aria-live', 'polite');
  sentinel.textContent = 'Scroll to keep exploring the catalogue.';
  if (!sentinel.isConnected) grid.insertAdjacentElement('afterend', sentinel);

  function makeCard(product) {
    const card = document.createElement('article');
    card.className = 'product-card' + (product.image ? '' : ' no-product-photo');
    card.dataset.productId = product.id;
    card.dataset.productName = product.name || '';
    card.dataset.productPrice = String(product.price || 0);
    card.dataset.productSlug = product.slug || '';
    card.dataset.productBrand = product.brand || '';
    card.dataset.productCategory = product.category_id || '';
    card.dataset.productImage = product.image || '';
    card.dataset.productInStock = product.in_stock ? 'true' : 'false';
    card.dataset.categoryId = product.category_id || '';

    const href = product.url || '/shop';
    const imageLink = document.createElement('a'); imageLink.className = 'product-image product-image-clean'; imageLink.href = href;
    const imageLabel = document.createElement('span'); imageLabel.className = 'image-unavailable-label'; imageLabel.textContent = 'Product photo unavailable';
    if (product.image) {
      const img = document.createElement('img'); img.loading = 'lazy'; img.decoding = 'async'; img.src = product.image; img.alt = product.name || 'Product'; img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', () => { imageLink.classList.add('image-unavailable'); img.remove(); }, { once: true });
      imageLink.append(img, imageLabel);
    } else imageLink.appendChild(imageLabel);

    const info = document.createElement('div'); info.className = 'product-info';
    const brand = document.createElement('span'); brand.className = 'product-brand'; brand.textContent = product.brand || 'Household';
    const title = document.createElement('a'); title.className = 'product-title'; title.href = href; title.textContent = product.name || 'Product';
    info.append(brand, title);
    if (!product.in_stock) { const stock = document.createElement('span'); stock.className = 'product-stock-status'; stock.setAttribute('aria-label', 'Out of stock'); stock.textContent = 'Out of stock'; info.appendChild(stock); }
    const bottom = document.createElement('div'); bottom.className = 'product-bottom';
    const price = document.createElement('strong'); const n = Number(product.price || 0); price.textContent = 'KES ' + (Number.isFinite(n) ? Math.round(n).toLocaleString('en-KE') : '0');
    const add = document.createElement('button'); add.type = 'button'; add.textContent = product.in_stock ? 'Add' : 'Unavailable'; add.disabled = !product.in_stock;
    add.setAttribute('aria-label', product.in_stock ? 'Add to basket' : 'Out of stock');
    if (!product.in_stock) add.title = 'Currently out of stock';
    else add.addEventListener('click', () => {
      if (typeof window.addToCart === 'function') window.addToCart(String(product.id), String(product.name || 'Product'), Number(product.price || 0));
    });
    bottom.append(price, add); info.appendChild(bottom); card.append(imageLink, info);
    return card;
  }

  async function loadMore() {
    if (loading || ended) return;
    loading = true; sentinel.classList.add('loading'); sentinel.textContent = 'Loading more products…';
    try {
      const url = new URL('/shop/api/products', location.origin);
      url.searchParams.set('page', String(page + 1));
      if (query) url.searchParams.set('q', query);
      if (category) url.searchParams.set('category', category);
      if (storeCode) url.searchParams.set('store', storeCode);
      const response = await fetch(url.toString(), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('Products could not be loaded. Scroll to retry.');
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      let added = 0;
      items.forEach((item) => {
        const id = String(item.id || ''); if (!id || seen.has(id)) return;
        seen.add(id); grid.appendChild(makeCard(item)); added += 1; loaded += 1;
      });
      page += 1;
      ended = !data.has_more || !items.length || loaded >= Number(data.total || 0);
      if (ended) {
        sentinel.textContent = loaded ? 'You have reached the end of this catalogue.' : 'No products are available for this selection.';
        observer.disconnect();
      } else if (!added) {
        // A search can have fuzzy-ranked initial results. If the current server page only
        // repeats those results, keep advancing until unique rows are found or exhausted.
        sentinel.textContent = 'Finding more items…';
        if (page < Math.ceil(Number(data.total || 0) / 60) + 2) queueMicrotask(loadMore);
        else { ended = true; sentinel.textContent = 'You have reached the end of this catalogue.'; observer.disconnect(); }
      } else sentinel.textContent = 'Scroll to keep exploring the catalogue.';
      const count = document.getElementById('homeProductCount');
      if (count && !category && !query) count.textContent = loaded.toLocaleString('en-KE') + ' products loaded';
    } catch (error) {
      sentinel.textContent = error.message || 'Could not load more products. Scroll to retry.';
      sentinel.classList.add('load-error');
    } finally { loading = false; sentinel.classList.remove('loading'); }
  }
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadMore();
  }, { rootMargin: '900px 0px', threshold: 0 });
  observer.observe(sentinel);
  sentinel.addEventListener('click', () => { if (!loading && !ended) loadMore(); });
  if (!initialCards.length) loadMore();
})();
