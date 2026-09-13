"""Seed ephemeral native account configuration, then exec the unchanged CLI.

Pi's OAuth credential accepts an empty refresh string; Tau explicitly supports
an access JWT via OPENAI_CODEX_ACCESS_TOKEN. Both use the same Codex account.
Refresh tokens are never exported, avoiding rotation of the host's credentials.
"""

import json
import os
from pathlib import Path
import sys


def write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def seed_account(seed: dict, harness: str, home: Path) -> None:
    if harness == "pi":
        write_private(home / ".pi/agent/auth.json", {"openai-codex": {
            "type": "oauth", "access": seed["access_token"], "refresh": "",
            "expires": seed["expires"], "accountId": seed["account_id"],
        }})
    elif harness == "tau":
        os.environ["OPENAI_CODEX_ACCESS_TOKEN"] = seed["access_token"]
    elif harness == "codex":
        write_private(home / ".codex/auth.json", {
            "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": seed["access_token"], "id_token": seed["id_token"],
                "refresh_token": "", "account_id": seed["account_id"],
            },
            "last_refresh": seed["last_refresh"],
        })
    else:
        raise ValueError("Unsupported native account bridge")


def main() -> None:
    try:
        path = Path("/run/harness-account.json")
        if path.is_file():
            seed_account(json.loads(path.read_text()), os.environ["DOC_INTELL_HARNESS"], Path.home())
        if len(sys.argv) < 2:
            raise ValueError("Missing harness command")
        os.execvp(sys.argv[1], sys.argv[1:])
    except (OSError, ValueError, KeyError, TypeError):
        # Never include exception representations: they can contain credential data.
        print("Could not initialize the native harness environment", file=sys.stderr)
        sys.exit(78)


if __name__ == "__main__":
    main()
