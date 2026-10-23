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
  function drawBrandMotion(t){const p=palette();ctx.save();ctx.globalAlpha=.22;for(let i=0;i<8;i++){const r=100+i*38;ctx.beginPath();ctx.arc(1410,460,r,0,Math.PI*2);ctx.strokeStyle=i%2?p.accent:p.accent2;ctx.lineWidth=2+(i%3);ctx.stroke();}ctx.globalAlpha=.3;ctx.fillStyle=p.accent;for(let i=0;i<18;i++){const x=1180+((i*103+t*28)%(570));const y=210+((i*71+Math.sin(t+i)*34)%510);ctx.beginPath();ctx.arc(x,y,3+(i%4),0,Math.PI*2);ctx.fill();}ctx.restore();}
  function drawCanvasDesign(slide,t,progress,localT){
    const design=slide.design||{};const bg1=design.background||'#10243a';const bg2=design.background2||'#45264f';
    if(campaign.media_asset_id&&typeof video!=='undefined'&&video&&video.readyState>=2){
      ctx.drawImage(video,0,0,W,H);
      const tint=Math.max(0,Math.min(.75,Number(design.video_tint_opacity)||0));
      if(tint>0){ctx.save();ctx.globalAlpha=tint;ctx.fillStyle=design.video_tint||bg1;ctx.fillRect(0,0,W,H);ctx.restore();}
    }else{
      if(design.gradient!==false){const g=ctx.createLinearGradient(0,0,W,H);g.addColorStop(0,bg1);g.addColorStop(1,bg2);ctx.fillStyle=g;}else{ctx.fillStyle=bg1;}
      ctx.fillRect(0,0,W,H);
    }
    const ease=v=>{v=Math.max(0,Math.min(1,v));return 1-Math.pow(1-v,3);};
    const rounded=(x,y,w,h,r)=>{rr(ctx,x,y,w,h,Math.max(0,Math.min(r,Math.min(w,h)/2)));};
    function wrap(text,maxWidth,font){ctx.font=font;const lines=[];for(const para of String(text||'').split('\n')){let line='';for(const word of para.split(/\s+/)){const candidate=line?line+' '+word:word;if(line&&ctx.measureText(candidate).width>maxWidth){lines.push(line);line=word;}else line=candidate;}lines.push(line);}return lines;}
    function drawOne(el,alphaOverride,offsetY,scaleOverride,rotationOverride,clipProgress){
      const x=Number(el.x)||0,y=(Number(el.y)||0)+(offsetY||0),w=Math.max(8,Number(el.w)||300),h=Math.max(8,Number(el.h)||100);
      const type=el.type||'text';ctx.save();ctx.globalAlpha=Math.max(0,Math.min(1,(Number(el.opacity??1))*alphaOverride));
      if(clipProgress!==undefined){ctx.beginPath();ctx.rect(x,y,w,h*Math.max(0,Math.min(1,clipProgress)));ctx.clip();}
      const angle=((Number(el.rotation)||0)+(rotationOverride||0))*Math.PI/180;const scale=scaleOverride===undefined?1:scaleOverride;
      ctx.translate(x+w/2,y+h/2);ctx.rotate(angle);ctx.scale(scale,scale);ctx.translate(-w/2,-h/2);
      if(el.shadow){ctx.shadowColor='rgba(0,0,0,.45)';ctx.shadowBlur=28;ctx.shadowOffsetY=10;}
      if(type==='rect'||type==='badge'||type==='circle'||type==='line'){
        ctx.fillStyle=el.fill||'#e63854';ctx.strokeStyle=el.stroke||'#ffffff';ctx.lineWidth=Math.max(0,Number(el.stroke_width)||0);
        if(type==='circle'){ctx.beginPath();ctx.ellipse(w/2,h/2,w/2,h/2,0,0,Math.PI*2);ctx.fill();if(ctx.lineWidth)ctx.stroke();}
        else if(type==='line'){ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.strokeStyle=el.fill||el.stroke||'#ffffff';ctx.lineWidth=Math.max(2,Number(el.stroke_width)||8);ctx.stroke();}
        else {rounded(0,0,w,h,Number(el.radius)||20);ctx.fill();if(ctx.lineWidth)ctx.stroke();}
      }
      if(type==='image'||type==='qr'){
        const img=type==='qr'?qrImage:getImage(String(el.image_url||''));
        if(img&&img.complete&&img.naturalWidth){if(type==='qr'){ctx.fillStyle='#fff';ctx.fillRect(-4,-4,w+8,h+8);}const fit=el.fit||'contain';if(fit==='stretch')ctx.drawImage(img,0,0,w,h);else{const sc=fit==='cover'?Math.max(w/img.naturalWidth,h/img.naturalHeight):Math.min(w/img.naturalWidth,h/img.naturalHeight);const iw=img.naturalWidth*sc,ih=img.naturalHeight*sc;ctx.drawImage(img,(w-iw)/2,(h-ih)/2,iw,ih);}}
      }
      if(type==='text'||type==='number'||type==='sticker'||type==='badge'){
        let text=String(el.text||(type==='number'?'01':type==='sticker'?'✦':''));const effect=String(el.effect||'fade');
        if(effect==='typewriter')text=text.slice(0,Math.max(1,Math.floor(text.length*Math.max(0,Math.min(1,progress)))));
        const size=Math.max(12,Number(el.font_size)||56);const weight=Number(el.weight)||700;const font=`${weight} ${size}px ${el.font_family||'Inter, system-ui, sans-serif'}`;ctx.font=font;ctx.textBaseline='top';ctx.textAlign=el.align||'left';
        ctx.fillStyle=el.color||'#ffffff';ctx.strokeStyle=el.stroke||'#10243a';ctx.lineWidth=Math.max(0,Number(el.stroke_width)||0);ctx.lineJoin='round';
        const lines=wrap(text,w-12,font);const lineHeight=size*1.14;let ty=type==='badge'?Math.max(0,(h-lines.length*lineHeight)/2):4;
        for(const line of lines){if(ty+lineHeight>h+lineHeight*.2)break;let tx=el.align==='center'?w/2:el.align==='right'?w-6:6;if(ctx.lineWidth)ctx.strokeText(line,tx,ty,w);ctx.fillText(line,tx,ty,w);ty+=lineHeight;}
      }
      ctx.restore();
    }
    const elements=Array.isArray(design.elements)?design.elements:[];
    for(const el of elements){
      if(!el||typeof el!=='object')continue;
      const delay=Math.max(0,Number(el.delay)||0),duration=Math.max(.2,Number(el.motion_duration)||1.2);let a=localT-delay;
      if(a<0)continue;let p=Math.max(0,Math.min(1,a/duration));const k=ease(p);let alpha=1,oy=0,scale=1,rot=0,clip;
      switch(String(el.effect||'fade')){
        case 'fade':alpha=k;break;case 'slide-left':oy=0;break;
        case 'slide-right':break;case 'rise':oy=80*(1-k);break;
        case 'zoom':scale=.5+.5*k;break;case 'bounce':scale=.72+.28*(p<1?Math.abs(Math.sin(p*Math.PI*2.5))*(1-p)+p:1);break;
        case 'melt':clip=Math.min(1,Math.max(0,(a/duration)*1.15));oy=(1-k)*18;alpha=Math.min(1,k*1.3);break;
        case 'float':oy=-8*Math.sin(localT*2.4);break;case 'rotate':rot=-18*(1-k);break;
        case 'typewriter':alpha=1;break;case 'wipe':clip=k;alpha=k;break;case 'blur':alpha=k;break;case 'pulse':alpha=k;scale=(.96+.04*Math.sin(localT*3.2));break;case 'shake':alpha=k;rot=(1-k)*0+Math.sin(localT*24)*2.2*(1-k);break;case 'flip':alpha=k;scale=.04+.96*k;rot=(1-k)*65;break;case 'pop':alpha=k;scale=p<1?.5+.5*Math.sin(k*Math.PI/2):1;break;case 'drop':alpha=k;oy=-110*(1-k);rot=-5*(1-k);break;case 'glow':alpha=k;break;default:break;
      }
      if(String(el.effect)==='slide-left'){ctx.save();ctx.translate(-(1-k)*Math.min(220,(Number(el.w)||300)*.6),0);drawOne(el,alpha,oy,scale,rot,clip);ctx.restore();}
      else if(String(el.effect)==='slide-right'){ctx.save();ctx.translate((1-k)*Math.min(220,(Number(el.w)||300)*.6),0);drawOne(el,alpha,oy,scale,rot,clip);ctx.restore();}
      else if(String(el.effect)==='blur'){ctx.save();try{ctx.filter='blur('+Math.max(0,(1-k)*15)+'px)';drawOne(el,alpha,oy,scale,rot,clip);}finally{ctx.restore();}}
      else if(String(el.effect)==='glow'){ctx.save();ctx.shadowColor=el.color||el.fill||'#ffffff';ctx.shadowBlur=30+12*Math.sin(localT*5);drawOne(el,alpha,oy,scale,rot,clip);ctx.restore();}
      else drawOne(el,alpha,oy,scale,rot,clip);
    }
  }
  function drawScene(slide,index,t,progress,localT){const p=palette();if(slide&&slide.design&&slide.design.enabled){drawCanvasDesign(slide,t,progress,Number.isFinite(localT)?localT:Math.max(0,Number(progress)||0)*Math.max(3,Number(slide.duration)||6));return;}if(campaign.media_asset_id){if(typeof video!=='undefined'&&video&&video.readyState>=2){ctx.drawImage(video,0,0,W,H);}else{ctx.fillStyle='#080b10';ctx.fillRect(0,0,W,H);}return;}drawBackground(t);drawBrand(t);const headline=String(slide.headline||'Your everyday essentials');const body=String(slide.body||'');const cta=String(slide.cta||'SHOP ONLINE');const gallery=(Array.isArray(slide.image_urls)?slide.image_urls:[]).filter(Boolean);if(slide.image_url&&!gallery.includes(slide.image_url))gallery.unshift(slide.image_url);const photoIndex=gallery.length?Math.floor(t/2.2)%gallery.length:0;const imageUrl=String(gallery[photoIndex]||'');
    const fade=Math.min(1,progress*4+0.06);ctx.save();ctx.globalAlpha=fade;ctx.translate(0,(1-fade)*25);
    ctx.fillStyle=p.accent;ctx.font='800 17px Inter,system-ui,sans-serif';ctx.textBaseline='top';ctx.fillText(String(campaign.name||'DENMART').toUpperCase(),101,179);
    const titleSize=headline.length>32?65:headline.length>23?76:88;
    const titleHeight=drawLines(headline,98,238,870,titleSize,900,'#ffffff',3,titleSize*1.06);
    drawLines(body,104,250+titleHeight,820,31,500,'#eaf8ef',4,43);
    const ctaY=Math.min(770,330+titleHeight+Math.min(170,fitText(body,820,31,500).length*43));
    rr(ctx,101,ctaY,Math.min(650,Math.max(360,ctx.measureText(cta).width+115)),76,38);const button=ctx.createLinearGradient(101,ctaY,760,ctaY+76);button.addColorStop(0,p.accent);button.addColorStop(1,p.accent2);ctx.fillStyle=button;ctx.fill();ctx.fillStyle='#09291d';ctx.font='900 22px Inter,system-ui,sans-serif';ctx.fillText(cta,134,ctaY+29);
    const photo=getImage(imageUrl);if(photo&&photo.complete&&photo.naturalWidth){ctx.save();ctx.shadowColor='#0007';ctx.shadowBlur=50;ctx.shadowOffsetY=22;rr(ctx,1120,180,560,535,34);ctx.fillStyle='#f5fbf7';ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;ctx.save();rr(ctx,1133,193,534,509,25);ctx.clip();const scale=Math.min(500/photo.naturalWidth,475/photo.naturalHeight);const iw=photo.naturalWidth*scale,ih=photo.naturalHeight*scale;ctx.drawImage(photo,1400-iw/2,447-ih/2,iw,ih);ctx.restore();ctx.restore();}else{drawBrandMotion(t);} 
    const showQR=slide.show_qr!==undefined?slide.show_qr:campaign.show_qr;if(showQR){ctx.save();ctx.shadowColor='#0007';ctx.shadowBlur=24;rr(ctx,1590,725,192,238,22);ctx.fillStyle='#fff';ctx.fill();ctx.shadowBlur=0;if(qrImage.complete&&qrImage.naturalWidth){ctx.imageSmoothingEnabled=false;ctx.drawImage(qrImage,1607,742,158,158);ctx.imageSmoothingEnabled=true;}ctx.fillStyle='#123429';ctx.font='900 14px Inter,system-ui,sans-serif';ctx.textAlign='center';ctx.fillText('SCAN TO SHOP',1686,927);ctx.restore();}
    ctx.restore();
    // moving light accent gives the screen the feel of a produced retail spot
    ctx.save();ctx.globalAlpha=.10;ctx.fillStyle=p.accent;const sx=(t*130)%2400-280;ctx.transform(1,0,-.16,1,0,0);ctx.fillRect(sx,-120,88,1200);ctx.restore();
    // ticker rail
    ctx.fillStyle='#02100d';ctx.globalAlpha=.88;ctx.fillRect(0,1002,W,78);ctx.globalAlpha=1;ctx.fillStyle=p.accent;ctx.fillRect(0,1002,W,3);ctx.save();ctx.beginPath();ctx.rect(0,1005,W,72);ctx.clip();const ticker=String(campaign.ticker||'DENMART.CO.KE  •  YOUR EVERYDAY ESSENTIALS').toUpperCase();ctx.font='800 21px Inter,system-ui,sans-serif';const tw=ctx.measureText(ticker+'     ✦     ').width;const off=(t*90)%(tw||1);for(let x=-tw-off;x<W+tw;x+=tw){ctx.fillStyle=p.accent;ctx.fillText('✦',x+3,1049);ctx.fillStyle='#f3fff7';ctx.fillText(ticker,x+38,1049);}ctx.restore();
    ctx.fillStyle='#ffffff75';ctx.font='600 13px Inter,system-ui,sans-serif';ctx.fillText('DENMART  ·  ' + (campaign.website||'denmart.co.ke'),99,970);
    ctx.fillStyle=p.accent;ctx.font='700 15px Inter,system-ui,sans-serif';ctx.textAlign='right';ctx.fillText(String(index+1).padStart(2,'0')+' / '+String((campaign.slides||[]).length).padStart(2,'0'),1812,969);ctx.textAlign='left';
    if(campaign.darken_screen){ctx.fillStyle='rgba(0,0,0,'+Math.max(.15,Math.min(.85,Number(campaign.overlay_opacity||.52)))+')';ctx.fillRect(0,0,W,H);}
    if(campaign.flow_text_enabled&&String(campaign.flow_text||'').trim()){ctx.save();ctx.font='900 36px Inter,system-ui,sans-serif';ctx.textBaseline='middle';const flow=String(campaign.flow_text).toUpperCase()+'     ✦     ';const fw=ctx.measureText(flow).width;ctx.fillStyle='rgba(0,0,0,.7)';ctx.fillRect(0,825,W,92);ctx.fillStyle='#fff';const ox=(t*150)%(fw||1);for(let x=-fw-ox;x<W+fw;x+=fw)ctx.fillText(flow,x,871);ctx.restore();}
  }
  function sceneAt(elapsed){const slides=Array.isArray(campaign.slides)&&campaign.slides.length?campaign.slides:[{headline:'WELCOME TO DENMART ONLINE',body:'Everyday essentials. A simpler way to shop.',cta:'VISIT DENMART.CO.KE',show_qr:true,duration:6}];let cursor=0;for(let i=0;i<slides.length;i++){const d=Math.max(3,Math.min(15,Number(slides[i].duration||campaign.duration||6)));if(elapsed<cursor+d)return {slide:slides[i],index:i,progress:(elapsed-cursor)/d,slideElapsed:elapsed-cursor,duration:d,total:slides.reduce((n,s)=>n+Math.max(3,Math.min(15,Number(s.duration||campaign.duration||6))),0)};cursor+=d;}return sceneAt(elapsed%Math.max(1,cursor));}
  let started=performance.now();let running=true;let activeMediaId='';let editorSceneIndex=null;let editorSceneStarted=performance.now();
  const video=document.getElementById('adUploadedVideo');const overlay=document.getElementById('adVideoOverlay');const flowNode=document.getElementById('adVideoFlow');
  function syncUploadedMedia(){if(!video)return;const id=String(campaign.media_asset_id||'');if(id){const src='/advertisement/media/'+encodeURIComponent(id);if(activeMediaId!==id||video.dataset.mediaSrc!==src){activeMediaId=id;video.dataset.mediaSrc=src;video.src=src;try{video.load();const play=video.play();if(play&&play.catch)play.catch(()=>{});}catch(_){}}const layered=(campaign.slides||[]).some(s=>s&&s.design&&s.design.enabled);video.hidden=false;video.style.visibility=layered?'hidden':'visible';if(canvas)canvas.style.visibility=layered?'visible':'hidden';if(overlay){overlay.hidden=layered;overlay.classList.toggle('darken',!!campaign.darken_screen);overlay.style.setProperty('--ad-dim',String(Math.max(.15,Math.min(.85,Number(campaign.overlay_opacity||.52)))));const flow=String(campaign.flow_text||'').trim();flowNode.textContent=flow.toUpperCase();overlay.classList.toggle('flowing',!!(campaign.flow_text_enabled&&flow));flowNode.style.display=campaign.flow_text_enabled&&flow?'block':'none';}}else{if(activeMediaId){activeMediaId='';video.pause();video.removeAttribute('src');video.load();}video.hidden=true;video.style.visibility='visible';if(canvas)canvas.style.visibility='visible';if(overlay)overlay.hidden=true;}}
  function frame(now){if(!running)return;syncUploadedMedia();const elapsed=(now-started)/1000;const scene=sceneAt(elapsed);const hasDesign=(campaign.slides||[]).some(s=>s&&s.design&&s.design.enabled);if(!campaign.media_asset_id||hasDesign){if(editorSceneIndex!==null){const slide=campaign.slides?.[editorSceneIndex]||campaign.slides?.[0];const d=Math.max(3,Number(slide?.duration||6));const local=(now-editorSceneStarted)/1000;drawScene(slide,editorSceneIndex,local,Math.min(1,local/d),local);}else drawScene(scene.slide,scene.index,elapsed,scene.progress,scene.slideElapsed);}requestAnimationFrame(frame);}
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(()=>requestAnimationFrame(frame));else requestAnimationFrame(frame);
  // Click or tap to ask the browser for kiosk fullscreen without adding player controls.
  if(document.body.classList.contains('ad-screen-body'))document.querySelector('.ad-screen')?.addEventListener('click',()=>{if(!document.fullscreenElement)document.documentElement.requestFullscreen?.().catch(()=>{});});
  async function refreshScheduledCampaign(){try{const r=await fetch('/advertisement/current.json',{cache:'no-store'});if(!r.ok)return;const data=await r.json();if(data.campaign&&data.campaign.id&&(data.campaign.id!==campaign.id||data.campaign.updated_at!==campaign.updated_at)){campaign=data.campaign;started=performance.now();const node=document.getElementById('adCampaign');if(node)node.textContent=JSON.stringify(campaign);}}catch(_){}}
  if(document.body.classList.contains('ad-screen-body'))setInterval(refreshScheduledCampaign,45000);
  // Keep a reference for the in-studio renderer/exporter; nothing is exposed on the public screen.
  window.DenmartAdPlayer={setCampaign(value,preserveTime=false){campaign=value||{};if(!preserveTime){started=performance.now();if(editorSceneIndex!==null)editorSceneStarted=performance.now();}syncUploadedMedia();},setEditorScene(index,enabled=true,preserveTime=false){editorSceneIndex=enabled?Math.max(0,Number(index)||0):null;if(!preserveTime)editorSceneStarted=performance.now();},render(value,time){campaign=value||campaign;syncUploadedMedia();const scene=sceneAt(time||0);if(!campaign.media_asset_id||(campaign.slides||[]).some(s=>s&&s.design&&s.design.enabled))drawScene(scene.slide,scene.index,time||0,scene.progress,scene.slideElapsed);},drawScene,sceneAt,canvas,palettes};
})();
