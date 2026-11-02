"""BRAWLIX matchmaking server — the deployable shell around queue_core.

Endpoints (exactly what the game client calls):
    POST /queue/join           {"pid","name","level","code","gap"} -> {"ticket"}
    GET  /queue/{ticket}       -> waiting / matched payload
    POST /queue/{ticket}/cancel  {"pid"}
    POST /queue/{ticket}/widen   {"gap","pid"}
    GET  /health               -> {ok, waiting, matched}
    GET  /                     -> service banner (paste the URL in a browser
                                  to verify the deployment worked)

Run locally:  uvicorn main:app --host 0.0.0.0 --port 8000
Deploy:       see README.md (Render / Railway, single process, no database).
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import queue_core
from queue_core import MatchQueue, validate_code, validate_pid

app = FastAPI(title="brawlix-matchmaker", version="1.0.0")

# The game runs on play.tesana.ai and players' own browsers — every origin
# must be allowed (same policy as the relay's lobby preflight).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ONE process owns the in-memory queue (uvicorn's default). The handlers are
# async without awaits, so each request is atomic — two players joining at
# the same instant can never interleave inside the pairing code.
QUEUE = MatchQueue()


class JoinBody(BaseModel):
    pid: str = Field(min_length=8, max_length=64)
    name: str = Field(default="OYUNCU", max_length=64)
    level: int = Field(default=0, ge=0, le=999999)
    code: str = Field(min_length=4, max_length=4)
    gap: int = Field(default=1, ge=1, le=queue_core.MAX_GAP)


class PidBody(BaseModel):
    pid: str = Field(min_length=8, max_length=64)


class WidenBody(PidBody):
    gap: int = Field(ge=1, le=queue_core.MAX_GAP)


@app.get("/")
def root() -> dict:
    s = QUEUE.stats()
    return {"service": "brawlix-matchmaker", "ok": True, **s}


@app.get("/health")
def health() -> dict:
    s = QUEUE.stats()
    return {"ok": True, **s}


@app.post("/queue/join")
async def queue_join(body: JoinBody) -> dict:
    if not validate_pid(body.pid):
        raise HTTPException(status_code=422, detail="bad pid")
    if not validate_code(body.code):
        raise HTTPException(status_code=422, detail="bad room code")
    ticket = QUEUE.join(body.pid, body.name, body.level, body.gap, body.code)
    return {"ticket": ticket}


@app.get("/queue/{ticket}")
async def queue_status(ticket: str) -> dict:
    data = QUEUE.status(ticket)
    if data["status"] == "expired":
        raise HTTPException(status_code=404, detail="ticket expired")
    return data


@app.post("/queue/{ticket}/widen")
async def queue_widen(ticket: str, body: WidenBody) -> dict:
    if not validate_pid(body.pid):
        raise HTTPException(status_code=422, detail="bad pid")
    if not QUEUE.widen(ticket, body.pid, body.gap):
        raise HTTPException(status_code=404, detail="no such ticket")
    return {"ok": True, "gap": body.gap}


@app.post("/queue/{ticket}/cancel")
async def queue_cancel(ticket: str, body: PidBody) -> dict:
    if not validate_pid(body.pid):
        raise HTTPException(status_code=422, detail="bad pid")
    if not QUEUE.cancel(ticket, body.pid):
        raise HTTPException(status_code=404, detail="no such ticket")
    return {"ok": True}
