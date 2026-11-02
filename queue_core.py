"""BRAWLIX matchmaking queue — pure pairing logic (standard library only).

The Godot client (scripts/autoloads/net_manager.gd) speaks exactly this
contract:

    POST /queue/join          {"pid","name","level","code","gap"} -> {"ticket"}
    GET  /queue/{ticket}      -> {"status":"waiting","gap":n}
                              | {"status":"matched","code","host","opponent"}
    POST /queue/{ticket}/cancel   {"pid"}
    POST /queue/{ticket}/widen    {"gap","pid"}

Pairing rules (the safety requirements, all enforced here):
  - one ticket per pid (a second join replaces the first — no double queue)
  - a pid is NEVER paired with itself (two tabs share one pid)
  - a ticket is single-use: matched tickets leave the pairing pool
  - two players pair only when |levelA - levelB| <= min(gapA, gapB), and gaps
    widen over time on the client (2 / 4 / 8) — near levels first
  - tickets that stop being polled for TICKET_TTL seconds are dropped
    (disconnected players leave the queue automatically)
  - the longer-waiting player's relay room becomes the match room; the client
    that owns it is told host=true, the other is told to join that code
"""

import re
import threading
import time

TICKET_TTL_S = 30.0      # a ticket dies when its client stops polling this long
MATCHED_TTL_S = 120.0    # matched tickets linger so both clients read the result
MAX_GAP = 16
MAX_NAME = 24

_PID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
_CODE_RE = re.compile(r"^[0-9]{4}$")


class Ticket:
    __slots__ = ("ticket", "pid", "name", "level", "gap", "code",
                 "created_at", "last_seen", "match")

    def __init__(self, ticket, pid, name, level, gap, code, now):
        self.ticket = ticket
        self.pid = pid
        self.name = name
        self.level = level
        self.gap = gap
        self.code = code
        self.created_at = now
        self.last_seen = now
        self.match = None   # {"code": ..., "host": bool, "opponent": {...}}


def validate_pid(pid) -> bool:
    return isinstance(pid, str) and bool(_PID_RE.match(pid))


def validate_code(code) -> bool:
    return isinstance(code, str) and bool(_CODE_RE.match(code))


def clean_name(name) -> str:
    if not isinstance(name, str):
        return "OYUNCU"
    n = "".join(ch for ch in name.strip() if ch.isprintable())[:MAX_NAME].strip()
    return n if n else "OYUNCU"


def clamp_int(value, lo, hi, default):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


class MatchQueue:
    """In-memory ticket board. One process (uvicorn's default) only."""

    def __init__(self, ticket_factory=None):
        self._lock = threading.RLock()
        self._tickets = {}     # ticket id -> Ticket
        self._by_pid = {}      # pid -> ticket id
        self._next_id = 0
        self._factory = ticket_factory or self._make_ticket_id

    # -- ids ------------------------------------------------------------------
    def _make_ticket_id(self) -> str:
        self._next_id += 1
        return "t%08x%04x" % (self._next_id, int(time.time()) & 0xFFFF)

    # -- stats ----------------------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            waiting = sum(1 for t in self._tickets.values() if t.match is None)
            matched = len(self._tickets) - waiting
            return {"waiting": waiting, "matched": matched}

    # -- lifecycle --------------------------------------------------------------
    def sweep(self, now: float) -> int:
        """Drop silent tickets (disconnected players) + stale matched info."""
        with self._lock:
            dead = []
            for tid, t in self._tickets.items():
                ttl = MATCHED_TTL_S if t.match is not None else TICKET_TTL_S
                if now - t.last_seen > ttl:
                    dead.append(tid)
            for tid in dead:
                t = self._tickets.pop(tid)
                if self._by_pid.get(t.pid) == tid:
                    del self._by_pid[t.pid]
            return len(dead)

    def join(self, pid, name, level, gap, code, now=None) -> str:
        now = time.time() if now is None else now
        with self._lock:
            self.sweep(now)
            old = self._by_pid.get(pid)
            if old is not None:
                self._tickets.pop(old, None)   # one ticket per player, ever
                del self._by_pid[pid]
            tid = self._factory()
            t = Ticket(tid, pid, clean_name(name),
                       clamp_int(level, 0, 999999, 0),
                       clamp_int(gap, 1, MAX_GAP, 1), code, now)
            self._tickets[tid] = t
            self._by_pid[pid] = tid
            self._try_pair(t, now)
            return tid

    def status(self, ticket, now=None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            self.sweep(now)
            t = self._tickets.get(ticket)
            if t is None:
                return {"status": "expired"}
            t.last_seen = now
            if t.match is not None:
                m = t.match
                return {"status": "matched", "ticket": ticket, "code": m["code"],
                        "host": m["host"], "opponent": m["opponent"]}
            self._try_pair(t, now)
            if t.match is not None:
                m = t.match
                return {"status": "matched", "ticket": ticket, "code": m["code"],
                        "host": m["host"], "opponent": m["opponent"]}
            return {"status": "waiting", "ticket": ticket, "gap": t.gap}

    def widen(self, ticket, pid, gap, now=None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            self.sweep(now)
            t = self._tickets.get(ticket)
            if t is None or t.match is not None or t.pid != pid:
                return False
            t.gap = clamp_int(gap, 1, MAX_GAP, t.gap)
            t.last_seen = now
            self._try_pair(t, now)
            return True

    def cancel(self, ticket, pid, now=None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            self.sweep(now)
            t = self._tickets.get(ticket)
            if t is None or t.pid != pid:
                return False
            del self._tickets[ticket]
            if self._by_pid.get(pid) == ticket:
                del self._by_pid[pid]
            return True

    # -- pairing ----------------------------------------------------------------
    def _try_pair(self, t: Ticket, now: float) -> None:
        if t.match is not None:
            return
        # oldest first: the player who waited longest hosts the room
        for other in sorted(self._tickets.values(), key=lambda x: x.created_at):
            if other is t or other.match is not None:
                continue
            if other.pid == t.pid:
                continue   # a player can never meet themselves
            if abs(t.level - other.level) <= min(t.gap, other.gap):
                host, guest = (other, t) if other.created_at <= t.created_at \
                    else (t, other)
                host_info = {"name": host.name, "level": host.level}
                guest_info = {"name": guest.name, "level": guest.level}
                host.match = {"code": host.code, "host": True,
                              "opponent": guest_info}
                guest.match = {"code": host.code, "host": False,
                               "opponent": host_info}
                return
