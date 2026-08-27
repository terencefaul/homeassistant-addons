"""Time handling.

Every timestamp that is stored or sent over the wire is epoch seconds in UTC.
Never store a formatted local time: the reference add-on parsed locale strings
with strtotime() against a container-local TZ, so changing the container
timezone silently shifted every expiry that had already been written.

With use counting dropped, `valid_until` is the entire security model for a
grant. A clock bug here is not cosmetic.
"""

from __future__ import annotations

import time


def now() -> int:
    """Current time as epoch seconds, UTC."""
    return int(time.time())
