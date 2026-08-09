# -*- coding: utf-8 -*-
"""Jaettu mobiili-CSS kaikille goaliq.app-sivuille.

TAUSTA (9.8.2026, Villen havainto X-liikenteesta): puhelimella avattu sivu
nayttaa rikkinaiselta -- navi hajoaa kahdelle riville paallekkain, ottelurivit
menevat solmuun ja taulukot ovat 1,1-3,1 x ruudun levyisia.

MIKSI TAMA ON OMA MODUULINSA: sama navi-CSS oli kopioituna NELJAAN paikkaan
(build_fpl_page.py, build_fpl_longtail.py, build_prediction_pages.py + kasin
yllapidetyt juurisivut). Yhden kopion korjaus olisi osunut vain yhteen
sivuperheeseen ja loput olisivat jaaneet rikki -- tasmalleen sama vika kuin
SPA:n liigalistoissa 8.8 (kuratoitu lista oli haudattu yhteen komponenttiin).

KAYTTO: builderit liittavat MOBILE_CSS:n oman CSS-merkkijononsa LOPPUUN.
Lohko on markkeroitu, joten scripts/apply_mobile_css.py osaa paivittaa sen
paikallaan myos kasin yllapidetyilla sivuilla -- ajo on idempotentti.

TARKEA: lohkon on oltava <style>-elementin VIIMEINEN osa. Saannot voittavat
aiemmat samalla spesifisyydella vain jarjestyksen perusteella; jos lohko
siirtyy ylospain, korjaukset lakkaavat toimimasta HILJAA.
"""

BEGIN_MARKER = "/* GEN:MOBILE-CSS */"
END_MARKER = "/* /GEN:MOBILE-CSS */"

# Sarakepolitiikka (Villen valinta (a) 9.8): kapealla naytolla nakyvat vain
# avainsarakkeet, loput saavat .m-hide-luokan. Luvut ovat tassa, jotta
# "montako saraketta puhelin nayttaa" on yksi paatos eika neljä.
MOBILE_GW_COLS = 3        # gameweek-sarakkeita fpl.html:n FDR-ruudukossa
MOBILE_BLOCK_COLS = 3     # lohkosarakkeita pitkan aikavalin ruudukossa

# Katkaisupiste 560px: 390px (iPhone 14/15) ja 412px (Pixel/Galaxy) ovat
# reilusti alle, 3. sukupolven iPad Mini pystyssa (768px) jaa ulkopuolelle.
_RULES = """
/* Vain kapealla naytolla nakyva selite. Oletuksena piilossa, jotta
   leveiden naytoiden sivut eivat muutu lainkaan. */
.m-only{display:none;}

@media (max-width:560px){
  .m-only{display:block;}

  /* --- 1. NAVI ---------------------------------------------------------
     Vika: nav{justify-content:space-between} + kaksi joustamatonta lasta.
     390px:ssa brandi ja linkkipari eivat mahdu samalle riville, joten
     molemmat rivittyivat sisaisesti: "GoalIQ" katkesi logon alle ja
     "Try it live" -napin teksti valui napin ulkopuolelle.
     Korjaus: sallitaan rivitys ELEMENTTIEN valilla, ei niiden sisalla. */
  nav,.nav{flex-wrap:wrap;gap:10px;padding-top:14px;padding-bottom:14px;}
  .brand{font-size:18px;white-space:nowrap;flex:0 0 auto;}
  .brand-icon{width:20px;height:20px;margin-right:6px;}
  nav>span,.nav>span{flex:1 1 100%;font-size:13px;}
  .nav-cta{display:inline-block;white-space:nowrap;padding:8px 14px;}

  /* --- 2. OTTELURIVIT --------------------------------------------------
     Vika: .mrow on flex-rivi, jossa joukkuenimi sai kolme rivia ja
     todennakoisyys leijui oikealla eri korkeudella -- rivia ei voinut
     lukea vasemmalta oikealle. Korjaus: pinotaan. */
  .mrow{flex-direction:column;align-items:flex-start;gap:2px;padding:10px 0;}
  .mrow>div{width:100%;}
  /* Pinoaminen lyhensi ottelulinkkeja (nimi mahtuu nyt yhdelle riville),
     jolloin kosketuskohteesta tuli alle 32px. Leveys taydeksi + pystypadding
     nostaa rivin takaisin sormenpaan kokoon. */
  .mrow a{display:block;width:100%;padding:7px 0;}
  .pick{font-size:14px;}

  /* --- 3. TAULUKOT: sarakeprioriteetti (Villen valinta (a) 9.8) --------
     Builderit merkitsevat vahemman tarkeat sarakkeet .m-hide:lla; kapealla
     naytolla nakyvat vain avainsarakkeet. Taysi taulukko sailyy
     leveammilla naytoilla muuttumattomana. */
  th.m-hide,td.m-hide{display:none;}

  /* ...MUTTA piilotettu ei saa tarkoittaa saavuttamatonta (Villen huomio
     9.8). Karsinta on OLETUS, ei lopputila: "Show all columns" palauttaa
     jokaisen sarakkeen jokaisessa taulukossa kerralla, ja taulukko
     vierittaa vaakaan kuten leveallakin naytolla. Korkeampi spesifisyys
     samassa media queryssa -> voittaa jarjestyksesta riippumatta. */
  body.cols-all th.m-hide,body.cols-all td.m-hide{display:table-cell;}
  body.cols-all .m-only{display:none;}

  .colstoggle{display:inline-block;margin:10px 0 4px;padding:9px 14px;
    min-height:40px;border:1px solid var(--line-strong,rgba(128,128,128,.5));
    background:transparent;color:inherit;font:inherit;font-size:13px;
    font-weight:600;cursor:pointer;border-radius:0;}
  .colstoggle[aria-pressed="true"]{border-color:var(--amber,#F5C542);
    color:var(--amber,#F5C542);}

  /* Pitkat tekstisolut saavat rivittya; luvut eivat (tabular-nums hajoaa
     ja "1,25" katkeaisi kahdelle riville). */
  .lb th,.lb td,.scroll table th,.scroll table td{white-space:normal;}
  .lb th.n,.lb td.n,.scroll table th.num,.scroll table td.num{
    white-space:nowrap;}
  .lb{font-size:13px;}
  /* Vaakapadding 8px -> 5px. Mitattu: stats.html jai 404px:aan (30px yli)
     senkin jalkeen kun kontekstisarakkeet oli piilotettu, ja yhdeksassa
     sarakkeessa padding yksin oli 144px. Tiukempi padding sailyttaa
     sarakkeen; sarakkeen pudottaminen olisi hukannut tietoa. */
  .lb th,.lb td{padding:7px 5px;}

  /* Taulukoiden min-width pakotti vierityksen myos silloin kun sarakkeita
     oli piilotettu niin etta loput olisivat mahtuneet. */
  .lb-wrap>.lb,.scroll>table,.table-wrap>table,.rec-scroll>table{
    min-width:0;}
  table{min-width:0;}

  /* HILJAINEN LEIKKAUS (9.8, loytyi vasta kuvasta):
     width:auto + min-width:0 sai taulukon kutistumaan TASMALLEEN kaareen
     (tableW=374=wrapClient), jolloin nowrap-numerosarakkeet eivat mahtuneet
     soluihinsa ja "28.17" renderoitiin muodossa "28.". Taulukko ei ollut
     ylileveä eika kaare vierittanyt, joten EI leveysmittaus EIKA
     scrollWidth-tarkistus nahnyt tata -- vain silmä.
     width:max-content pakottaa taulukon luonnolliseen leveyteensa: jos se ei
     mahdu, kaare vierittaa nakyvasti sen sijaan etta dataa katoaisi
     aanettomasti. Nakyva vieritys on huono, hiljaa kadonnut luku on pahempi. */
  .lb-wrap>.lb{width:max-content;max-width:none;}
  /* HUOM SPESIFISYYS: BYCOMP_CSS injektoidaan fpl.html:aan ja
     predictions.html:aan OMANA <style>-elementtinaan MYOHEMMIN sivulla, eli
     se voittaa taman lohkon dokumenttijarjestyksessa. Media query ei nosta
     spesifisyytta, joten .rec-scroll table (0,1,1) ei riittaisi kumoamaan
     sen min-width:640px:aa. div.-etuliite nostaa (0,1,2) ja tekee saannosta
     jarjestyksesta riippumattoman. */
  div.rec-scroll table{min-width:0;}
  /* Ottelunimi oli nowrap ("Nottingham Forest v Crystal Palace" = 277px
     yhdella rivilla), mika yksin teki track record -taulusta 3 x ruudun. */
  div.rec-scroll td.team,.scroll td.team{white-space:normal;}
  div.rec-scroll th,div.rec-scroll td{padding:7px 6px;font-size:13px;}
  /* Kick-off oli "2026-08-21 19:00:00 UTC" yhdella rivilla = 195px, eli
     yksi sarake vei kolmanneksen puhelimen leveydesta. Nama luvut ovat
     paivamaaria eivatka tasattavia numeroita, joten rivitys on turvallinen. */
  div.rec-scroll td.num,div.rec-scroll th.num{white-space:normal;}
  /* FDR-ruudukon solu on "ARS (H) 60%" = kolme osaa yhdella rivilla.
     nowrap piti ruudukon 472px:ssa vaikka sarakkeita oli jo piilotettu;
     rivittyva solu vie kaksi rivia ja puolittaa leveyden. */
  .fdr-grid td.num,.scroll td.num .fdr,.fdr{white-space:normal;}
  .fdr{min-width:0;}

  /* Vieritysvihje: nakyy vain siella minne builder sen lisaa, eli
     taulukoissa jotka vierivat sarakkeiden piilotuksen jalkeenkin. */
  .scrollhint{display:block;color:var(--muted,#A8A29A);font-size:12px;
    margin:6px 0 0;}

  /* --- 4. SUODATINNAPIT ------------------------------------------------
     Vika: .chips{display:inline-flex} ilman rivitysta -> nappirivi oli
     454px, ja koska html/body on overflow-x:clip, viimeinen nappi
     ("Set pieces") oli fyysisesti saavuttamattomissa puhelimella.
     Korjaus: rivitys + jokainen suodatinryhma omalle rivilleen. */
  .lbctl{gap:6px 8px;}
  .lbctl .lbl{flex:1 1 100%;margin:10px 0 0;}
  .lbctl .lbl:first-child{margin-top:0;}
  .chips{display:flex;flex-wrap:wrap;gap:6px;max-width:100%;}
  .chip{min-height:36px;}
  .lbctl select,.lbctl input{min-height:36px;max-width:100%;}

  /* --- 5. LUETTAVUUS ---------------------------------------------------
     12px monospace on puhelimessa alle luettavan rajan. */
  .meta,.note,.stat span,.legend,.mrow .meta,footer{font-size:13px;}
  .hero .lede,.lede{font-size:16px;}
  .stat b{font-size:24px;}

  /* --- 6. KOSKETUSKOHTEET ---------------------------------------------- */
  .btn,.cta,.nav-cta{min-height:44px;display:inline-flex;align-items:center;
    justify-content:center;}
  .toolnav a{display:inline-block;padding:4px 0;}
}

/* Erittain kapea (esim. iPhone SE 375px / Galaxy Fold ulkonaytto 344px):
   brandi ja CTA eivat mahdu edes pienennettyina, ja hero-otsikko
   ylivuotaa jos siina on pitkia sanoja. */
@media (max-width:400px){
  .wrap{padding-left:14px;padding-right:14px;}
  .hero h1,h1{font-size:26px;overflow-wrap:break-word;}
  .brand{font-size:17px;}
  /* Fonttia EI pienenneta 12px:aan taalla. Kokeiltiin 9.8 ja mitattiin:
     se teki 1200 solusta alle 13px:n eli alle luettavan rajan, ja
     sarakkeiden piilotus riitti jo mahduttamaan taulukot ilman sita.
     Padding sen sijaan kiristetaan: stats.html on tihein taulukko
     (9 nakyvaa saraketta) ja jai 404px:aan 6px:n paddingilla eli 14px yli
     puhelimen leveyden. Luonnollinen leveys (width:max-content) on 383px
     4px:n paddingilla; 3px vie sen 365:aan eli kaareen (374) mahtuvaksi. */
  .lb th,.lb td{padding:6px 3px;}
}
"""

MOBILE_CSS = BEGIN_MARKER + _RULES + END_MARKER + "\n"


# ---------------------------------------------------------------------------
# "Show all columns" -kytkin (Villen huomio 9.8: piilotettu ei saa tarkoittaa
# saavuttamatonta). Karsinta on oletus, tama on ulospaasy.
#
# MIKSI JS EIKA MARKUP: nappi lisataan JOKAISEN sellaisen taulukon eteen jossa
# on .m-hide-sarakkeita, eika yhtakaan builderia tarvitse muuttaa. Jos nappi
# kirjoitettaisiin markupiin, se pitaisi lisata neljaan builderiin ja kymmeneen
# kasin yllapidettyyn sivuun erikseen -- eli sama nelinkertainen kopio josta
# koko tama urakka alkoi.
#
# Napit pidetaan synkassa: ne kaikki kaantavat samaa body-luokkaa, joten sivun
# alalaidan nappi ei voi vaittaa eri tilaa kuin ylalaidan.
# ---------------------------------------------------------------------------
COLS_JS_BEGIN = "<!-- GEN:MOBILE-COLS -->"
COLS_JS_END = "<!-- /GEN:MOBILE-COLS -->"

MOBILE_COLS_JS = COLS_JS_BEGIN + """
<script>
(function(){
 function init(){
  if(!document.querySelector('.m-hide'))return;
  var WRAPS='.lb-wrap,.scroll,.table-wrap,.rec-scroll',
      seen=[],btns=[],i;
  var wraps=document.querySelectorAll(WRAPS);
  for(i=0;i<wraps.length;i++){
   if(!wraps[i].querySelector('.m-hide'))continue;
   seen.push(wraps[i]);
  }
  // Taulukko ilman tunnettua kaarta (esim. kasin kirjoitettu sivu): laitetaan
  // nappi taulukon itsensa eteen, jotta yksikaan piilotettu sarake ei jaa
  // ilman ulospaasya.
  var tables=document.querySelectorAll('table');
  for(i=0;i<tables.length;i++){
   if(!tables[i].querySelector('.m-hide'))continue;
   var w=tables[i].closest(WRAPS);
   if(!w&&seen.indexOf(tables[i])<0)seen.push(tables[i]);
  }
  if(!seen.length)return;

  function label(on){return on?'Show key columns':'Show all columns';}
  function sync(on){
   for(var j=0;j<btns.length;j++){
    btns[j].textContent=label(on);
    btns[j].setAttribute('aria-pressed',on?'true':'false');
   }
  }
  function toggle(){
   var on=document.body.classList.toggle('cols-all');
   sync(on);
  }
  for(i=0;i<seen.length;i++){
   var host=document.createElement('p');
   host.className='m-only';
   host.style.margin='0';
   var b=document.createElement('button');
   b.type='button';
   b.className='colstoggle';
   b.setAttribute('aria-pressed','false');
   b.textContent=label(false);
   b.addEventListener('click',toggle);
   host.appendChild(b);
   seen[i].parentNode.insertBefore(host,seen[i]);
   btns.push(b);
  }
 }
 if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',init);
 }else{init();}
})();
</script>
""" + COLS_JS_END + "\n"
