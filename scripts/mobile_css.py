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
/* Note shown only on narrow screens. Hidden by default so that pages on
   wide screens do not change at all. */
.m-only{display:none;}

@media (max-width:560px){
  .m-only{display:block;}

  /* --- 1. NAV ----------------------------------------------------------
     Bug: nav{justify-content:space-between} plus two inflexible children.
     At 390px the brand and the link pair do not fit on one line, so both
     wrapped internally instead: "GoalIQ" broke below the logo and the
     "Try it live" button text spilled outside the button.
     Fix: allow wrapping BETWEEN elements, not inside them. */
  nav,.nav{flex-wrap:wrap;gap:10px;padding-top:14px;padding-bottom:14px;}
  .brand{font-size:18px;white-space:nowrap;flex:0 0 auto;}
  .brand-icon{width:20px;height:20px;margin-right:6px;}
  nav>span,.nav>span{flex:1 1 100%;font-size:13px;}
  .nav-cta{display:inline-block;white-space:nowrap;padding:8px 14px;}

  /* --- 2. MATCH ROWS ---------------------------------------------------
     Bug: .mrow is a flex row where the team name took three lines and the
     probability floated right at a different height, so the row could not
     be read left to right. Fix: stack it. */
  .mrow{flex-direction:column;align-items:flex-start;gap:2px;padding:10px 0;}
  .mrow>div{width:100%;}
  /* Stacking shortened the match links (the name now fits on one line),
     which dropped the touch target below 32px. Full width plus vertical
     padding brings the row back to fingertip size. */
  .mrow a{display:block;width:100%;padding:7px 0;}
  .pick{font-size:14px;}

  /* --- 3. TABLES: column priority (option (a), chosen 9 Aug) -----------
     Builders mark the less important columns with .m-hide; on a narrow
     screen only the key columns show. The full table stays unchanged on
     wider screens. */
  th.m-hide,td.m-hide{display:none;}

  /* ...BUT hidden must not mean unreachable (raised 9 Aug). The trimming is
     a DEFAULT, not an end state: "Show all columns" restores every column
     in every table at once, and the table then scrolls horizontally just
     as it does on a wide screen. Higher specificity inside the same media
     query -> wins regardless of order. */
  body.cols-all th.m-hide,body.cols-all td.m-hide{display:table-cell;}
  body.cols-all .m-only{display:none;}

  /* Bring a hidden column's number back into the row as a subline (10 Aug).
     The column does not fit as a 5th column at 390px, but "Show all
     columns" is two interactions too far from a number nobody knows to
     look for yet. The subline gives the same number without the column,
     and because it is .m-only it DISAPPEARS when the column comes back ->
     the number is never shown twice. */
  td .m-sub{font-size:11px;font-weight:400;opacity:.72;padding-top:2px;}

  .colstoggle{display:inline-block;margin:10px 0 4px;padding:9px 14px;
    min-height:40px;border:1px solid var(--line-strong,rgba(128,128,128,.5));
    background:transparent;color:inherit;font:inherit;font-size:13px;
    font-weight:600;cursor:pointer;border-radius:0;}
  .colstoggle[aria-pressed="true"]{border-color:var(--amber,#F5C542);
    color:var(--amber,#F5C542);}

  /* Long text cells may wrap; numbers may not (tabular-nums breaks down and
     "1.25" would split across two lines). */
  .lb th,.lb td,.scroll table th,.scroll table td{white-space:normal;}
  .lb th.n,.lb td.n,.scroll table th.num,.scroll table td.num{
    white-space:nowrap;}
  .lb{font-size:13px;}
  /* Horizontal padding 8px -> 5px. Measured: stats.html still came out at
     404px (30px over) after the context columns were hidden, and across
     nine columns the padding alone was 144px. Tighter padding keeps the
     column; dropping a column would have lost information. */
  .lb th,.lb td{padding:7px 5px;}

  /* The tables' min-width forced scrolling even when enough columns were
     hidden that the rest would have fit. */
  .lb-wrap>.lb,.scroll>table,.table-wrap>table,.rec-scroll>table{
    min-width:0;}
  table{min-width:0;}

  /* SILENT TRUNCATION (9 Aug, only ever caught in a screenshot):
     width:auto + min-width:0 shrank the table to EXACTLY the wrapper
     (tableW=374=wrapClient), so nowrap number columns no longer fit their
     cells and "28.17" rendered as "28.". The table was not overwide and
     the wrapper did not scroll, so NEITHER a width measurement NOR a
     scrollWidth check could see this. Only the eye could.
     width:max-content forces the table to its natural width: if it does not
     fit, the wrapper scrolls visibly instead of data disappearing in
     silence. Visible scrolling is bad, a quietly lost number is worse. */
  .lb-wrap>.lb{width:max-content;max-width:none;}
  /* SPECIFICITY WARNING: BYCOMP_CSS is injected into fpl.html and
     predictions.html as its OWN <style> element LATER in the page, so it
     beats this block on document order. A media query does not raise
     specificity, so .rec-scroll table (0,1,1) would not be enough to
     override its min-width:640px. The div. prefix raises it to (0,1,2) and
     makes the rule order-independent. */
  div.rec-scroll table{min-width:0;}
  /* The match name was nowrap ("Nottingham Forest v Crystal Palace" =
     277px on one line), which alone made the track record table three
     screens wide. */
  div.rec-scroll td.team,.scroll td.team{white-space:normal;}
  div.rec-scroll th,div.rec-scroll td{padding:7px 6px;font-size:13px;}
  /* Kick-off was "2026-08-21 19:00:00 UTC" on one line = 195px, so a single
     column took a third of the phone's width. These values are dates rather
     than numbers that need aligning, so wrapping is safe here. */
  div.rec-scroll td.num,div.rec-scroll th.num{white-space:normal;}
  /* An FDR grid cell is "ARS (H) 60%" = three parts on one line. nowrap kept
     the grid at 472px even after columns had been hidden; a wrapping cell
     takes two lines and halves the width. */
  .fdr-grid td.num,.scroll td.num .fdr,.fdr{white-space:normal;}
  .fdr{min-width:0;}

  /* Scroll hint: appears only where the builder adds it, that is, in tables
     that still scroll after columns have been hidden. */
  .scrollhint{display:block;color:var(--muted,#A8A29A);font-size:12px;
    margin:6px 0 0;}

  /* --- 4. FILTER CHIPS -------------------------------------------------
     Bug: .chips{display:inline-flex} without wrapping -> the chip row was
     454px, and because html/body is overflow-x:clip the last chip ("Set
     pieces") was physically unreachable on a phone.
     Fix: allow wrapping, and give each filter group its own line. */
  .lbctl{gap:6px 8px;}
  .lbctl .lbl{flex:1 1 100%;margin:10px 0 0;}
  .lbctl .lbl:first-child{margin-top:0;}
  .chips{display:flex;flex-wrap:wrap;gap:6px;max-width:100%;}
  .chip{min-height:36px;}
  .lbctl select,.lbctl input{min-height:36px;max-width:100%;}

  /* --- 5. READABILITY --------------------------------------------------
     12px monospace is below the readable limit on a phone. */
  .meta,.note,.stat span,.legend,.mrow .meta,footer{font-size:13px;}
  .hero .lede,.lede{font-size:16px;}
  .stat b{font-size:24px;}

  /* --- 6. TOUCH TARGETS ------------------------------------------------ */
  .btn,.cta,.nav-cta{min-height:44px;display:inline-flex;align-items:center;
    justify-content:center;}
  .toolnav a{display:inline-block;padding:4px 0;}
}

/* Very narrow (e.g. iPhone SE 375px / Galaxy Fold cover screen 344px):
   the brand and the CTA do not fit even when scaled down, and the hero
   heading overflows if it contains long words. */
@media (max-width:400px){
  .wrap{padding-left:14px;padding-right:14px;}
  .hero h1,h1{font-size:26px;overflow-wrap:break-word;}
  .brand{font-size:17px;}
  /* The font is NOT dropped to 12px here. Tried and measured 9 Aug: it took
     1200 cells below 13px, which is under the readable limit, and hiding
     columns was already enough to fit the tables without it.
     Padding is tightened instead: stats.html is the densest table
     (9 visible columns) and came out at 404px with 6px padding, i.e. 14px
     over the phone's width. Its natural width (width:max-content) is 383px
     at 4px padding; 3px takes it to 365px, which fits the wrapper (374). */
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
  // Table without a known wrapper (e.g. a hand-written page): put the
  // button directly before the table itself, so no hidden column is ever
  // left without a way out.
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

# ---------------------------------------------------------------------------
# Luojan ref-silta (16.8.2026)
# ---------------------------------------------------------------------------
# Miksi TAMA tiedosto, vaikka silta ei liity mobiili-CSS:aan: jokainen
# sivugeneraattori emittoi jo `MOBILE_COLS_JS`:n juuri ennen </body>:a. Kun
# silta menee samaan merkkijonoon, uusi generaattori ei voi unohtaa sita.
#
# Vaihtoehto oli lisata `<script>` neljaan generaattoriin kasin, ja tasan se
# unohtui: silta lisattiin 16.8 hub-sivuille ja `build_fpl_page.py`:hyn, mutta
# `build_fpl_longtail.py` (12 /fpl/-alasivua) ja `build_prediction_pages.py`
# (16 world-cup-sivua) jaivat ilman. Ne ovat juuri niita sivuja joita
# FPL-luoja linkkaa, ja `/fpl/best-captain` sisaltaa upsell-linkin
# pro.goaliq.appiin - eli attribuutio katosi tarkalleen siella missa se
# eniten merkitsi. Portti ei nahnyt sita, koska se katsoi vain juuren
# *.html-sivuja.
REF_BRIDGE_TAG = '<script defer src="/ref-bridge.js"></script>\n'
MOBILE_COLS_JS = MOBILE_COLS_JS + REF_BRIDGE_TAG
