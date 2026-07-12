# Bot-signup guard: Before User Created -hook (QUEUE #60)

Supabase Edge Function joka hylkää bottisignupit palvelinpuolella ENNEN kuin
käyttäjä luodaan `auth.users`-tauluun. Ei client-muutoksia, ei riko yhtään
asennettua app-versiota (1.0.3/1.0.5/web).

## Miksi Edge Function eikä Render-endpoint

Supabasen HTTP-hookilla on **5 sekunnin kokonaisbudjetti** ja hook-virhe
**kaataa signup-pyynnön** (fail-closed Supabasen suunnasta). Render free-tier
cold start on 30–50 s → hook Renderissä rikkoisi signupit ajoittain. Edge
Function käynnistyy millisekunneissa samassa infrassa (free-tier 500K
kutsua/kk riittää ~ikuisesti tällä volyymilla).

## Päätöslogiikka (validation.mjs)

1. Syntaksitarkistus (löysä — MX-check tekee raskaan työn).
2. Disposable-domain-blocklist (mailinator.com yms., ~24 kpl).
3. MX-lookup DNS-over-HTTPS:llä (Cloudflare → Google-fallback, 1,5 s
   timeout/resolveri, tunnin TTL-cache):
   - NXDOMAIN (`gmail.comaa`) → **hylkää**
   - MX löytyy → salli
   - Ei MX:ää mutta A/AAAA → salli (RFC 5321 implicit MX)
   - Ei MX:ää eikä A:ta → **hylkää**
   - DoH ei vastaa / SERVFAIL molemmilta → **salli (fail-open)** — aitoja
     käyttäjiä ei koskaan blokata oman DNS-tarkistuksen häiriön takia.

Hylätty signup saa clientissä virheen
"This email address looks invalid or undeliverable…" — vanhat app-versiot
näyttävät sen normaalina signup-virheenä (ei crash).

## Testit

```
node --test supabase/functions/before-user-created/validation.test.mjs
```

14 testiä: mock-DoH-päätösmatriisi + live-kriteerit (gmail.comaa hylkyyn,
gmail.com läpi).

## 🔒 Deploy (GO-REQUIRED — Villen lupa)

Kaikki alla oleva koskee tuotanto-authia → ei ajeta ilman erillistä GO:ta.

1. `supabase login` + `supabase link --project-ref bhcgommvjlhqcktrbtxf`
2. Deploy ILMAN JWT-vahvistusta (Auth kutsuu webhook-allekirjoituksella):
   `supabase functions deploy before-user-created --no-verify-jwt`
3. Dashboard → Authentication → Hooks → **Before User Created** →
   HTTPS-hook → URL `https://bhcgommvjlhqcktrbtxf.supabase.co/functions/v1/before-user-created`
   → Generate secret → kopioi.
4. `supabase secrets set BEFORE_USER_CREATED_HOOK_SECRET="v1,whsec_..."`
5. Verify: signup rikkinäisellä domainilla (esim. `test@gmail.comaa`) →
   hylkäytyy; signup oikealla gmaililla → menee läpi; olemassaolevan
   käyttäjän LOGIN ei muutu (hook koskee vain user-luontia).

Rollback = poista hook-konfiguraatio dashboardista (funktio voi jäädä
deployattuna, sitä ei kutsuta).

## Ei kuulu tähän

- Olemassaolevien ~150 bottitunnuksen poisto (Villen erillinen tehtävä).
- Turnstile CAPTCHA (Polku B) — kestävämpi mutta vaatii pakotetun
  app-päivityksen; ks. cc-raportti 2026-07-12.
