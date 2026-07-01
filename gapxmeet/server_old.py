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

# Auto-create static directory if it doesn't exist
os.makedirs(STATIC_DIR, exist_ok=True)

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
    servers = list(STUN_SERVERS)
    if not TURN_URLS:
        return servers

    if TURN_SECRET:
        expiry = int(time.time()) + TURN_TTL_SECONDS
        username = str(expiry)
        digest = hmac.new(TURN_SECRET.encode(), username.encode(), hashlib.sha1).digest()
        import base64
        password = base64.b64encode(digest).decode()
        servers.append({"urls": TURN_URLS, "username": username, "credential": password})
    elif TURN_USERNAME and TURN_PASSWORD:
        servers.append({"urls": TURN_URLS, "username": TURN_USERNAME, "credential": TURN_PASSWORD})
    else:
        servers.append({"urls": TURN_URLS})

    return servers


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60,
)

app = FastAPI(title="GapX Meet Signaling Server")

ROOMS: dict[str, dict[str, dict]] = {}
SID_ROOM: dict[str, str] = {}


def _room_peer_list(room_id: str, exclude_sid: str | None = None):
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
    room_id = str(data.get("roomId", "")).upper().strip()
    if not room_id:
        return

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

    await sio.emit("room-peers", _room_peer_list(room_id, exclude_sid=sid), to=sid)

    await sio.emit(
        "peer-joined",
        {"id": sid, **peer_info},
        room=room_id,
        skip_sid=sid,
    )
    print(f"[join] {sid} -> room {room_id} ({peer_info['name']})")


@sio.event
async def offer(sid, data):
    to_sid = data.get("to")
    if to_sid:
        await sio.emit("offer", {"from": sid, "offer": data.get("offer")}, to=to_sid)


@sio.event
async def answer(sid, data):
    to_sid = data.get("to")
    if to_sid:
        await sio.emit("answer", {"from": sid, "answer": data.get("answer")}, to=to_sid)


@sio.event
async def ice(sid, data):
    to_sid = data.get("to")
    if to_sid:
        await sio.emit("ice", {"from": sid, "candidate": data.get("candidate")}, to=to_sid)


@sio.event
async def chat(sid, data):
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
    return {"iceServers": get_ice_servers()}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Wrap the FastAPI app with the Socket.IO ASGI app
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="socket.io")


if __name__ == "__main__":
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000)
