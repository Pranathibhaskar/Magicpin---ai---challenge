import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI()

START_TIME = time.time()

# Context storage:
# (scope, context_id) -> {"version": int, "payload": dict}
contexts: dict[tuple[str, str], dict[str, Any]] = {}

# Conversation storage:
# conversation_id -> list of turns
conversations: dict[str, list[dict[str, Any]]] = {}


# -------------------------
# Health check
# -------------------------

@app.get("/v1/healthz")
async def healthz():
    counts = {
        "category": 0,
        "merchant": 0,
        "customer": 0,
        "trigger": 0,
    }

    for (scope, _), _value in contexts.items():
        if scope in counts:
            counts[scope] += 1

    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts,
    }


# -------------------------
# Bot metadata
# -------------------------

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Pranathi",
        "team_members": ["Pranathi"],
        "model": "TBD",
        "approach": "context-aware rule-based composer with LLM assistance",
        "contact_email": "TBD",
        "version": "0.1.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


# -------------------------
# Context endpoint
# -------------------------

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


@app.post("/v1/context")
async def push_context(body: ContextBody):
    key = (body.scope, body.context_id)

    current = contexts.get(key)

    if current and current["version"] >= body.version:
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": current["version"],
        }

    contexts[key] = {
        "version": body.version,
        "payload": body.payload,
    }

    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


# -------------------------
# Tick endpoint
# -------------------------

class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    # Composer logic comes here.
    return {
        "actions": []
    }


# -------------------------
# Reply endpoint
# -------------------------

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conversations.setdefault(body.conversation_id, []).append({
        "from": body.from_role,
        "message": body.message,
        "received_at": body.received_at,
        "turn_number": body.turn_number,
    })

    # Reply logic comes here.
    return {
        "action": "wait",
        "wait_seconds": 0,
        "rationale": "Reply handling not implemented yet.",
    }