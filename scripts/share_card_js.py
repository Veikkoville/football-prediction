# -*- coding: utf-8 -*-
"""Jakokortti (share as image) staattisille goaliq.app-sivuille.

TAUSTA: SPA:ssa (web/pro-spa/src/lib/shareCard.ts) on ollut 31.7. alkaen
"share as image" -kortti, joka on layoutiltaan 1:1 goaliq-appin
outputs/gen_fpl_xp_list.py:n kanssa -- eli viikkopostaus, tuote ja sivusto
kertovat saman tarinan samassa muodossa. Ilmaisilta sivuilta se puuttui,
vaikka juuri ne ovat se pinta jonne X-liikenne laskeutuu.

TAMA MODUULI on sama kortti vanilla-JS:na, jotta staattiset sivut eivat
tarvitse SPA:n build-ketjua. Mitat, varit, fontit ja rivilayout on kopioitu
shareCard.ts:n renderCard():sta SELLAISENAAN -- jos niita muuttaa, molemmat
on muutettava, muuten syntyy kolmas erinakoinen kortti.

MUUTTUJAT (korvataan kutsujassa):
  __CARD_ROWS_FN__  JS-funktio joka palauttaa {title,subtitle,nameLabel,
                    midLabel,valueLabel,rows,fileName}
"""

# Huom: tama on JS-lahdekoodia Python-merkkijonossa. Aaltosulkeita EI saa
# tuplata, koska merkkijonoa ei formatoida f-stringilla vaan replacella.
SHARE_CARD_JS = r"""
<script>
(function(){
 // --- Dimensions and palette: 1:1 with shareCard.ts (do not change one-sidedly)
 var W=1080,MX=60,ROW_TOP=404,ROW_H=80,FOOT_H=146;
 var INK='#0b0a09',INK2='#141311',AMBER='#f5c542',CREAM='#f3f2f2',
     MUTED='#a8a29a',LINE='rgba(243,242,242,0.13)',
     TAG_LINE='rgba(243,242,242,0.33)';
 var FONT='"IBM Plex Mono", ui-monospace, monospace';
 function bold(px){return '700 '+px+'px '+FONT;}
 function med(px){return '500 '+px+'px '+FONT;}

 var wmP=null;
 function loadWordmark(){
  if(!wmP){
   wmP=new Promise(function(res){
    var img=new Image();
    img.onload=function(){res(img);};
    // The card must not fail on a missing asset: the fallback draws the wordmark
    // tekstina. Sama sopimus kuin SPA:ssa.
    img.onerror=function(){res(null);};
    img.src='/assets/brand/goaliq-wordmark-teletext.png';
   });
  }
  return wmP;
 }

 function shrink(ctx,text,px,maxW,minPx,weight){
  ctx.font=weight(px);
  while(ctx.measureText(text).width>maxW&&px>minPx){px-=2;ctx.font=weight(px);}
  return px;
 }

 function render(spec){
  var fonts=(document.fonts&&document.fonts.load)
   ? Promise.all([document.fonts.load(bold(60)),document.fonts.load(bold(36)),
                  document.fonts.load(med(24))])['catch'](function(){})
   : Promise.resolve();
  return fonts.then(loadWordmark).then(function(wm){
   var n=spec.rows.length,H=ROW_TOP+n*ROW_H+FOOT_H;
   var c=document.createElement('canvas');
   c.width=W;c.height=H;
   var ctx=c.getContext('2d');
   ctx.textBaseline='top';

   var g=ctx.createLinearGradient(0,0,0,H);
   g.addColorStop(0,INK);g.addColorStop(1,INK2);
   ctx.fillStyle=g;ctx.fillRect(0,0,W,H);

   if(wm){
    var wmH=84,wmW=Math.round(wm.width*wmH/wm.height);
    ctx.drawImage(wm,(W-wmW)/2,64,wmW,wmH);
   }else{
    ctx.font=bold(56);
    var gw=ctx.measureText('GOAL').width,box=76,total=gw+14+box,x0=(W-total)/2;
    ctx.fillStyle=CREAM;ctx.fillText('GOAL',x0,72);
    ctx.fillStyle=AMBER;ctx.fillRect(x0+gw+14,64,box,box);
    ctx.fillStyle=INK;ctx.font=bold(40);
    ctx.fillText('IQ',x0+gw+14+(box-ctx.measureText('IQ').width)/2,82);
   }
   ctx.fillStyle=AMBER;
   ctx.beginPath();
   if(ctx.roundRect){ctx.roundRect((W-120)/2,176,120,6,3);ctx.fill();}
   else{ctx.fillRect((W-120)/2,176,120,6);}

   // Title and subtitle shrink to fit. The filter list can be long
   // ("Goal threat, per 90, DEF, 900+ mins, ARS, 42 players"), and
   // without shrinking it would spill over the card edges.
   var tf=shrink(ctx,spec.title,60,W-2*MX,34,bold);
   ctx.font=bold(tf);ctx.fillStyle=CREAM;
   ctx.fillText(spec.title,(W-ctx.measureText(spec.title).width)/2,226);
   var sf=shrink(ctx,spec.subtitle,22,W-2*MX,13,med);
   ctx.font=med(sf);ctx.fillStyle=MUTED;
   ctx.fillText(spec.subtitle,(W-ctx.measureText(spec.subtitle).width)/2,306);

   var fxRight=W-MX-180;
   ctx.font=med(19);
   ctx.fillText(spec.nameLabel||'PLAYER',MX+76,ROW_TOP-34);
   if(spec.midLabel){
    ctx.fillText(spec.midLabel,fxRight-ctx.measureText(spec.midLabel).width,
                 ROW_TOP-34);
   }
   ctx.fillText(spec.valueLabel,
                W-MX-ctx.measureText(spec.valueLabel).width,ROW_TOP-34);

   for(var i=0;i<n;i++){
    var r=spec.rows[i],y=ROW_TOP+i*ROW_H,cy=y+ROW_H/2,first=(i===0);
    ctx.strokeStyle=first?AMBER:LINE;ctx.lineWidth=first?2:1;
    ctx.strokeRect(MX-12,y+4,W-2*(MX-12),ROW_H-8);

    ctx.font=bold(28);ctx.fillStyle=first?AMBER:MUTED;
    var rk=String(r.rank);
    ctx.fillText(rk,MX+34-ctx.measureText(rk).width,cy-16);

    var x=MX+76;
    var nPx=shrink(ctx,r.name,32,330,20,bold);
    ctx.font=bold(nPx);ctx.fillStyle=CREAM;
    ctx.fillText(r.name,x,cy-nPx*0.62);
    x+=ctx.measureText(r.name).width+16;

    if(r.tag){
     ctx.font=bold(17);
     var pw=ctx.measureText(r.tag).width+16;
     ctx.strokeStyle=TAG_LINE;ctx.lineWidth=1;
     ctx.strokeRect(x,cy-15,pw,30);
     ctx.fillText(r.tag,x+8,cy-10);
     x+=pw+12;
    }

    if(r.team){
     ctx.font=med(20);ctx.fillStyle=MUTED;
     ctx.fillText(r.team,x,cy-10);
     x+=ctx.measureText(r.team).width+12;
    }

    if(r.mid){
     var fPx=shrink(ctx,r.mid,24,190,14,med);
     ctx.font=med(fPx);ctx.fillStyle=MUTED;
     ctx.fillText(r.mid,fxRight-ctx.measureText(r.mid).width,cy-fPx*0.55);
    }

    ctx.font=bold(36);ctx.fillStyle=first?AMBER:CREAM;
    ctx.fillText(r.value,W-MX-ctx.measureText(r.value).width,cy-36*0.58);
   }

   // The footer comes from the SPEC. The default text ("logged before
   // kickoff, graded in public") is a MATCH PREDICTION claim and is not
   // true of a stats list -- a shared image must not claim more than the
   // data supports. The handle reserves the right edge of the same row: a
   // footer that runs long would draw OVER it (seen in the PIL version,
   // 9 Aug).
   ctx.font=bold(20);
   var hw=ctx.measureText('@goaliqapp').width;
   var fn=spec.footNote||'logged before kickoff, graded in public';
   var ff=shrink(ctx,fn,20,W-2*MX-hw-24,13,med);
   ctx.font=med(ff);ctx.fillStyle=MUTED;
   ctx.fillText(fn,MX,H-88);
   ctx.font=bold(20);ctx.fillStyle=AMBER;
   ctx.fillText('@goaliqapp',W-MX-hw,H-88);
   ctx.font=med(17);ctx.fillStyle=MUTED;
   ctx.fillText(spec.footNote2||'model projections, not betting advice',
                MX,H-54);
   ctx.fillStyle=AMBER;ctx.fillRect(0,H-8,W,8);

   return new Promise(function(res,rej){
    c.toBlob(function(b){b?res(b):rej(new Error('toBlob failed'));},'image/png');
   });
  });
 }

 function deliver(blob,fileName){
  var file=null;
  try{file=new File([blob],fileName,{type:'image/png'});}catch(e){}
  // On a phone the native share sheet is what the user expects; on desktop
  // and wherever sharing is unavailable, fall back to download.
  if(file&&navigator.canShare&&navigator.canShare({files:[file]})&&navigator.share){
   return navigator.share({files:[file]})['catch'](function(){download(blob,fileName);});
  }
  download(blob,fileName);
  return Promise.resolve();
 }
 function download(blob,fileName){
  var u=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=u;a.download=fileName;document.body.appendChild(a);a.click();
  a.remove();setTimeout(function(){URL.revokeObjectURL(u);},1000);
 }

 var btn=document.getElementById('sharecard');
 if(!btn)return;
 btn.addEventListener('click',function(){
  var spec=null;
  try{spec=(__CARD_ROWS_FN__)();}catch(e){spec=null;}
  if(!spec||!spec.rows||!spec.rows.length){
   btn.textContent='Nothing to share yet';
   return;
  }
  var label=btn.textContent;
  btn.disabled=true;btn.textContent='Building card...';
  render(spec).then(function(b){return deliver(b,spec.fileName);})
   .then(function(){btn.disabled=false;btn.textContent=label;})
   ['catch'](function(){btn.disabled=false;btn.textContent='Card failed';});
 });
})();
</script>
"""
