"""Set up a fresh Stardog (Cloud) endpoint for this project: database, options, users, permissions.

Creates, unless they exist already (so it is safe to rerun):
  database  STARDOG_DATABASE, with voicebox.enabled=true and query.all.graphs=true (docs/decisions.md)
  user      STARDOG_USERNAME (the loader): READ + WRITE on that database only
  user      STARDOG_READER_USERNAME (the MCP server): READ on that database only
Passwords are taken from .env (STARDOG_PASSWORD, STARDOG_READER_PASSWORD), so the rest of the
pipeline needs no change. Needs an admin login, STARDOG_ADMIN_USERNAME and STARDOG_ADMIN_PASSWORD in
.env, used by this script only; remove them from .env afterwards.

Then load the data with scripts/load_stardog.py.

Usage: .venv/bin/python scripts/setup_stardog.py
"""
import base64
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_stardog import ROOT  # noqa: E402

DB_OPTIONS = {"voicebox.enabled": True, "query.all.graphs": True}


def env():
    out = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    need = ["STARDOG_ENDPOINT", "STARDOG_DATABASE", "STARDOG_USERNAME", "STARDOG_PASSWORD",
            "STARDOG_READER_USERNAME", "STARDOG_READER_PASSWORD", "STARDOG_ADMIN_USERNAME", "STARDOG_ADMIN_PASSWORD"]
    if missing := [k for k in need if not out.get(k)]:
        sys.exit(f"missing in .env: {missing}")
    return out


class Admin:
    def __init__(self, e):
        self.base = e["STARDOG_ENDPOINT"].rstrip("/")
        token = base64.b64encode(f"{e['STARDOG_ADMIN_USERNAME']}:{e['STARDOG_ADMIN_PASSWORD']}".encode()).decode()
        self.auth = {"Authorization": f"Basic {token}"}

    def call(self, method, path, body=None, content_type="application/json"):
        headers = dict(self.auth, Accept="application/json")
        if body is not None:
            headers["Content-Type"] = content_type
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                text = resp.read().decode()
                return json.loads(text) if text.strip().startswith(("{", "[")) else text
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {exc.read()[:400].decode(errors='replace')}") from None


def create_database(admin, name):
    if name in admin.call("GET", "/admin/databases")["databases"]:
        print(f"database {name}: exists")
    else:
        boundary = uuid.uuid4().hex
        root = json.dumps({"dbname": name, "options": DB_OPTIONS, "files": []})
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"root\"\r\n\r\n{root}\r\n"
                f"--{boundary}--\r\n").encode()
        admin.call("POST", "/admin/databases", body, f"multipart/form-data; boundary={boundary}")
        print(f"database {name}: created")
    current = admin.call("GET", f"/admin/databases/{name}/options")
    wrong = {k: v for k, v in DB_OPTIONS.items() if current.get(k) != v}
    if wrong:  # an existing database, or a server that ignored the options at creation
        admin.call("POST", f"/admin/databases/{name}/options", wrong)
        print(f"database {name}: set {wrong}")


def create_user(admin, user, password, actions, db):
    users = admin.call("GET", "/admin/users")["users"]
    if user in users:
        print(f"user {user}: exists (password unchanged)")
    else:
        admin.call("POST", "/admin/users", {"username": user, "password": list(password), "superuser": False})
        print(f"user {user}: created")
    for action in actions:
        try:
            admin.call("PUT", f"/admin/permissions/user/{user}",
                       {"action": action, "resource_type": "db", "resource": [db]})
            print(f"user {user}: {action} on db:{db}")
        except RuntimeError as exc:
            if "409" not in str(exc):  # 409: permission exists already
                raise
            print(f"user {user}: {action} on db:{db} (exists)")


def main():
    e = env()
    admin = Admin(e)
    db = e["STARDOG_DATABASE"]
    create_database(admin, db)
    create_user(admin, e["STARDOG_USERNAME"], e["STARDOG_PASSWORD"], ["read", "write"], db)
    create_user(admin, e["STARDOG_READER_USERNAME"], e["STARDOG_READER_PASSWORD"], ["read"], db)
    print("\ndone; remove STARDOG_ADMIN_* from .env, then run scripts/load_stardog.py")


if __name__ == "__main__":
    main()
