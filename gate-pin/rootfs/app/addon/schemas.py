"""Request and response models.

Every request model sets extra="forbid". That is the reason FastAPI was chosen
over aiohttp: "no field from the request body ever reaches the Home Assistant
call" becomes a type-level guarantee enforced at the boundary, rather than a
review rule that erodes. A request carrying `service`, `service_data` or an
entity_id array is rejected before any handler code runs.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from gate_pin.grants import KINDS, THEMES
from gate_pin.policy import ALL_INTENTS

Intent = Literal[tuple(ALL_INTENTS)]  # type: ignore[valid-type]
Theme = Literal[tuple(THEMES)]  # type: ignore[valid-type]
Kind = Literal[tuple(KINDS)]  # type: ignore[valid-type]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- guest ---------------------------------------------------------------


class RedeemRequest(Strict):
    credential: str = Field(min_length=1, max_length=128)


class ActRequest(Strict):
    entity_id: str = Field(min_length=3, max_length=255)
    intent: Intent


# ---- admin ---------------------------------------------------------------


class MintRequest(Strict):
    label: str = Field(default="", max_length=120)
    entities: list[str] = Field(min_length=1, max_length=50)
    duration_s: int = Field(ge=60, le=60 * 60 * 24 * 30)
    starts_in_s: int = Field(default=0, ge=0, le=60 * 60 * 24 * 30)
    # Omitted means "use the branding default". A hardcoded default here is what
    # made the Branding form's theme setting do nothing on this path.
    theme: Optional[Theme] = None
    kinds: list[Kind] = Field(default=["pin", "token"], min_length=1, max_length=2)


class ExtendRequest(Strict):
    additional_s: int = Field(ge=60, le=60 * 60 * 24 * 30)


class ReissueRequest(Strict):
    kinds: list[Kind] = Field(min_length=1, max_length=2)


class PresetRequest(Strict):
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=60)
    entities: list[str] = Field(min_length=1, max_length=50)
    duration_s: int = Field(ge=60, le=60 * 60 * 24 * 30)
    theme: Optional[Theme] = None
    kinds: list[Kind] = Field(default=["pin", "token"], min_length=1, max_length=2)


class BrandingRequest(Strict):
    accent: str = Field(default="#22c55e", pattern=r"^#[0-9a-fA-F]{6}$")
    default_theme: Theme = "dark"
    # Shown in the guest page header, so a visitor sees whose gate this is.
    property_name: str = Field(default="", max_length=60)


class ControlItem(Strict):
    """One block on the control page: a camera view, or a control."""

    type: Literal["camera", "control"]
    entity_id: str = Field(min_length=3, max_length=255)


class ControlConfigRequest(Strict):
    """The owner's control page as a single ordered list of blocks.

    One list rather than cameras-then-controls, so a camera can sit directly
    above the gate it looks at. Order is the list order -- there is no separate
    sort key to drift out of sync."""

    items: list[ControlItem] = Field(default=[], max_length=48)


class OwnerActRequest(Strict):
    """Operating an entity as the owner, from the control page.

    Shaped exactly like the guest ActRequest and resolved through the same
    policy: this is a second path to calling a service, so it must not become a
    looser one."""

    entity_id: str = Field(min_length=3, max_length=255)
    intent: Intent
