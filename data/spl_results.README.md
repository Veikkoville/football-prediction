# spl_results.csv — Saudi Pro League -tulokset (vendoroitu)

Kaudet 2024/25 + 2025/26, 306 + 306 = 612 valmista ottelua. Lähde: ESPN:n
julkinen scoreboard-API (`site.api.espn.com/.../soccer/ksa.1/scoreboard`),
haettu 7.8.2026 skriptillä `scripts/fetch_spl_results_espn.py`.

Käyttö: `scripts/build_spl_phase0.py` sovittaa tästä Dixon-Coles-priorit
SPL-fantasy-tuotteelle (maalipohjainen fitti — SPL:lle ei ole ilmaista
xG-fixturefeediä). Vendoroitu koska (a) FBref/soccerdata palauttaa 403:n
kaikilla testatuilla klienteillä, (b) Render-ajossa ei haluta live-pullia
(sama konventio kuin international_results.csv, #79).

Kauden mittaan uudet tulokset tulevat SPL-fantasy-APIn `/api/fixtures/`
-feedistä — tätä CSV:tä päivitetään vain kun priorien historiaikkuna
siirretään (kerran kaudessa).

Joukkuenimet = ESPN:n englanninkieliset `displayName`-nimet; mappaus
fantasy-APIn short-koodeihin: `build_spl_phase0.py::SHORT_TO_MODEL`.
