const SHELL_CACHE='real-mart-public-v6';
const IMAGE_CACHE='real-mart-catalogue-images-v2';
self.addEventListener('install',e=>{e.waitUntil(caches.open(SHELL_CACHE));self.skipWaiting()});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=='GET'||u.origin!==location.origin)return;
  if(u.pathname.startsWith('/otcOmc')||u.pathname.startsWith('/fr%2')||u.pathname.startsWith('/admin')||u.pathname.startsWith('/api'))return;
  if(u.pathname.startsWith('/static/catalogue/products/')){
    e.respondWith((async()=>{
      const cache=await caches.open(IMAGE_CACHE);
      const hit=await cache.match(e.request);
      if(hit)return hit;
      try{
        const response=await fetch(e.request);
        if(response.ok) cache.put(e.request,response.clone());
        return response;
      }catch(err){
        const fallback=await cache.match(e.request);
        return fallback||new Response('',{status:504});
      }
    })());
    return;
  }
  e.respondWith(fetch(e.request).catch(()=>new Response('Shopping site unavailable offline',{status:503})));
});
