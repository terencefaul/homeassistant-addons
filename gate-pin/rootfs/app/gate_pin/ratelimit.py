"""Rate limiting.

With use counting dropped, this is the SOLE defence for the PIN path. Two
independent limiters, because either alone is defeated:

  per-IP backoff   - stops one client grinding, defeated by IP rotation
  global budget    - stops a rotating fleet, but on its own would let a single
                     client burn the whole budget for everybody

Policy differs by credential kind, which is the practical payoff of issuing two
credentials per grant: the strict limits that protect a 20-bit PIN never
degrade the 192-bit link you actually use day to day.

A note on sizing, so the next person to change these numbers knows what they
are trading. An attacker guessing PINs wins on a hit against ANY live PIN, so
the effective keyspace is 10^len / (live PIN grants). At 6 digits with the
default cap of 20 live PIN grants that is 1_000_000 / 20 = 50_000. A global
budget of 20 failures per hour gives an expected 50_000 / 20 / 2 = 1250 hours
to a hit. Raise the cap or the budget and that number falls linearly.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from .clock import now

PIN_BASE_DELAY_S = 2
PIN_MAX_DELAY_S = 300
TOKEN_BASE_DELAY_S = 1
TOKEN_MAX_DELAY_S = 15


@dataclass
class Decision:
    allowed: bool
    retry_after: int = 0
    reason: str = ""
    lockout: bool = False


@dataclass
class _IpState:
    failures: int = 0
    blocked_until: int = 0
    last_seen: int = field(default_factory=now)


class RateLimiter:
    def __init__(
        self,
        *,
        global_budget: int = 20,
        global_window_s: int = 3600,
        cooldown_s: int = 900,
        token_global_budget: int = 300,
    ):
        self._lock = threading.Lock()
        self._ips: Dict[str, _IpState] = {}
        self._pin_failures: Deque[int] = deque()
        self._token_failures: Deque[int] = deque()
        self._global_budget = global_budget
        self._token_global_budget = token_global_budget
        self._window = global_window_s
        self._cooldown = cooldown_s
        self._locked_until = 0
        self._lockout_announced = False

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def _key(ip: str, kind: str) -> str:
        return f"{kind}:{ip}"

    def _trim(self, dq: Deque[int], t: int) -> None:
        while dq and dq[0] < t - self._window:
            dq.popleft()

    def _backoff(self, failures: int, kind: str) -> int:
        base, cap = (
            (PIN_BASE_DELAY_S, PIN_MAX_DELAY_S)
            if kind == "pin"
            else (TOKEN_BASE_DELAY_S, TOKEN_MAX_DELAY_S)
        )
        if failures <= 2:
            return 0
        return min(cap, base * (2 ** (failures - 3)))

    # ---- public ---------------------------------------------------------

    def check(self, ip: str, kind: str = "pin") -> Decision:
        t = now()
        with self._lock:
            if kind == "pin" and t < self._locked_until:
                # Failing closed for a cooldown is the deliberate choice. The
                # alternative -- staying open under an obvious attack -- is a
                # silently openable gate. The link path is untouched, so you
                # can still let someone in during a lockout.
                return Decision(
                    False,
                    retry_after=self._locked_until - t,
                    reason="locked_out",
                    lockout=True,
                )
            st = self._ips.get(self._key(ip, kind))
            if st and t < st.blocked_until:
                return Decision(False, retry_after=st.blocked_until - t, reason="backoff")
        return Decision(True)

    def record_failure(self, ip: str, kind: str = "pin") -> Decision:
        """Record a wrong credential. Returns the decision for the NEXT attempt."""
        t = now()
        with self._lock:
            key = self._key(ip, kind)
            st = self._ips.setdefault(key, _IpState())
            st.failures += 1
            st.last_seen = t
            delay = self._backoff(st.failures, kind)
            st.blocked_until = t + delay if delay else 0

            dq = self._pin_failures if kind == "pin" else self._token_failures
            budget = self._global_budget if kind == "pin" else self._token_global_budget
            dq.append(t)
            self._trim(dq, t)

            newly_locked = False
            if kind == "pin" and len(dq) >= budget and t >= self._locked_until:
                self._locked_until = t + self._cooldown
                newly_locked = True
                dq.clear()

            self._gc(t)
            return Decision(
                False,
                retry_after=max(delay, self._cooldown if newly_locked else 0),
                reason="locked_out" if newly_locked else "backoff",
                lockout=newly_locked,
            )

    def record_success(self, ip: str, kind: str = "pin") -> None:
        with self._lock:
            self._ips.pop(self._key(ip, kind), None)

    def _gc(self, t: int) -> None:
        if len(self._ips) < 4096:
            return
        stale = [k for k, v in self._ips.items() if v.last_seen < t - self._window]
        for k in stale:
            self._ips.pop(k, None)

    def snapshot(self) -> dict:
        t = now()
        with self._lock:
            self._trim(self._pin_failures, t)
            return {
                "locked_out": t < self._locked_until,
                "locked_until": self._locked_until if t < self._locked_until else None,
                "pin_failures_in_window": len(self._pin_failures),
                "pin_failure_budget": self._global_budget,
                "tracked_clients": len(self._ips),
            }
