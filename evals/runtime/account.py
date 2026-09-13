"""Read the existing Codex access credential for a disposable account seed."""

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


MIN_AUTH_VALIDITY_SECONDS = 900


def _codex_auth_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"


def read_account_seed() -> dict:
    """Read only the current access credential; never export the refresh secret."""
    try:
        auth = json.loads(_codex_auth_path().read_text(encoding="utf-8"))
        tokens = auth["tokens"]
        access = tokens["access_token"]
        part = access.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        expires = claims["exp"]
        account = tokens.get("account_id") or claims["https://api.openai.com/auth"]["chatgpt_account_id"]
        if not isinstance(access, str) or not isinstance(account, str) or not account:
            raise ValueError
        if isinstance(expires, bool) or not isinstance(expires, (int, float)):
            raise ValueError
        if expires - time.time() < MIN_AUTH_VALIDITY_SECONDS:
            raise TimeoutError
    except TimeoutError:
        raise ValueError("Codex account access expires in under 15 minutes; refresh your Codex login before running") from None
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise ValueError("A valid existing Codex ChatGPT account login is required; run codex login first") from None
    return {
        "access_token": access,
        "id_token": tokens.get("id_token", ""),
        "account_id": account,
        "expires": int(expires * 1000),
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
