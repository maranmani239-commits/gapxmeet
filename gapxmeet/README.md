# GapX Meet — Real-Time AI Translation Video Meetings

A Google Meet–style video calling app with live speech-to-text, AI translation,
text-to-speech, chat, and downloadable meeting transcripts (PDF).

## Project structure

```
gapxmeet/
├── server.py          # FastAPI + Socket.IO backend (signaling, rooms, chat relay)
├── requirements.txt   # Python dependencies
└── static/
    ├── index.html        # Frontend (single-page app: UI, WebRTC, STT/TTS, translation)
    └── socket.io.min.js  # Socket.IO client, bundled locally (no CDN dependency)
```

The frontend loads `socket.io.min.js` from your own server first, falling
back to public CDNs only if that file is missing — so calls keep working
even if `cdn.socket.io` is blocked or slow on the network it's deployed to.

## What the Python backend does

`server.py` replaces the old hard-coded (and unreliable) signaling server.
It handles:

- **Room management** — players join a room by code; server tracks who's in each room
- **WebRTC signaling relay** — forwards SDP offers/answers and ICE candidates between peers
  so browsers can establish direct peer-to-peer audio/video connections
- **Presence** — notifies everyone when someone joins/leaves
- **Chat relay** — broadcasts chat messages to everyone in the room
- **Translation broadcast** — relays each speaker's live transcript so peers can
  translate it into their own "hear" language

The actual translation/STT/TTS happens **in the browser** (Web Speech API +
free public translation APIs), so the server stays lightweight.

## ⚠️ Before real-world use: set up a TURN server

STUN alone (the default) only works on simple networks. Without TURN,
calls will fail to connect for a meaningful fraction of real users —
corporate networks, some mobile carriers, and symmetric NATs all need it.

Set these environment variables before starting the server:

**Option A — your own coturn server (cheapest, ~$5/mo VPS):**
```bash
export TURN_URLS="turn:your.turn.server:3478"
export TURN_SECRET="your-coturn-static-auth-secret"
```
The server automatically generates time-limited HMAC credentials per
session (1 hour by default, configurable via `TURN_TTL_SECONDS`) — this
is the recommended, more secure option since credentials expire.

**Option B — a managed TURN provider (Twilio, Metered.ca, Xirsys, etc.):**
```bash
export TURN_URLS="turn:provider-host:3478,turns:provider-host:5349"
export TURN_USERNAME="your-username"
export TURN_PASSWORD="your-password"
```

Without either of these set, the app still runs and works locally /
on friendly networks, but falls back to STUN-only.

Check `GET /ice-config` on your running server to confirm TURN is active
(`turn_configured: true` in `/health`).

## Setup & run locally

```bash
cd gapxmeet
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

Then open **http://localhost:8000** in **Chrome, Edge, or Brave**
(Safari/Firefox don't support the Web Speech API used for live voice translation).

> ⚠️ Voice translation requires a secure context (HTTPS) **or** localhost.
> `localhost` is treated as secure, so local testing works without HTTPS.

## Deploying

To deploy (Render, Railway, Fly.io, a VPS, etc.):

1. Push this folder to your host
2. Set the start command to:
   ```bash
   uvicorn server:asgi_app --host 0.0.0.0 --port $PORT
   ```
3. Make sure the deployment uses **HTTPS** (most platforms do this automatically) —
   required for microphone access and Web Speech API.
4. Open the deployed URL — the frontend automatically points its signaling
   connection at `location.origin`, so no extra config is needed.

## How a meeting works

1. **Home screen** — pick languages you **speak** and want to **hear**, then
   create or join a room (room code is shareable via link).
2. **In the meeting**:
   - Tap **🎤 Speak** — your speech is transcribed live (Web Speech API)
   - The transcript is translated into each listener's chosen "hear" language
     (via free Google Translate / MyMemory / LibreTranslate APIs, with fallback chain)
   - Translated text is read aloud (TTS) and shown in the transcript bar/sidebar
   - Camera, mic, screen share, chat, reactions, raise hand all work like Meet
3. **Leaving** — rate the meeting, then download a full **PDF transcript**
   (original + translated text, chat history) from the summary screen.

## Browser requirements

| Feature              | Requirement                          |
|----------------------|---------------------------------------|
| Video/audio calls    | Any modern browser (WebRTC)            |
| Live voice → text    | Chrome, Edge, or Brave (desktop/Android) |
| Translation          | Any browser (uses fetch to public APIs)|
| Text-to-speech       | Any browser (Web Speech API / Google TTS audio) |
| PDF transcript export| Any browser (print-to-PDF)             |

## Production readiness notes

This app is solid for personal use, demos, and small group calls once
TURN is configured (see above). Before treating it as a product for
unknown/public users, be aware of these remaining gaps:

- **Room state is in-memory** — restarting `server.py` or running
  multiple server instances loses all active rooms. For multi-instance
  deployments, move `ROOMS`/`SID_ROOM` to Redis.
- **Mesh topology, not SFU** — every participant connects directly to
  every other participant. This is fine for ~2-4 people; for larger
  group calls you'd want an SFU (LiveKit, mediasoup, Janus) instead of
  raw mesh WebRTC, since bandwidth/CPU cost grows with the square of
  participant count.
- **Free translation APIs** — Google Translate's public endpoint,
  MyMemory, and LibreTranslate are convenient but not guaranteed-uptime
  or rate-limit-free for production traffic. For guaranteed reliability
  at scale, swap in a paid translation API (Google Cloud Translate,
  DeepL, Azure Translator) in `doTranslate()`.
- **No auth** — anyone with a room code can join. Fine for trusted
  links; add real authentication if you need access control.
- **HTTPS is required** in production for microphone access and Web
  Speech API — most hosting platforms (Render, Railway, Fly.io) provide
  this automatically, but confirm it's enabled.
