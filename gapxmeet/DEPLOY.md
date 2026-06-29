# 🚀 Deploy GapX Meet — Step by Step

Follow these steps exactly. Takes about 10–15 minutes.
Your app will be live at a free HTTPS link like: https://gapxmeet.up.railway.app

---

## Step 1 — Create a GitHub Account (if you don't have one)
Go to https://github.com and sign up for free.

---

## Step 2 — Upload your project to GitHub

1. Go to https://github.com/new
2. Repository name: `gapxmeet`
3. Set to **Public**
4. Click **Create repository**
5. On your computer, open Terminal (Mac/Linux) or Command Prompt (Windows)
6. Run these commands one by one:

```bash
cd gapxmeet          # go into your project folder
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/gapxmeet.git
git push -u origin main
```

Replace YOUR_USERNAME with your GitHub username.

---

## Step 3 — Deploy on Railway (free)

1. Go to https://railway.app
2. Click **Login with GitHub** — use the same GitHub account
3. Click **New Project**
4. Click **Deploy from GitHub repo**
5. Select your `gapxmeet` repository
6. Railway will detect it automatically and start deploying
7. Wait 2–3 minutes for the build to finish

---

## Step 4 — Get your live URL

1. In Railway, click your project
2. Click **Settings** → **Domains**
3. Click **Generate Domain**
4. You'll get a URL like: `https://gapxmeet-production.up.railway.app`

**That's your live app! Open it in Chrome and test it.**

---

## Step 5 — Set up TURN server (for reliable calls)

Without this, calls may fail on some networks. It's free to start.

1. Go to https://www.metered.ca/tools/openrelay/ 
2. Sign up for free
3. You'll get:
   - TURN URL (like: `turn:openrelay.metered.ca:80`)
   - Username
   - Password

4. In Railway, go to your project → **Variables** → Add these:
```
TURN_URLS = turn:openrelay.metered.ca:80,turns:openrelay.metered.ca:443
TURN_USERNAME = your-username-from-metered
TURN_PASSWORD = your-password-from-metered
```

5. Railway will auto-restart with TURN enabled.

---

## ✅ You're live!

Share your Railway URL with anyone to test GapX Meet.
For demo calls, use Chrome or Edge (required for voice translation).

---

## Troubleshooting

**Build fails?**
- Make sure all 4 files are in your repo: server.py, requirements.txt, Procfile, railway.json
- Check Railway build logs for the exact error

**Voice translation not working?**
- Must use Chrome or Edge browser
- Must be on HTTPS (Railway gives you this automatically)

**Calls not connecting?**
- Set up the TURN server (Step 5 above)
