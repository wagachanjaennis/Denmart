(function(){
  'use strict';
  const canvas=document.getElementById('adCanvas');
  if(!canvas||!canvas.getContext)return;
  const ctx=canvas.getContext('2d');
  let campaign={};
  try{campaign=JSON.parse(document.getElementById('adCampaign')?.textContent||'{}');}catch(_){campaign={};}
  const W=1920,H=1080;
  const imageCache=new Map();
  const qrImage=new Image();qrImage.src='/advertisement/qr.png';
  const palettes={
    emerald:{bg1:'#041b15',bg2:'#0a5b3d',accent:'#a4f4c0',accent2:'#d5ff72',warm:'#ffce88'},
    midnight:{bg1:'#050b25',bg2:'#20376b',accent:'#9ee7ff',accent2:'#d5c3ff',warm:'#ffda9e'},
    sunrise:{bg1:'#3a1124',bg2:'#b9472a',accent:'#ffe1a7',accent2:'#ffb5a8',warm:'#fff2d0'},
    christmas:{bg1:'#071e1a',bg2:'#851e32',accent:'#e9ffd1',accent2:'#d7f5bf',warm:'#ffe0a1'},
    school:{bg1:'#091a32',bg2:'#155a88',accent:'#f4d35e',accent2:'#a8e6ff',warm:'#ffd8a4'},
    ocean:{bg1:'#04192a',bg2:'#086f88',accent:'#a8f2e8',accent2:'#b9ddff',warm:'#fff2b0'},
    plum:{bg1:'#1b0c2d',bg2:'#6c3385',accent:'#f2cdfb',accent2:'#e9ffba',warm:'#ffe0aa'}
  };
  const palette=()=>palettes[campaign.theme]||palettes.emerald;
  function getImage(src){if(!src)return null;if(imageCache.has(src))return imageCache.get(src);const img=new Image();if(/^https?:/i.test(src))img.crossOrigin='anonymous';img.onload=()=>imageCache.set(src,img);img.onerror=()=>imageCache.set(src,null);img.src=src;imageCache.set(src,img);return img;}
  function rr(c,x,y,w,h,r){c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x+w,y,r);c.arcTo(x,y,x+w,y,r);c.closePath();}
  function fitText(text,maxWidth,fontSize,weight){const words=String(text||'').split(/\s+/);const lines=[];let line='';ctx.font=`${weight||700} ${fontSize}px Inter, system-ui, sans-serif`;for(const word of words){const test=line?line+' '+word:word;if(ctx.measureText(test).width>maxWidth&&line){lines.push(line);line=word;}else line=test;}if(line)lines.push(line);return lines;}
  function drawLines(text,x,y,maxWidth,fontSize,weight,color,maxLines,lineGap){const p=palette();ctx.fillStyle=color||'#fff';const lines=fitText(text,maxWidth,fontSize,weight).slice(0,maxLines||4);ctx.font=`${weight||700} ${fontSize}px Inter, system-ui, sans-serif`;ctx.textBaseline='top';lines.forEach((line,i)=>ctx.fillText(line,x,y+i*(lineGap||fontSize*1.18)));return lines.length*(lineGap||fontSize*1.18);}
  function drawBackground(t){const p=palette();const g=ctx.createLinearGradient(80+Math.sin(t*.22)*460,0,W, H);g.addColorStop(0,p.bg1);g.addColorStop(.56,p.bg2);g.addColorStop(1,'#06120f');ctx.fillStyle=g;ctx.fillRect(0,0,W,H);const orb=(x,y,r,color,a)=>{ctx.globalAlpha=a;const grad=ctx.createRadialGradient(x,y,0,x,y,r);grad.addColorStop(0,color);grad.addColorStop(1,'transparent');ctx.fillStyle=grad;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;};orb(1400+Math.sin(t*.24)*120,230,560,p.accent,.13);orb(320,900+Math.cos(t*.19)*60,420,p.accent2,.10);ctx.save();ctx.globalAlpha=.12;ctx.strokeStyle='#fff';ctx.lineWidth=1;for(let i=0;i<14;i++){const x=(i*170+(t*15)%170)-100;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x+250,H);ctx.stroke();}ctx.restore();for(let i=0;i<36;i++){const x=(i*239+(t*20*(i%3+1)))%(W+40)-20;const y=(i*137+Math.sin(t*.55+i)*35)%(H+30);ctx.globalAlpha=.11+((i%4)*.035);ctx.fillStyle=i%3===0?p.warm:p.accent;ctx.beginPath();ctx.arc(x,y,2+(i%4),0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;}
  function drawBrand(t){const p=palette();ctx.save();ctx.globalAlpha=.88;rr(ctx,84,62,66,66,20);ctx.fillStyle=p.accent;ctx.fill();ctx.fillStyle='#062116';ctx.font='900 32px Inter,system-ui,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('D',117,94);ctx.textAlign='left';ctx.textBaseline='alphabetic';ctx.fillStyle='#fff';ctx.font='800 31px Inter,system-ui,sans-serif';ctx.fillText('DENMART',171,91);ctx.globalAlpha=.68;ctx.font='500 15px Inter,system-ui,sans-serif';ctx.fillText('EVERYDAY ESSENTIALS',173,118);ctx.restore();ctx.fillStyle=p.accent;rr(ctx,84,153,10,72,5);ctx.fill();}
  function drawDecorativeProducts(t,slide){const p=palette();const cx=1435,cy=475;ctx.save();ctx.translate(cx,cy);ctx.rotate(Math.sin(t*.4)*.025);ctx.globalAlpha=.9;ctx.shadowColor='#0008';ctx.shadowBlur=55;ctx.shadowOffsetY=28;rr(ctx,-220,-260,440,535,45);const card=ctx.createLinearGradient(-220,-260,220,275);card.addColorStop(0,'#ffffff');card.addColorStop(1,'#e8f6ed');ctx.fillStyle=card;ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;const objects=[{x:-155,y:-130,w:105,h:220,c:'#2e9961',label:'FRESH'},{x:-31,y:-165,w:112,h:255,c:'#f7c74e',label:'HOME'},{x:91,y:30,w:96,h:190,c:'#f09b79',label:'CARE'}];objects.forEach((o,i)=>{const yy=o.y+Math.sin(t*1.2+i)*8;rr(ctx,o.x,yy,o.w,o.h,18);ctx.fillStyle=o.c;ctx.fill();ctx.fillStyle='#fff';rr(ctx,o.x+10,yy+o.h*.32,o.w-20,o.h*.34,8);ctx.fill();ctx.fillStyle='#183329';ctx.font='900 12px Inter,system-ui,sans-serif';ctx.textAlign='center';ctx.fillText(o.label,o.x+o.w/2,yy+o.h*.52);});ctx.fillStyle='#0b3a27';ctx.font='900 22px Inter,system-ui,sans-serif';ctx.textAlign='center';ctx.fillText('YOUR EVERYDAY STORE',0,232);ctx.restore();}
  function drawScene(slide,index,t,progress){const p=palette();drawBackground(t);drawBrand(t);const headline=String(slide.headline||'Your everyday essentials');const body=String(slide.body||'');const cta=String(slide.cta||'SHOP ONLINE');const imageUrl=String(slide.image_url||'');
    const fade=Math.min(1,progress*4+0.06);ctx.save();ctx.globalAlpha=fade;ctx.translate(0,(1-fade)*25);
    ctx.fillStyle=p.accent;ctx.font='800 17px Inter,system-ui,sans-serif';ctx.textBaseline='top';ctx.fillText(String(campaign.name||'DENMART').toUpperCase(),101,179);
    const titleSize=headline.length>32?65:headline.length>23?76:88;
    const titleHeight=drawLines(headline,98,238,870,titleSize,900,'#ffffff',3,titleSize*1.06);
    drawLines(body,104,250+titleHeight,820,31,500,'#eaf8ef',4,43);
    const ctaY=Math.min(770,330+titleHeight+Math.min(170,fitText(body,820,31,500).length*43));
    rr(ctx,101,ctaY,Math.min(650,Math.max(360,ctx.measureText(cta).width+115)),76,38);const button=ctx.createLinearGradient(101,ctaY,760,ctaY+76);button.addColorStop(0,p.accent);button.addColorStop(1,p.accent2);ctx.fillStyle=button;ctx.fill();ctx.fillStyle='#09291d';ctx.font='900 22px Inter,system-ui,sans-serif';ctx.fillText(cta,134,ctaY+29);
    const photo=getImage(imageUrl);if(photo&&photo.complete&&photo.naturalWidth){ctx.save();ctx.shadowColor='#0007';ctx.shadowBlur=50;ctx.shadowOffsetY=22;rr(ctx,1120,180,560,535,34);ctx.fillStyle='#f5fbf7';ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;ctx.save();rr(ctx,1133,193,534,509,25);ctx.clip();const scale=Math.max(534/photo.naturalWidth,509/photo.naturalHeight);const iw=photo.naturalWidth*scale,ih=photo.naturalHeight*scale;ctx.drawImage(photo,1133+(534-iw)/2,193+(509-ih)/2,iw,ih);ctx.restore();ctx.restore();}else{drawDecorativeProducts(t,slide);}
    const showQR=slide.show_qr!==undefined?slide.show_qr:campaign.show_qr;if(showQR){ctx.save();ctx.shadowColor='#0007';ctx.shadowBlur=24;rr(ctx,1590,725,192,238,22);ctx.fillStyle='#fff';ctx.fill();ctx.shadowBlur=0;if(qrImage.complete&&qrImage.naturalWidth){ctx.imageSmoothingEnabled=false;ctx.drawImage(qrImage,1607,742,158,158);ctx.imageSmoothingEnabled=true;}ctx.fillStyle='#123429';ctx.font='900 14px Inter,system-ui,sans-serif';ctx.textAlign='center';ctx.fillText('SCAN TO SHOP',1686,927);ctx.restore();}
    ctx.restore();
    // moving light accent gives the screen the feel of a produced retail spot
    ctx.save();ctx.globalAlpha=.10;ctx.fillStyle=p.accent;const sx=(t*130)%2400-280;ctx.transform(1,0,-.16,1,0,0);ctx.fillRect(sx,-120,88,1200);ctx.restore();
    // ticker rail
    ctx.fillStyle='#02100d';ctx.globalAlpha=.88;ctx.fillRect(0,1002,W,78);ctx.globalAlpha=1;ctx.fillStyle=p.accent;ctx.fillRect(0,1002,W,3);ctx.save();ctx.beginPath();ctx.rect(0,1005,W,72);ctx.clip();const ticker=String(campaign.ticker||'DENMART.CO.KE  •  YOUR EVERYDAY ESSENTIALS').toUpperCase();ctx.font='800 21px Inter,system-ui,sans-serif';const tw=ctx.measureText(ticker+'     ✦     ').width;const off=(t*90)%(tw||1);for(let x=-tw-off;x<W+tw;x+=tw){ctx.fillStyle=p.accent;ctx.fillText('✦',x+3,1049);ctx.fillStyle='#f3fff7';ctx.fillText(ticker,x+38,1049);}ctx.restore();
    ctx.fillStyle='#ffffff75';ctx.font='600 13px Inter,system-ui,sans-serif';ctx.fillText('DENMART  ·  ' + (campaign.website||'denmart.co.ke'),99,970);
    ctx.fillStyle=p.accent;ctx.font='700 15px Inter,system-ui,sans-serif';ctx.textAlign='right';ctx.fillText(String(index+1).padStart(2,'0')+' / '+String((campaign.slides||[]).length).padStart(2,'0'),1812,969);ctx.textAlign='left';
  }
  function sceneAt(elapsed){const slides=Array.isArray(campaign.slides)&&campaign.slides.length?campaign.slides:[{headline:'WELCOME TO DENMART ONLINE',body:'Everyday essentials. A simpler way to shop.',cta:'VISIT DENMART.CO.KE',show_qr:true,duration:6}];let cursor=0;for(let i=0;i<slides.length;i++){const d=Math.max(3,Math.min(15,Number(slides[i].duration||campaign.duration||6)));if(elapsed<cursor+d)return {slide:slides[i],index:i,progress:(elapsed-cursor)/d,slideElapsed:elapsed-cursor,duration:d,total:slides.reduce((n,s)=>n+Math.max(3,Math.min(15,Number(s.duration||campaign.duration||6))),0)};cursor+=d;}return sceneAt(elapsed%Math.max(1,cursor));}
  let started=performance.now();let running=true;
  function frame(now){if(!running)return;const elapsed=(now-started)/1000;const scene=sceneAt(elapsed);drawScene(scene.slide,scene.index,elapsed,scene.progress);requestAnimationFrame(frame);}
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(()=>requestAnimationFrame(frame));else requestAnimationFrame(frame);
  // Click or tap to ask the browser for kiosk fullscreen without adding player controls.
  if(document.body.classList.contains('ad-screen-body'))document.querySelector('.ad-screen')?.addEventListener('click',()=>{if(!document.fullscreenElement)document.documentElement.requestFullscreen?.().catch(()=>{});});
  async function refreshScheduledCampaign(){try{const r=await fetch('/advertisement/current.json',{cache:'no-store'});if(!r.ok)return;const data=await r.json();if(data.campaign&&data.campaign.id&&(data.campaign.id!==campaign.id||data.campaign.updated_at!==campaign.updated_at)){campaign=data.campaign;started=performance.now();const node=document.getElementById('adCampaign');if(node)node.textContent=JSON.stringify(campaign);}}catch(_){}}
  if(document.body.classList.contains('ad-screen-body'))setInterval(refreshScheduledCampaign,45000);
  // Keep a reference for the in-studio renderer/exporter; nothing is exposed on the public screen.
  window.DenmartAdPlayer={setCampaign(value){campaign=value||{};started=performance.now();},render(value,time){campaign=value||campaign;const scene=sceneAt(time||0);drawScene(scene.slide,scene.index,time||0,scene.progress);},drawScene,sceneAt,canvas,palettes};
})();
