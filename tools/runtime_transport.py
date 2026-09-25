#!/usr/bin/env python3
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import result_relay as rr


class TransportError(ValueError):
    pass


def _dt(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise TransportError(f"{label} must be a non-empty timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransportError(f"invalid {label}") from exc
    if dt.tzinfo is None:
        raise TransportError(f"{label} must be timezone-aware")
    return dt


def _obs_time(observation: dict[str, Any], key: str) -> datetime | None:
    value = observation.get(key)
    if value in (None, ""):
        return None
    return _dt(value, key)


def current_run_observed(ticket: dict[str, Any], observation: dict[str, Any]) -> bool:
    rr.validate_ticket(ticket)
    last_run = _obs_time(observation, "last_run_time")
    if last_run is None:
        return False
    not_before = _dt(ticket["scheduled_not_before"], "scheduled_not_before")
    return last_run >= not_before


def classify_observation(
    *,
    ticket: dict[str, Any],
    observation: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    """Classify one Scheduled Task observation without mutating canonical state."""
    rr.validate_ticket(ticket)
    now_dt = _dt(now, "now")
    not_before = _dt(ticket["scheduled_not_before"], "scheduled_not_before")
    deadline = _dt(ticket["relay_deadline_at"], "relay_deadline_at")
    prompt = observation.get("prompt")
    updated_at = observation.get("updated_at")

    if isinstance(prompt, str) and (
        prompt.startswith(rr.PREFIX)
        or prompt.startswith(rr.LEGACY_PREFIX_V2)
        or prompt.startswith(rr.LEGACY_PREFIX_V1)
    ):
        if not isinstance(updated_at, str) or not updated_at:
            return {
                "state": "relay-invalid",
                "reason": "relay metadata has no platform updated_at",
            }
        try:
            envelope = rr.validate_raw_relay(prompt, ticket=ticket)
            rr.validate_publication_time(ticket, updated_at)
        except rr.RelayError as exc:
            message = str(exc)
            stale_markers = (
                "binding mismatch",
                "unsupported relay schema_version for acceptance",
            )
            if "after relay_deadline_at" in message:
                return {"state": "late-relay", "reason": message}
            if any(marker in message for marker in stale_markers):
                return {"state": "relay-stale", "reason": message}
            return {"state": "relay-invalid", "reason": message}
        return {
            "state": "ready",
            "reason": "valid current-generation relay observed",
            "envelope": envelope,
            "transport_updated_at": updated_at,
        }

    if now_dt < not_before:
        return {"state": "awaiting-launch", "reason": "scheduled_not_before not reached"}

    ran = current_run_observed(ticket, observation)
    if now_dt <= deadline:
        if ran:
            return {
                "state": "awaiting-relay",
                "reason": "current delivery invocation observed; relay deadline still open",
            }
        return {
            "state": "awaiting-launch",
            "reason": "no current delivery invocation observed; relay deadline still open",
        }

    if ran:
        return {
            "state": "egress-miss",
            "reason": "current delivery invocation observed but no valid relay before deadline",
        }
    return {
        "state": "launch-miss",
        "reason": "no current delivery invocation observed before deadline",
    }


def recycle_quiescent_slots(pool: dict[str, Any], *, now: str) -> dict[str, Any]:
    now_dt = _dt(now, "now")
    out = copy.deepcopy(pool)
    for slot in out.get("slots", []):
        if slot.get("state") != "quiescent":
            continue
        quiescent_until = slot.get("quiescent_until")
        if not isinstance(quiescent_until, str) or not quiescent_until:
            raise TransportError("quiescent slot missing quiescent_until")
        if now_dt >= _dt(quiescent_until, "quiescent_until"):
            slot["state"] = "idle"
            slot["current_ticket"] = None
            slot["quiescent_until"] = None
    return out


def select_idle_slot(
    pool: dict[str, Any],
    *,
    now: str,
    avoid_slot_id: str | None = None,
) -> dict[str, Any]:
    normalized = recycle_quiescent_slots(pool, now=now)
    slots = [slot for slot in normalized.get("slots", []) if slot.get("state") == "idle"]
    if avoid_slot_id:
        preferred = [slot for slot in slots if slot.get("slot_id") != avoid_slot_id]
        if preferred:
            slots = preferred
    if not slots:
        raise TransportError("no idle Scheduled Runtime slot available")
    slots.sort(key=lambda slot: str(slot.get("slot_id", "")))
    return copy.deepcopy(slots[0])


def allocate_slot(
    pool: dict[str, Any],
    *,
    now: str,
    ticket_path: str,
    quiescent_until: str,
    avoid_slot_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (new_pool, allocation); caller must CAS-persist new_pool before scheduler arm."""
    normalized = recycle_quiescent_slots(pool, now=now)
    selected = select_idle_slot(normalized, now=now, avoid_slot_id=avoid_slot_id)
    out = copy.deepcopy(normalized)

    generation = out.get("pool_generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise TransportError("pool_generation must be a non-negative integer")
    generation += 1
    out["pool_generation"] = generation

    target = next(
        (slot for slot in out.get("slots", []) if slot.get("slot_id") == selected["slot_id"]),
        None,
    )
    if target is None:
        raise TransportError("selected slot disappeared")
    if target.get("state") != "idle":
        raise TransportError("selected slot is not idle")
    target["state"] = "armed"
    target["last_transport_generation"] = generation
    target["current_ticket"] = ticket_path
    target["quiescent_until"] = quiescent_until

    allocation = {
        "slot_id": target["slot_id"],
        "automation_id": target["automation_id"],
        "transport_generation": generation,
        "ticket_path": ticket_path,
        "quiescent_until": quiescent_until,
    }
    return out, allocation


def mark_slot_quiescent(
    pool: dict[str, Any],
    *,
    slot_id: str,
    transport_generation: int,
    quiescent_until: str,
) -> dict[str, Any]:
    out = copy.deepcopy(pool)
    target = next(
        (slot for slot in out.get("slots", []) if slot.get("slot_id") == slot_id),
        None,
    )
    if target is None:
        raise TransportError("unknown slot_id")
    if target.get("last_transport_generation") != transport_generation:
        raise TransportError("transport generation fence mismatch")
    if target.get("state") not in {"armed", "running", "awaiting-relay"}:
        raise TransportError("slot cannot enter quiescence from current state")
    target["state"] = "quiescent"
    target["quiescent_until"] = quiescent_until
    return out
