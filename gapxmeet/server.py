"""
GapX Meet — Backend Server
===========================
FastAPI + python-socketio server that powers:
  - Room-based WebRTC signaling (offer/answer/ICE relay)
  - TURN/STUN credential distribution (for real-world NAT traversal)
  - Peer presence (join/leave, peer list)
  - Live chat relay
  - Live translation broadcast relay between participants
  - Serves the frontend (static/index.html)

Run locally:
    pip install -r requirements.txt
    python server.py

Then open http://localhost:8000 in Chrome or Edge.

──────────────────────────────────────────────────────────────
TURN SERVER SETUP (required for reliable real-world calls)
──────────────────────────────────────────────────────────────
WebRTC needs a TURN server to connect users behind restrictive
NATs/firewalls (corporate networks, some mobile carriers, etc).
STUN alone is NOT enough for production use — without TURN, a
meaningful fraction of real calls will simply fail to connect.

Configure via environment variables:

  Option A — static TURN credentials (e.g. a managed provider
  like Twilio, Metered, Xirsys, or your own coturn with a fixed
  user/pass):
    TURN_URLS=turn:your.turn.server:3478,turns:your.turn.server:5349
    TURN_USERNAME=myuser
    TURN_PASSWORD=mypassword

  Option B — coturn with shared-secret (time-limited HMAC
  credentials, recommended for self-hosted coturn):
    TURN_URLS=turn:your.turn.server:3478
    TURN_SECRET=your-coturn-static-auth-secret

  If no TURN_* variables are set, the server falls back to
  STUN-only (works on simple networks, fails on many real ones).

  Free/cheap TURN options to get started: Twilio Network Traversal
  Service, Metered.ca TURN, or self-hosted coturn (~$5/mo VPS).
"""

import hashlib
import hmac
import os
import time

import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ──────────────────────────────────────────────────────────────
# TURN / STUN configuration (see module docstring above)
# ──────────────────────────────────────────────────────────────
TURN_URLS = [u.strip() for u in os.environ.get("TURN_URLS", "").split(",") if u.strip()]
TURN_USERNAME = os.environ.get("TURN_USERNAME", "")
TURN_PASSWORD = os.environ.get("TURN_PASSWORD", "")
TURN_SECRET = os.environ.get("TURN_SECRET", "")
TURN_TTL_SECONDS = int(os.environ.get("TURN_TTL_SECONDS", "3600"))

STUN_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
]


def get_ice_servers() -> list[dict]:
    """
    Build the iceServers list for RTCPeerConnection.

    - Always includes public STUN servers (free, fine for simple networks).
    - Adds TURN servers if configured, using either static credentials
      or coturn-style time-limited HMAC credentials (preferred — these
      expire automatically so they're safe to hand to the browser).
    """
    servers = list(STUN_SERVERS)
    if not TURN_URLS:
        return servers

    if TURN_SECRET:
        # coturn shared-secret scheme: username is "<expiry-timestamp>",
        # password is base64(HMAC-SHA1(secret, username)).
        expiry = int(time.time()) + TURN_TTL_SECONDS
        username = str(expiry)
        digest = hmac.new(TURN_SECRET.encode(), username.encode(), hashlib.sha1).digest()
        import base64
        password = base64.b64encode(digest).decode()
        servers.append({"urls": TURN_URLS, "username": username, "credential": password})
    elif TURN_USERNAME and TURN_PASSWORD:
        servers.append({"urls": TURN_URLS, "username": TURN_USERNAME, "credential": TURN_PASSWORD})
    else:
        # TURN_URLS set but no credentials — likely a misconfiguration,
        # but include anyway in case the TURN server allows anonymous access.
        servers.append({"urls": TURN_URLS})

    return servers


# ──────────────────────────────────────────────────────────────
# Socket.IO async server (CORS open so this can be hosted
# separately from the frontend if needed)
# ──────────────────────────────────────────────────────────────
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60,
)

app = FastAPI(title="GapX Meet Signaling Server")

# In-memory room state: { room_id: { sid: {name, lang, hearLang, init} } }
ROOMS: dict[str, dict[str, dict]] = {}
# Reverse index for O(1) lookup of which room a sid belongs to.
SID_ROOM: dict[str, str] = {}


def _room_peer_list(room_id: str, exclude_sid: str | None = None):
    """Return a list of peer-info dicts for a room, excluding a given sid."""
    peers = ROOMS.get(room_id, {})
    result = []
    for sid, info in peers.items():
        if sid == exclude_sid:
            continue
        result.append({"id": sid, **info})
    return result


@sio.event
async def connect(sid, environ):
    print(f"[connect] {sid}")


@sio.event
async def disconnect(sid):
    room_id = SID_ROOM.pop(sid, None)
    if room_id and room_id in ROOMS and sid in ROOMS[room_id]:
        info = ROOMS[room_id].pop(sid)
        await sio.emit(
            "peer-left",
            {"id": sid, "name": info.get("name")},
            room=room_id,
            skip_sid=sid,
        )
        if not ROOMS[room_id]:
            ROOMS.pop(room_id, None)
        print(f"[disconnect] {sid} left room {room_id}")
    print(f"[disconnect] {sid}")


@sio.event
async def join(sid, data):
    """
    data: { roomId, name, init, lang, hearLang }
    """
    room_id = str(data.get("roomId", "")).upper().strip()
    if not room_id:
        return

    # If this sid was previously in a different room (e.g. reconnect or
    # room switch without a full page reload), clean that up first.
    prev_room = SID_ROOM.get(sid)
    if prev_room and prev_room != room_id and prev_room in ROOMS:
        ROOMS[prev_room].pop(sid, None)
        await sio.leave_room(sid, prev_room)
        if not ROOMS[prev_room]:
            ROOMS.pop(prev_room, None)

    await sio.enter_room(sid, room_id)
    SID_ROOM[sid] = room_id

    peer_info = {
        "name": data.get("name", "Guest"),
        "init": data.get("init", "G"),
        "lang": data.get("lang", "en-US"),
        "hearLang": data.get("hearLang", "en-US"),
    }
    ROOMS.setdefault(room_id, {})[sid] = peer_info

    # Send the new joiner the list of existing peers in the room
    await sio.emit("room-peers", _room_peer_list(room_id, exclude_sid=sid), to=sid)

    # Notify existing peers that a new participant joined
    await sio.emit(
        "peer-joined",
        {"id": sid, **peer_info},
        room=room_id,
        skip_sid=sid,
    )
    print(f"[join] {sid} -> room {room_id} ({peer_info['name']})")


@sio.event
async def offer(sid, data):
    """Relay a WebRTC SDP offer to a specific peer."""
    to_sid = data.get("to")
    if to_sid:
        await sio.emit("offer", {"from": sid, "offer": data.get("offer")}, to=to_sid)


@sio.event
async def answer(sid, data):
    """Relay a WebRTC SDP answer to a specific peer."""
    to_sid = data.get("to")
    if to_sid:
        await sio.emit("answer", {"from": sid, "answer": data.get("answer")}, to=to_sid)


@sio.event
async def ice(sid, data):
    """Relay an ICE candidate to a specific peer."""
    to_sid = data.get("to")
    if to_sid:
        await sio.emit("ice", {"from": sid, "candidate": data.get("candidate")}, to=to_sid)


@sio.event
async def chat(sid, data):
    """Broadcast a chat message to everyone else in the sender's room."""
    room_id = SID_ROOM.get(sid)
    if not room_id or room_id not in ROOMS or sid not in ROOMS[room_id]:
        return
    peer = ROOMS[room_id][sid]
    await sio.emit(
        "chat",
        {
            "name": data.get("name") or peer.get("name"),
            "init": data.get("init") or peer.get("init"),
            "text": data.get("text", ""),
        },
        room=room_id,
        skip_sid=sid,
    )


@sio.event
async def translation(sid, data):
    """Broadcast a live translation (original text + source language) to peers."""
    room_id = SID_ROOM.get(sid)
    if not room_id or room_id not in ROOMS or sid not in ROOMS[room_id]:
        return
    peer = ROOMS[room_id][sid]
    await sio.emit(
        "translation",
        {
            "from": data.get("from") or peer.get("name"),
            "fromLang": data.get("fromLang") or peer.get("lang"),
            "original": data.get("original", ""),
        },
        room=room_id,
        skip_sid=sid,
    )


# ──────────────────────────────────────────────────────────────
# HTTP routes
# ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "rooms": len(ROOMS),
        "participants": sum(len(p) for p in ROOMS.values()),
        "turn_configured": bool(TURN_URLS),
    }


@app.get("/ice-config")
async def ice_config():
    """
    Returns the iceServers list (STUN + TURN, if configured) for the
    frontend to use when creating RTCPeerConnections. Credentials are
    generated fresh (and time-limited, if using TURN_SECRET) on each
    request rather than baked into the frontend JS.
    """
    return {"iceServers": get_ice_servers()}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static assets (css/js/images if split out later)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Wrap the FastAPI app with the Socket.IO ASGI app
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="socket.io")


if __name__ == "__main__":
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000)
