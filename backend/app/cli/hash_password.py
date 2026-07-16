"""Prints an argon2 hash for AUTH_PASSWORD_HASH. Run via:

  docker compose run --rm --no-deps --entrypoint python backend -m app.cli.hash_password

(--entrypoint is required because the backend image's ENTRYPOINT swallows args.)
"""
from __future__ import annotations

import getpass
import sys

from app.core.security import hash_password


def main() -> None:
    pw = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        print("Passwords did not match.", file=sys.stderr)
        raise SystemExit(1)
    if not pw:
        print("Password cannot be empty.", file=sys.stderr)
        raise SystemExit(1)
    print(hash_password(pw))


if __name__ == "__main__":
    main()
