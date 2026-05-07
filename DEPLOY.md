# Deployment guide: Streamlit Community Cloud

Step-by-step guide for deploying the app to free Streamlit Community Cloud
with password protection.

## What you need

- A GitHub account (if not, sign up at https://github.com)
- Git installed on your computer (test: `git --version` in PowerShell)
- This project working locally

## Step 1: Create a GitHub repository

### 1.1 Go to https://github.com/new

Fill in:
- **Repository name**: `football-prediction` (or whatever you prefer)
- **Description**: optional
- **Public** vs **Private**:
  - **Private** = recommended, code stays hidden
  - **Public** = required on Streamlit Cloud Free! For Private + Streamlit Cloud
    you need a Streamlit Connect account
- **Do NOT** check "Add README" / .gitignore / license (we already have these)

Click **Create repository**.

### 1.2 Link your local project to GitHub

In PowerShell, in your project folder:

```powershell
cd C:\Users\vvsaa\Documents\football-prediction

# Initialize git if it isn't already
git init
git branch -M main

# Add all files (except those in .gitignore)
git add .

# Make the first commit
git commit -m "Initial commit: football prediction app"

# Add GitHub remote (REPLACE YOUR_USERNAME and REPONAME with yours)
git remote add origin https://github.com/YOUR_USERNAME/football-prediction.git

# Push to GitHub
git push -u origin main
```

GitHub may ask you to log in: do it in the browser when it opens.

### 1.3 Verify that secrets did NOT go to GitHub

Open your repo in the browser. Confirm:
- ✅ `app.py`, `pages/`, `src/` are there
- ❌ `.env` is NOT visible anywhere
- ❌ `raw_data/` is NOT visible
- ❌ `.venv/` is NOT visible

If `.env` is visible on GitHub, that's a **big problem** — your API key is public.
Do this:
1. Go to `https://www.football-data.org/client/home`
2. Regenerate the API key (the old one dies)
3. Add the new key to your local `.env` file
4. Run: `git rm --cached .env && git commit -m "Remove .env" && git push`

## Step 2: Streamlit Community Cloud

### 2.1 Sign up

Go to https://share.streamlit.io and sign in with **your GitHub account**.

### 2.2 Deploy a new app

Click **"Create app"** → **"Deploy a public app from GitHub"**.

Fill in:
- **Repository**: choose `YOUR_USERNAME/football-prediction`
- **Branch**: `main`
- **Main file path**: `app.py`
- **App URL**: (optional) pick a name, e.g. `myfootballapp`

### 2.3 Add the API key as a secret

Click **"Advanced settings..."** before pressing Deploy.

Under **Secrets**, paste in TOML format:

```toml
FOOTBALL_DATA_API_KEY = "4e793bdedcf64ed5b91a7d38ae157c99"
```

(Use your own key, the one in your `.env` file.)

Click **"Save"**.

### 2.4 Deploy

Click **"Deploy"**. Streamlit will install the packages from requirements.txt
(~3-5 minutes the first time).

When done, you'll see the app working in the browser at
`https://[appname]-[hash].streamlit.app`.

## Step 3: Add password protection

### 3.1 Open app settings

Go to https://share.streamlit.io → click your app → **Settings** (top-right).

### 3.2 Sharing tab

Choose:
- **"Only specific people can view this app"**

This requires the visitor to have a GitHub account or an email address from the
allow list.

**Add the emails** that are allowed to view the app (at least your own).

Or for URL+password protection, see option B below.

## Step 4: Making updates

When you want to update the app:

```powershell
# 1. Make changes locally, test: streamlit run app.py
# 2. Commit and push to GitHub:
git add .
git commit -m "Description of change"
git push

# 3. Streamlit Cloud detects the push and redeploys automatically (~30s)
```

You can monitor the deployment at https://share.streamlit.io.

## Troubleshooting

### "Module not found" error in cloud

`requirements.txt` is missing something. Add the missing package, push, redeploy.

### App crashes due to RAM (1 GB limit)

Avoid: 4 seasons + Optuna + ensemble + calibration in one go. Use the
`Fast mode` toggle or fewer seasons.

### .env file accidentally pushed to GitHub

```powershell
# Remove from cache:
git rm --cached .env

# Make sure it's in .gitignore:
echo ".env" >> .gitignore

# Commit:
git add .gitignore
git commit -m "Remove .env from tracking"
git push

# REGENERATE the API key on footballdata.org! The old one is exposed.
```

### SofaScore live page doesn't work in the cloud

The cloud server's IP is blocked more aggressively by Cloudflare. This is a
known limitation — the Live page only works locally.

## Option B: Streamlit-secret-level password in code

If you want a URL+password approach (anyone can open the URL, but they need a
password to continue), add this near the top of `app.py`:

```python
import streamlit as st
import hmac

def check_password():
    """Asks for the password and returns True if correct."""
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
        "Password", type="password", on_change=password_entered, key="password"
    )
    if "password_correct" in st.session_state:
        st.error("Wrong password.")
    return False

if not check_password():
    st.stop()
```

Also add to **Secrets**:
```toml
APP_PASSWORD = "choose_a_password_here"
```

## Further reading

- Streamlit Cloud docs: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Streamlit secrets: https://docs.streamlit.io/develop/concepts/connections/secrets-management
- Password protection: https://docs.streamlit.io/knowledge-base/deploy/authentication-without-sso
