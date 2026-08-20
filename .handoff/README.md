# Handoff: SHARE-CARD-WHY-EMPHASIS (20.8)

**Tämä patch EI kuulu tähän repoon.** Sen kohde on
`GoalIQ/football-prediction` (migroitu web-/API-repo, 17.8), jonne tämä
sessio ei saanut työntöoikeutta — repo on eri omistajalla eikä sitä voi
liittää samaan sessioon. Patch on tallennettu tänne siksi, että se on
tavutarkka artefakti eikä kopioitava tekstipala.

Patch on tehty `GoalIQ/football-prediction` HEADia vasten (20.8 klo ~19 UTC).

## Mitä se tekee

Rowanin palaute 20.8 jaettuun pelaajakorttiin: *"making the 2–3 biggest
reasons stand out slightly more, so you can understand why the model likes
the player within a second or two."*

1. **`src/models/fpl_xp.py`** — `driver_facts()`: yhden rivin todisteluku
   jokaiselle WHY-ajurille mallin omista kentistä ("83 mins a game",
   "51% clean sheet chance", "0.15 xGI/90 last season", ...). Serve-timessa,
   ei putkessa: ei koske `build_fpl_why.component_hash`ia, joten olemassa
   olevia selityksiä EI generoida uusiksi. `attach_why` rajaa ajurilistan
   kolmeen **järjestystä muuttamatta** ja liittää `why.driver_facts`.
2. **`api/main.py`** — ETag-skeema `s6` → `s7` (serve-time-kenttä ei liikuta
   `generated_at`ia; ilman nostoa luvut jäisivät näkymättä juuri niiltä
   joilla vastaus on välimuistissa).
3. **`web/pro-spa/src/lib/whyDrivers.ts`** — `whyDriverRows()`: yksi lähde
   sivulle ja kortille.
4. **`WhyThisPick.svelte` + `shareCard.ts`** — tasa-arvoiset chipit →
   rivit: amber-tolppa + nimi vasemmalle, todisteluku amberilla oikeaan
   reunaan, sama pystylinja joka rivillä.
5. **`tests/test_fpl_why.py`** — 6 uutta testiä.

## Verifiointi tässä sessiossa

- `pytest tests/test_fpl_why.py tests/test_fpl_xp.py` → 45 + 66 vihreää
- `npm run check` (svelte-check) → 0 virhettä / 0 varoitusta, 341 tiedostoa
- `npm run build` → OK
- Kortti renderöity oikeasta koodista PNG:ksi kolmella tapauksella
  (pitkät arvot, puuttuvat `driver_facts`) — ei leikkautumista, puuttuva
  luku degradoituu pelkäksi nimeksi ilman placeholderia.

## Soveltaminen

```
git clone https://github.com/GoalIQ/football-prediction
cd football-prediction
git checkout -b claude/puhelimella-tehtavat-nkrnr2
curl -sL https://raw.githubusercontent.com/Veikkoville/football-prediction/claude/puhelimella-tehtavat-nkrnr2/.handoff/2026-08-20-share-card-why-emphasis.patch -o /tmp/p.patch
git apply --check /tmp/p.patch && git apply /tmp/p.patch
```

Mobiilipari on jo pushattu: `Veikkoville/goaliq-app`, haara
`claude/puhelimella-tehtavat-nkrnr2`.

🔒 Deploy (Render + wrangler) = Villen GO.
