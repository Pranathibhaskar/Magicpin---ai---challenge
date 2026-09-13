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


# Prevent sending the same logical event repeatedly.
sent_suppressions: set[str] = set()

# Track the last message generated for each conversation.
last_messages: dict[str, str] = {}


def get_payload(scope: str, context_id: str | None) -> dict[str, Any]:
    if not context_id:
        return {}

    stored = contexts.get((scope, context_id))
    if not stored:
        return {}

    return stored.get("payload", {})


def parse_time(value: str | None):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def get_merchant_name(merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity") or {}

    return (
        identity.get("name")
        or merchant.get("name")
        or merchant.get("merchant_name")
        or merchant.get("business_name")
        or merchant.get("display_name")
        or "there"
    )


def get_customer_name(customer: dict[str, Any]) -> str:
    return (
        customer.get("name")
        or customer.get("customer_name")
        or customer.get("display_name")
        or "the customer"
    )


def humanize_kind(kind: str) -> str:
    return kind.replace("_", " ").strip().capitalize()


def find_digest_item(category: dict[str, Any], item_id: str | None) -> dict[str, Any] | None:
    """Find a category digest item across supported payload shapes."""
    if not item_id or not isinstance(category, dict):
        return None

    digest = category.get("digest")
    if digest is None and isinstance(category.get("category"), dict):
        digest = category["category"].get("digest")

    if isinstance(digest, dict):
        digest = digest.get("items") or digest.get("digest") or []

    if not isinstance(digest, list):
        return None

    for item in digest:
        if isinstance(item, dict) and str(item.get("id")) == str(item_id):
            return item

    return None


def compose_proactive_message(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
    customer: dict[str, Any],
) -> tuple[str, str, str, list[str]]:
    """
    Deterministic first-pass composer.

    Returns:
        body, cta, template_name, template_params
    """

    kind = str(trigger.get("kind", "update"))
    payload = trigger.get("payload") or {}

    merchant_name = get_merchant_name(merchant)

    category_name = (
        merchant.get("category_slug")
        or category.get("slug")
        or payload.get("category")
        or "your category"
    )

    # Common useful facts from merchant context.
    signals = merchant.get("signals") or {}
    performance = merchant.get("performance") or {}
    offers = merchant.get("offers") or []

    # Some datasets use lists instead of dictionaries.
    signal_text = ", ".join(map(str, signals)) if isinstance(signals, list) else ""
    if isinstance(signals, dict):
        signal_text = ", ".join(
            f"{k}: {v}" for k, v in signals.items()
        )

    # ---- Trigger-specific routing ----

    if kind == "research_digest":
        top_item = payload.get("top_item_id") or payload.get("headline")

        # Look up the full research item from the category digest.
        digest_item = find_digest_item(category, top_item)

        if digest_item:
            title = digest_item.get("title")
            source = digest_item.get("source")
            actionable = digest_item.get("actionable")

            body_parts = [f"{merchant_name}, {title}."]

            if source:
                body_parts.append(f"Source: {source}.")

            if actionable:
                body_parts.append(f"{actionable}.")

            body_parts.append(
                "Want me to pull out the practical takeaway for your clinic?"
            )

            body = " ".join(body_parts)

            return (
                body,
                "open_ended",
                "vera_research_digest_v2",
                [merchant_name, str(title or top_item)],
            )

        body = (
            f"{merchant_name}, there's a new {category_name}-relevant update "
            "worth a look. Want me to pull out the practical takeaway?"
        )

        return (
            body,
            "open_ended",
            "vera_research_digest_v2",
            [merchant_name, str(top_item or category_name)],
        )

    if kind == "perf_dip":
        calls = performance.get("calls")
        delta_7d = performance.get("delta_7d") or {}
        calls_pct = delta_7d.get("calls_pct")

        if calls is not None and calls_pct is not None:
            drop_pct = abs(calls_pct) * 100

            body = (
                f"{merchant_name}, calls are down {drop_pct:.0f}% this week — "
                f"{calls} calls in the current 30-day window. "
                "I'd start by fixing the offer gap first. "
                f"Want me to draft a {category_name} offer you can review?"
            )

            return (
                body,
                "open_ended",
                "vera_perf_dip_v2",
                [merchant_name, f"{calls}", f"{drop_pct:.0f}%"],
            )

        body = (
            f"{merchant_name}, there's a recent performance dip. "
            "Want me to show you the specific signal and suggest what to fix first?"
        )

        return (
            body,
            "open_ended",
            "vera_perf_dip_v2",
            [merchant_name],
        )

    if kind == "renewal_due":
        body = (
            f"{merchant_name}, your renewal is coming up. "
            f"I can help you review what you're currently getting and the simplest next step. "
            f"Want me to walk you through it?"
        )

        return (
            body,
            "open_ended",
            "vera_renewal_due_v1",
            [merchant_name],
        )

    if kind in {"active_planning_intent", "join_intent", "campaign_intent"}:
        body = (
            f"{merchant_name}, looks like you're ready to move ahead. "
            f"I can help with the next step now rather than making you go through more questions. "
            f"Shall I start?"
        )

        return (
            body,
            "yes_stop",
            "vera_intent_handoff_v1",
            [merchant_name],
        )

    if kind == "supply_alert":
        headline = payload.get("headline") or payload.get("alert") or "a supply update"

        body = (
            f"{merchant_name}, there's a time-sensitive supply update: {headline}. "
            f"I can help you figure out whether it affects your business. Want me to check?"
        )

        return (
            body,
            "open_ended",
            "vera_supply_alert_v1",
            [merchant_name, str(headline)],
        )

    if kind == "regulation_change":
        top_item_id = payload.get("top_item_id")
        digest_item = find_digest_item(category, top_item_id)

        if digest_item:
            headline = digest_item.get("title") or "a regulatory update"
            source = digest_item.get("source")
            actionable = digest_item.get("actionable")

            body_parts = [f"{merchant_name}, {headline}."]
            if source:
                body_parts.append(f"Source: {source}.")
            if actionable:
                body_parts.append(f"{actionable}.")
            body_parts.append(
                "Want me to summarize what actually matters for your clinic?"
            )

            body = " ".join(body_parts)

            return (
                body,
                "open_ended",
                "vera_regulation_update_v2",
                [merchant_name, str(headline)],
            )

        headline = (
            payload.get("headline")
            or payload.get("change")
            or "a regulatory update"
        )

        body = (
            f"{merchant_name}, there's a new regulatory update that may affect "
            f"{category_name}: {headline}. "
            f"Want me to summarize what actually matters for you?"
        )

        return (
            body,
            "open_ended",
            "vera_regulation_update_v2",
            [merchant_name, str(headline)],
        )

    if kind == "recall_due":
        customer_name = get_customer_name(customer)

        body = (
            f"{merchant_name}, {customer_name} appears to be due for a follow-up. "
            f"I can help you review the reminder details before you reach out. "
            f"Want me to show them?"
        )

        return (
            body,
            "open_ended",
            "vera_recall_due_v1",
            [merchant_name, customer_name],
        )

    if kind == "chronic_refill_due":
        customer_name = get_customer_name(customer)

        body = (
            f"{merchant_name}, {customer_name} may be due for a refill-related follow-up. "
            f"I can help you prepare the reminder. Want me to?"
        )

        return (
            body,
            "open_ended",
            "vera_refill_due_v1",
            [merchant_name, customer_name],
        )

    if kind == "dormant_with_vera":
        body = (
            f"{merchant_name}, I spotted an opportunity worth revisiting. "
            f"I can suggest one concrete thing based on your current account rather than sending a generic offer. "
            f"Want to see it?"
        )

        return (
            body,
            "open_ended",
            "vera_reengagement_v1",
            [merchant_name],
        )

    # ---- Safe generic fallback ----

    body = (
        f"{merchant_name}, I have a {humanize_kind(kind).lower()} update "
        f"that looks relevant to your {category_name} business. "
        f"Want me to show you the specific detail?"
    )

    return (
        body,
        "open_ended",
        "vera_contextual_update_v1",
        [merchant_name, category_name, kind],
    )


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []

    # Process highest-urgency triggers first.
    candidates = []

    for trigger_id in body.available_triggers:
        trigger = get_payload("trigger", trigger_id)

        if not trigger:
            continue

        urgency = int(trigger.get("urgency", 1) or 1)

        candidates.append(
            (urgency, trigger_id, trigger)
        )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    for urgency, trigger_id, trigger in candidates:

        # Don't exceed the judge's 20-action-per-tick limit.
        if len(actions) >= 20:
            break

        # Respect trigger expiry.
        expires_at = parse_time(trigger.get("expires_at"))

        current_time = parse_time(body.now)

        if expires_at and current_time and current_time > expires_at:
            continue

        suppression_key = (
            trigger.get("suppression_key")
            or trigger_id
        )

        # Deduplicate repeated ticks.
        if suppression_key in sent_suppressions:
            continue

        merchant_id = trigger.get("merchant_id")
        customer_id = trigger.get("customer_id")

        merchant = get_payload("merchant", merchant_id)
        customer = get_payload("customer", customer_id)

        category_slug = (
            merchant.get("category_slug")
            or (trigger.get("payload") or {}).get("category")
        )

        category = get_payload("category", category_slug)

        body_text, cta, template_name, template_params = (
            compose_proactive_message(
                trigger=trigger,
                merchant=merchant,
                category=category,
                customer=customer,
            )
        )

        # Never repeat the exact same generated body.
        if body_text in last_messages.values():
            continue

        conversation_id = (
            f"conv_{trigger_id}_{len(actions) + 1}"
        )

        send_as = (
            "merchant_on_behalf"
            if customer_id
            else "vera"
        )

        rationale = (
            f"Selected active trigger '{trigger.get('kind', 'unknown')}' "
            f"with urgency {urgency}; composed from the available "
            f"merchant, category"
        )

        if customer_id:
            rationale += ", and customer context"

        rationale += " without inventing unavailable facts."

        action = {
            "conversation_id": conversation_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trigger_id,
            "template_name": template_name,
            "template_params": template_params,
            "body": body_text,
            "cta": cta,
            "suppression_key": suppression_key,
            "rationale": rationale,
        }

        actions.append(action)

        sent_suppressions.add(suppression_key)
        last_messages[conversation_id] = body_text

    return {
        "actions": actions
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


def is_auto_reply(message: str) -> bool:
    text = message.lower().strip()

    markers = [
        "thank you for contacting",
        "thanks for contacting",
        "we have received your message",
        "our team will get back",
        "will get back to you shortly",
        "this is an automated",
        "automatic reply",
        "office hours",
        "working hours",
        "please leave a message",
    ]

    return any(marker in text for marker in markers)


def is_negative(message: str) -> bool:
    text = message.lower().strip()

    negatives = [
        "not interested",
        "no thanks",
        "no thank you",
        "don't want",
        "do not want",
        "stop",
        "remove me",
        "unsubscribe",
        "not required",
        "not needed",
        "leave it",
    ]

    return any(phrase in text for phrase in negatives)


def is_positive_intent(message: str) -> bool:
    text = message.lower().strip()

    positives = [
        "yes",
        "okay",
        "ok",
        "sure",
        "go ahead",
        "let's do it",
        "lets do it",
        "do it",
        "send it",
        "please do",
        "please start",
        "i want to",
        "i'd like to",
        "interested",
    ]

    return any(
        text == phrase or phrase in text
        for phrase in positives
    )


def is_question(message: str) -> bool:
    text = message.strip()

    return (
        "?" in text
        or text.lower().startswith(
            (
                "what ",
                "how ",
                "when ",
                "where ",
                "why ",
                "can ",
                "could ",
                "is ",
                "do ",
            )
        )
    )


@app.post("/v1/reply")
async def reply(body: ReplyBody):

    history = conversations.setdefault(
        body.conversation_id,
        [],
    )

    history.append({
        "from": body.from_role,
        "message": body.message,
        "received_at": body.received_at,
        "turn_number": body.turn_number,
    })

    message = body.message.strip()

    # 1. Auto-reply detection.
    if is_auto_reply(message):
        previous_auto_replies = sum(
            1
            for turn in history
            if turn["from"] != "vera"
            and is_auto_reply(turn["message"])
        )

        if previous_auto_replies >= 2:
            return {
                "action": "end",
                "rationale": (
                    "Detected repeated automated replies; "
                    "ending instead of wasting conversational turns."
                ),
            }

        return {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": (
                "Detected an automated WhatsApp response; "
                "backing off rather than treating it as merchant intent."
            ),
        }

    # 2. Explicit opt-out / rejection.
    if is_negative(message):
        return {
            "action": "end",
            "rationale": (
                "Merchant/customer explicitly declined; "
                "ending respectfully."
            ),
        }

    # 3. Explicit positive intent.
    if is_positive_intent(message):
        return {
            "action": "send",
            "body": (
                "Absolutely — let's move ahead. "
                "I'll take the next step from here."
            ),
            "cta": "open_ended",
            "rationale": (
                "Explicit positive intent detected; "
                "switching directly from qualification to action."
            ),
        }

    # 4. Questions deserve an answer rather than another pitch.
    if is_question(message):
        return {
            "action": "send",
            "body": (
                "Good question. Let me use the information "
                "I have for your account and give you the most "
                "relevant answer rather than guessing."
            ),
            "cta": "open_ended",
            "rationale": (
                "Detected a question; preserving the user's intent "
                "instead of forcing another promotional message."
            ),
        }

    # 5. Otherwise, acknowledge once and give the merchant space.
    return {
        "action": "wait",
        "wait_seconds": 900,
        "rationale": (
            "No clear action intent detected; avoiding unnecessary "
            "follow-up pressure."
        ),
    }
