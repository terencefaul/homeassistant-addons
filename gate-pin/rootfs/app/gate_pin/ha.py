"""Home Assistant client.

Takes a token *provider* rather than a token, so an integration wrapper can
supply hass-derived credentials without this module knowing Supervisor exists.

Nothing on the guest request path ever holds the token. Callers pass an entity
and an intent; this module resolves the service itself and builds the payload
as {"entity_id": ...} and nothing else, so no field from a request body can
reach Home Assistant.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from . import policy

DEFAULT_BASE = "http://supervisor/core/api/"


class HAError(Exception):
    """Home Assistant did not accept or answer the call.

    Distinct from a policy refusal on purpose: the visitor must be told 'the
    gate did not respond', never 'wrong code'. Collapsing the two is what makes
    every fault in this system look identical from the outside.
    """


class HomeAssistant:
    def __init__(
        self,
        token_provider: Callable[[], str],
        base_url: str = DEFAULT_BASE,
        timeout: float = 10.0,
    ):
        self._token = token_provider
        self._base = base_url.rstrip("/") + "/"
        self._client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    async def states(self) -> list[dict[str, Any]]:
        try:
            r = await self._client.get(self._base + "states", headers=self._headers())
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            raise HAError(f"could not read entity states: {exc}") from exc

    async def state(self, entity_id: str) -> Optional[dict[str, Any]]:
        try:
            r = await self._client.get(
                self._base + f"states/{entity_id}", headers=self._headers()
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except HAError:
            raise
        except Exception as exc:
            raise HAError(f"could not read {entity_id}: {exc}") from exc

    async def call_intent(self, entity_id: str, intent: str) -> None:
        """Resolve an intent to a service and call it.

        Raises PolicyError if the pair is not permitted, HAError if the call
        was permitted but did not succeed. The caller must keep those apart.
        """
        domain, service = policy.resolve_service(entity_id, intent)
        try:
            r = await self._client.post(
                self._base + f"services/{domain}/{service}",
                headers=self._headers(),
                json={"entity_id": entity_id},
            )
            r.raise_for_status()
        except Exception as exc:
            raise HAError(f"{domain}.{service} on {entity_id} failed: {exc}") from exc

    async def camera_snapshot(self, entity_id: str) -> tuple[bytes, str]:
        if policy.domain_of(entity_id) != "camera":
            raise HAError(f"{entity_id} is not a camera")
        try:
            r = await self._client.get(
                self._base + f"camera_proxy/{entity_id}", headers=self._headers()
            )
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "image/jpeg")
        except Exception as exc:
            raise HAError(f"camera {entity_id} unavailable: {exc}") from exc

    async def notify(self, service: str, title: str, message: str) -> None:
        """Send an alert through a notify.* service. Never raises."""
        if not service:
            return
        name = service.split(".", 1)[1] if service.startswith("notify.") else service
        try:
            await self._client.post(
                self._base + f"services/notify/{name}",
                headers=self._headers(),
                json={"title": title, "message": message},
            )
        except Exception:
            pass

    async def persistent_notification(self, title: str, message: str) -> None:
        try:
            await self._client.post(
                self._base + "services/persistent_notification/create",
                headers=self._headers(),
                json={"title": title, "message": message},
            )
        except Exception:
            pass
