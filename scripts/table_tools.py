# -*- coding: utf-8 -*-
"""Taulukon lajittelu ja suodatus generoiduille sivuille (15.8.2026).

VILLEN HAVAINTO joka laukaisi taman:
    "noihin ilmaisiin listoihinkin olisi hyva saada sorttausmahollisuudet,
     vaikea nyt tosta listasta sortata 8milj hyokkaajat vertailuun, siis ihan
     olematonta."

Han on oikeassa kirjaimellisesti: /fpl/expected-points on 100 rivia yhdessa
kiinteassa jarjestyksessa, eika sivulla ollut yhtaan suodatinta (mitattu 15.8:
`filter`-osumia 0). Jos lukija haluaa "hyokkaajat 8,0 M£ ja alle", hanen on
selattava sata rivia silmalla. Se ei ole lista vaan tuloste.

Sama havainto tuli riippumatta myos julkaisutarkistajalta: se ei pystynyt
verifioimaan hintavaitetta ILMAISPINNALTA puhelimella, koska hinta- ja
positiosarakkeet olivat `m-hide`. Eli sama puute esti seka kayton etta
tarkistamisen.

MIKSI JAETTU MODUULI EIKA SIVUKOHTAINEN KOODI
Repo on kaksi kertaa aiemmin oppinut taman: komponenttiin haudattu lista
korjaa vain yhden nakyman, ja MOBILE_COLS_JS kirjoitettiin nimenomaan siksi
ettei nappia tarvitse lisata neljaan builderiin. Tama liittyy JOKAISEEN
`table.lb`-taulukkoon automaattisesti, eika yhtakaan builderia tarvitse
muuttaa uuden sivun kohdalla.

MITA TAMA EI TEE
Ei uutta dataa, ei verkkokutsuja, ei kirjastoja. Se jarjestaa ja piilottaa
rivit jotka ovat jo sivulla. Sivun oma jarjestys sailyy oletuksena, ja
`#`-sarake pitaa ALKUPERAISEN sijan (se on sija xP:ssa, ei rivinumero) —
muuten lajittelu hinnan mukaan vaittaisi etta halvin pelaaja on liigan paras.
"""

TOOLS_BEGIN = "<!-- GEN:TABLE-TOOLS -->"
TOOLS_END = "<!-- /GEN:TABLE-TOOLS -->"

TABLE_TOOLS_JS = TOOLS_BEGIN + """
<style>
.tt-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 6px;}
.tt-chip{font:inherit;font-size:13px;padding:5px 11px;border-radius:999px;
  border:1px solid rgba(243,242,242,.28);background:transparent;color:inherit;
  cursor:pointer;line-height:1.2;}
.tt-chip[aria-pressed="true"]{background:#f5c542;color:#0b0a09;
  border-color:#f5c542;font-weight:600;}
.tt-price{font:inherit;font-size:13px;padding:5px 8px;border-radius:8px;
  border:1px solid rgba(243,242,242,.28);background:transparent;color:inherit;
  width:5.5em;}
.tt-count{font-size:12px;opacity:.7;}
.tt-clear{font-size:12px;text-decoration:underline;cursor:pointer;
  background:none;border:0;color:inherit;padding:0;}
table.lb thead th[data-sortable]{cursor:pointer;user-select:none;
  white-space:nowrap;}
table.lb thead th[data-sortable]:after{content:" \\2195";opacity:.35;}
table.lb thead th[data-dir="asc"]:after{content:" \\2191";opacity:1;}
table.lb thead th[data-dir="desc"]:after{content:" \\2193";opacity:1;}
</style>
<script>
(function(){
 function num(s){
  // Parse a cell into a number. Both "6.0" and "6,0" appear on generated
  // pages, so the comma decimal is accepted too.
  if(s==null)return NaN;
  var t=String(s).replace(/[^0-9.,\\-]/g,'').replace(',','.');
  if(t===''||t==='-')return NaN;
  var v=parseFloat(t);
  return isNaN(v)?NaN:v;
 }
 function txt(td){return (td.textContent||'').trim();}

 function colIndex(tb,names){
  var th=tb.querySelectorAll('thead th'),i,n;
  for(i=0;i<th.length;i++){
   n=(th[i].textContent||'').trim().toLowerCase();
   for(var j=0;j<names.length;j++){if(n===names[j])return i;}
  }
  return -1;
 }

 function initSort(tb){
  var th=tb.querySelectorAll('thead th');
  if(!th.length)return;
  var tbody=tb.querySelector('tbody');
  if(!tbody)return;
  Array.prototype.forEach.call(th,function(h,idx){
   if(idx===0)return;                    // rank column, not a sort key
   h.setAttribute('data-sortable','1');
   h.setAttribute('tabindex','0');
   h.setAttribute('role','button');
   function go(){
    var rows=Array.prototype.slice.call(tbody.rows);
    var dir=h.getAttribute('data-dir')==='desc'?'asc':'desc';
    Array.prototype.forEach.call(th,function(x){x.removeAttribute('data-dir');});
    h.setAttribute('data-dir',dir);
    var mul=dir==='asc'?1:-1;
    rows.sort(function(a,b){
     var av=txt(a.cells[idx]),bv=txt(b.cells[idx]);
     var an=num(av),bn=num(bv);
     if(!isNaN(an)&&!isNaN(bn))return (an-bn)*mul;
     // Missing values sink to the bottom in both directions, so a blank
     // never reads as the best row when sorting ascending.
     if(isNaN(an)&&!isNaN(bn))return 1;
     if(!isNaN(an)&&isNaN(bn))return -1;
     return av.localeCompare(bv)*mul;
    });
    rows.forEach(function(r){tbody.appendChild(r);});
   }
   h.addEventListener('click',go);
   h.addEventListener('keydown',function(e){
    if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}
   });
  });
 }

 function initFilter(tb){
  var tbody=tb.querySelector('tbody');
  if(!tbody||tbody.rows.length<8)return;   // short table needs no filter
  var pos=colIndex(tb,['pos','position']);
  var price=colIndex(tb,['price','cost','£']);
  if(pos<0&&price<0)return;

  var bar=document.createElement('div');
  bar.className='tt-bar';
  var state={pos:null,max:null};
  var count=document.createElement('span');
  count.className='tt-count';

  function apply(){
   var shown=0,rows=tbody.rows,i,r,ok;
   for(i=0;i<rows.length;i++){
    r=rows[i];ok=true;
    if(state.pos&&pos>=0)
     ok=ok&&txt(r.cells[pos]).toUpperCase()===state.pos;
    if(state.max!=null&&price>=0){
     var v=num(txt(r.cells[price]));
     ok=ok&&!isNaN(v)&&v<=state.max;
    }
    r.style.display=ok?'':'none';
    if(ok)shown++;
   }
   count.textContent=shown+' of '+rows.length+' shown';
  }

  if(pos>=0){
   ['GKP','DEF','MID','FWD'].forEach(function(p){
    var b=document.createElement('button');
    b.type='button';b.className='tt-chip';b.textContent=p;
    b.setAttribute('aria-pressed','false');
    b.addEventListener('click',function(){
     state.pos=state.pos===p?null:p;
     Array.prototype.forEach.call(bar.querySelectorAll('.tt-chip'),function(x){
      x.setAttribute('aria-pressed',String(x.textContent===state.pos));
     });
     apply();
    });
    bar.appendChild(b);
   });
  }
  if(price>=0){
   var lab=document.createElement('label');
   lab.style.fontSize='13px';lab.style.opacity='.85';
   lab.textContent='Max price ';
   var inp=document.createElement('input');
   inp.type='number';inp.step='0.5';inp.min='0';inp.className='tt-price';
   inp.placeholder='any';
   inp.setAttribute('aria-label','Maximum price in millions');
   inp.addEventListener('input',function(){
    var v=parseFloat(inp.value);
    state.max=isNaN(v)?null:v;
    apply();
   });
   lab.appendChild(inp);
   bar.appendChild(lab);
  }
  var clr=document.createElement('button');
  clr.type='button';clr.className='tt-clear';clr.textContent='clear';
  clr.addEventListener('click',function(){
   state.pos=null;state.max=null;
   Array.prototype.forEach.call(bar.querySelectorAll('.tt-chip'),function(x){
    x.setAttribute('aria-pressed','false');});
   var i=bar.querySelector('.tt-price');if(i)i.value='';
   apply();
  });
  bar.appendChild(clr);
  bar.appendChild(count);

  var host=tb.closest('.lb-wrap')||tb;
  host.parentNode.insertBefore(bar,host);
  apply();
 }

 function init(){
  var tables=document.querySelectorAll('table.lb');
  Array.prototype.forEach.call(tables,function(tb){
   try{initSort(tb);initFilter(tb);}catch(e){/* leave the table as it was */}
  });
 }
 if(document.readyState==='loading')
  document.addEventListener('DOMContentLoaded',init);
 else init();
})();
</script>
""" + TOOLS_END
