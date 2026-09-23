"""Local account recovery. Run bootstrap once, then sign in and change password."""

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

from fastapi import HTTPException

from mg.auth import AuthStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent / ".local",
                        help="Private local state directory (default: money_graph/.local)")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap", help="Create the first administrator only")
    bootstrap.add_argument("--username", required=True)
    create = commands.add_parser("create", help="Create an account with an interactively entered password")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=("admin", "analyst"), default="analyst")
    reset = commands.add_parser("reset", help="Set a password interactively and revoke all user sessions")
    reset.add_argument("--username", required=True)
    args = parser.parse_args(argv)
    try:
        store = AuthStore(args.root / "auth.sqlite3")
        if args.command == "bootstrap":
            if store.list_users():
                raise HTTPException(409, "Bootstrap is allowed only when no users exist")
            password = secrets.token_urlsafe(24)
            onboarding = args.root / "admin-onboarding.txt"
            # Exclusive creation avoids overwriting an existing recovery secret.
            fd = os.open(onboarding, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"Username: {args.username.lower()}\nTemporary password: {password}\n"
                                 "Change this password at first login, then delete this file.\n"
                                 "PRIVATE: restrict this directory and file to your Windows account.\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                store.create_user(args.username, password, "admin", must_change_password=True, bootstrap=True)
            except BaseException:
                onboarding.unlink(missing_ok=True)
                raise
            print(f"Initial administrator created. Credentials are in: {onboarding}")
            print("LOCAL PERMISSIONS WARNING: this file contains a password. Keep .local private; "
                  "on Windows, verify its ACL allows only your account (chmod does not restrict Windows ACLs). "
                  "The default .local directory is ignored by Git. Delete the onboarding file after changing the password.",
                  file=sys.stderr)
        else:
            password = getpass.getpass("New password (at least 12 characters): ")
            if password != getpass.getpass("Confirm new password: "):
                raise HTTPException(422, "Passwords do not match")
            if args.command == "create":
                store.create_user(args.username, password, args.role, must_change_password=True)
            else:
                store.reset_password(args.username, password)
            print("Account updated. A password change is required at next login.")
        return 0
    except (HTTPException, OSError, EOFError) as exc:
        print(f"Account operation failed: {exc.detail if isinstance(exc, HTTPException) else exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
