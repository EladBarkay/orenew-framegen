"""Resource IDs: a short type prefix and 128 random bits, for example ``usr_3k...``.

The prefix makes an ID's kind obvious in logs and support requests (DESIGN.md section 10.1).
"""

import base64
import secrets


def new_id(prefix: str) -> str:
    random = base64.b32encode(secrets.token_bytes(16)).decode().rstrip("=").lower()
    return f"{prefix}_{random}"
