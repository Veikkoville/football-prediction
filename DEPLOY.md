# Deployment-ohje: Streamlit Community Cloud

Vaiheittainen ohje sovelluksen viemiseen ilmaiseen Streamlit Community Cloudiin
salasanasuojauksen kanssa.

## Mitä tarvitset

- GitHub-tili (jos ei ole, rekisteröidy: https://github.com)
- Git asennettuna koneelle (testaa: `git --version` PowerShellissä)
- Tämä projekti toimivana lokaalisti

## Vaihe 1: Luo GitHub-repo

### 1.1 Mene https://github.com/new

Täytä:
- **Repository name**: `football-prediction` (tai mitä haluat)
- **Description**: vapaaehtoinen
- **Public** vai **Private**:
  - **Private** = suositeltu, koodi ei näy muille
  - **Public** = vaadittu Streamlit Cloud Free-tasolla! Jos haluat Private + Streamlit Cloud, tarvitset Streamlitin Connect-tilin
- **EI** rastia "Add README" / .gitignore / license -kohtiin (meillä on jo)

Klikkaa **Create repository**.

### 1.2 Linkitä paikallinen projekti GitHubiin

PowerShellissä projektikansiossa:

```powershell
cd C:\Users\vvsaa\Documents\football-prediction

# Initialisoi git jos ei jo ole
git init
git branch -M main

# Lisää kaikki tiedostot (paitsi .gitignoressa olevat)
git add .

# Tee ensimmäinen commit
git commit -m "Initial commit: football prediction app"

# Lisää GitHub remote (KORVAA YOUR_USERNAME ja REPONAME omillasi)
git remote add origin https://github.com/YOUR_USERNAME/football-prediction.git

# Pushaa GitHubiin
git push -u origin main
```

GitHub voi pyytää kirjautumaan: tee se selaimessa kun se avautuu.

### 1.3 Tarkista että salaisuudet eivät menneet GitHubiin

Avaa GitHubin repo selaimessa. Varmista että:
- ✅ `app.py`, `pages/`, `src/` ovat siellä
- ❌ `.env` EI näy missään
- ❌ `raw_data/` EI näy
- ❌ `.venv/` EI näy

Jos `.env` näkyy GitHubissa, se on **iso ongelma** — API-avain on julkinen. Toimi näin:
1. Mene `https://www.football-data.org/client/home`
2. Regeneroi API-avain (vanha kuolee)
3. Lisää uusi avain `.env`-tiedostoon paikallisesti
4. Aja: `git rm --cached .env && git commit -m "Remove .env" && git push`

## Vaihe 2: Streamlit Community Cloudiin

### 2.1 Rekisteröidy

Mene https://share.streamlit.io ja kirjaudu **GitHub-tilillä**.

### 2.2 Deploy uusi app

Klikkaa **"Create app"** → **"Deploy a public app from GitHub"**.

Täytä:
- **Repository**: valitse `YOUR_USERNAME/football-prediction`
- **Branch**: `main`
- **Main file path**: `app.py`
- **App URL**: (valinnainen) keksi nimi, esim. `myfootballapp`

### 2.3 Lisää API-avain salaisuutena

Klikkaa **"Advanced settings..."** ennen Deploy-nappia.

Kohdassa **Secrets** liitä TOML-formaatissa:

```toml
FOOTBALL_DATA_API_KEY = "4e793bdedcf64ed5b91a7d38ae157c99"
```

(Käytä omaa avaintasi, joka on `.env`-tiedostossasi.)

Klikkaa **"Save"**.

### 2.4 Deploy

Klikkaa **"Deploy"**. Streamlit asentaa requirements.txt:n paketteja
(~3-5 minuuttia ensimmäisellä kerralla).

Kun se on valmis, näet sovelluksen toimivana selaimessa osoitteessa
`https://[appname]-[hash].streamlit.app`.

## Vaihe 3: Lisää salasanasuojaus

### 3.1 App-asetuksiin

Mene https://share.streamlit.io → klikkaa appiasi → **Settings** (oikeassa yläkulmassa).

### 3.2 Sharing-välilehti

Valitse:
- **"Only specific people can view this app"**

Tämä vaatii vierailijalta GitHub-tilin tai sähköpostin sallitusta listasta.

**Lisää sähköpostit** jotka saavat katsoa appia (vähintään oma sähköpostisi).

Tai jos haluat URL+salasana-tyylisen ratkaisun: katso vaihtoehto B alla.

## Vaihe 4: Päivitysten tekeminen

Kun haluat päivittää sovellusta:

```powershell
# 1. Tee muutoksia paikallisesti, testaa: streamlit run app.py
# 2. Commit ja push GitHubiin:
git add .
git commit -m "Kuvaus muutoksesta"
git push

# 3. Streamlit Cloud havaitsee push:n ja redeployaa automaattisesti (~30s)
```

Voit seurata deploymentia https://share.streamlit.io:ssa.

## Vianetsintä

### "Module not found" -virhe pilvessä

`requirements.txt` ei sisällä jotain tarvittua. Lisää puuttuva paketti, push ja redeploy.

### App kaatuu RAM-rajoissa (1 GB)

Vältä: 4 kautta + Optuna + ensemble + kalibrointi yhdessä. Käytä `nopea_tila` togglea
tai vähemmän kausia.

### .env-tiedosto vahingossa GitHubiin

```powershell
# Poista cachesta:
git rm --cached .env

# Varmista .gitignoressa:
echo ".env" >> .gitignore

# Commit:
git add .gitignore
git commit -m "Remove .env from tracking"
git push

# REGENEROI API-avain footballdata.orgissa! Vanha on jo paljastunut.
```

### SofaScore-live-sivu ei toimi pilvessä

Pilven palvelin-IP on Cloudflaren herkemmin blokkaama. Tämä on tunnettu rajoitus
— Live-sivu toimii vain lokaalisti.

## Vaihtoehto B: Streamlit-secret-tason salasana koodissa

Jos haluat URL+salasana-ratkaisun (kuka vaan voi avata URL:n, mutta tarvitsee
salasanan jatkaakseen), lisää tämä `app.py`:n alkuun:

```python
import streamlit as st
import hmac

def check_password():
    """Pyytaa salasanan ja palauttaa True jos oikea."""
    def password_entered():
        if hmac.compare_digest(
            st.session_state["password"],
            st.secrets.get("APP_PASSWORD", ""),
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "Salasana", type="password", on_change=password_entered, key="password"
    )
    if "password_correct" in st.session_state:
        st.error("Vaara salasana.")
    return False

if not check_password():
    st.stop()
```

Lisää myös `Secrets`-asetuksiin:
```toml
APP_PASSWORD = "valitse_salasana_tahan"
```

## Lisalukemista

- Streamlit Cloudin dokumentaatio: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Streamlit secrets: https://docs.streamlit.io/develop/concepts/connections/secrets-management
- Salasanasuojaus: https://docs.streamlit.io/knowledge-base/deploy/authentication-without-sso
