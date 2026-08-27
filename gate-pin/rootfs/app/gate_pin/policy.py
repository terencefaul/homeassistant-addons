"""What a guest may do to an entity.

The client never names a Home Assistant service. It sends an opaque intent
from a fixed vocabulary and the server resolves it here, so a crafted request
cannot reach a service that was never offered.
"""

from __future__ import annotations

from typing import Dict

# domain -> {intent: service}
POLICY: Dict[str, Dict[str, str]] = {
    "cover": {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"},
    # Deliberately no "lock" intent. A guest who can lock a door can lock
    # someone out. Only unlocking is ever offered.
    "lock": {"open": "unlock"},
    "light": {"on": "turn_on", "off": "turn_off"},
    "switch": {"on": "turn_on", "off": "turn_off"},
    "scene": {"activate": "turn_on"},
    "script": {"run": "turn_on"},
    "button": {"press": "press"},
}

# Shown to the guest with live state, never actuated.
READ_ONLY_DOMAINS = frozenset(
    {"binary_sensor", "sensor", "person", "device_tracker", "camera"}
)

# Cameras are selectable so the ADMIN panel can stream them. They are never
# rendered on the guest page: a public endpoint is the wrong place for video.
ADMIN_ONLY_DOMAINS = frozenset({"camera"})

ALL_INTENTS = sorted({i for m in POLICY.values() for i in m})


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def is_selectable(entity_id: str) -> bool:
    """May this entity be attached to a grant at all?"""
    d = domain_of(entity_id)
    return d in POLICY or d in READ_ONLY_DOMAINS


def is_guest_visible(entity_id: str) -> bool:
    """May this entity appear on the public guest page?"""
    return is_selectable(entity_id) and domain_of(entity_id) not in ADMIN_ONLY_DOMAINS


def is_actionable(entity_id: str) -> bool:
    return domain_of(entity_id) in POLICY


def intents_for(entity_id: str) -> list[str]:
    return sorted(POLICY.get(domain_of(entity_id), {}))


class PolicyError(Exception):
    """The requested (entity, intent) pair is not permitted by policy."""


def resolve_service(entity_id: str, intent: str) -> tuple[str, str]:
    """Map (entity, intent) to (domain, service), or raise.

    Returns only the domain and service name. The caller builds the payload as
    {"entity_id": entity_id} and nothing else -- no field from the request body
    ever reaches Home Assistant.
    """
    domain = domain_of(entity_id)
    if domain in ADMIN_ONLY_DOMAINS:
        raise PolicyError(f"{domain} entities are never actuated by guests")
    services = POLICY.get(domain)
    if not services:
        raise PolicyError(f"domain '{domain}' has no guest-callable services")
    service = services.get(intent)
    if not service:
        raise PolicyError(f"intent '{intent}' is not permitted on domain '{domain}'")
    return domain, service
