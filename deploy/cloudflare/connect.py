#!/usr/bin/env python3
"""Put TranslateBook AI on Cloudflare's free tier (docs/CLOUDFLARE.md).

    python deploy/cloudflare/connect.py setup     # once: build, deploy the Worker, secrets
    python deploy/cloudflare/connect.py           # each session: tunnel + point the site at it

How it fits together:

* The React app is deployed as a **Cloudflare Worker** with static assets
  (free), at ``https://translatebook-ai.<your-subdomain>.workers.dev``. The
  Worker puts a password in front of the whole site and proxies ``/api``.
* The API, job worker, database and OCR keep running on **your machine**. A
  free **Cloudflare quick tunnel** gives it a public https address, and the
  proxy forwards ``/api`` there with a shared secret the API checks.
* A quick tunnel gets a new address every time it starts, so this script
  starts it and stores the address as the Worker's ``BACKEND_URL`` secret.
  Secrets apply immediately, with no redeploy. With your own domain on
  Cloudflare, use a named tunnel instead and run ``set-backend <url>`` once.

Only the Python standard library is used. Wrangler (the Cloudflare CLI) is
installed into this folder on first use, pinned in package.json.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
WORKER = os.environ.get("CF_WORKER_NAME", "translatebook-ai")
WRANGLER_JS = HERE / "node_modules" / "wrangler" / "bin" / "wrangler.js"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
WORKER_URL = re.compile(r"https://[a-z0-9.-]+\.workers\.dev")


def say(msg: str) -> None:
    print(f"[cloudflare] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[cloudflare] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------- .env


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def set_env(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- tools


def node() -> str:
    path = shutil.which("node")
    if not path:
        fail("Node.js is required for the Cloudflare CLI: https://nodejs.org")
    return path


def ensure_wrangler() -> None:
    if WRANGLER_JS.exists():
        return
    npm = shutil.which("npm")
    if not npm:
        fail("npm is required to install the Cloudflare CLI: https://nodejs.org")
    say("installing the Cloudflare CLI (wrangler) into deploy/cloudflare ...")
    subprocess.run([npm, "install", "--no-fund", "--no-audit"], cwd=HERE, check=True)


def wrangler(*args: str, stdin: str | None = None) -> str:
    """Run wrangler from the frontend folder (where wrangler.toml lives)."""
    ensure_wrangler()
    proc = subprocess.run(
        [node(), str(WRANGLER_JS), *args],
        cwd=FRONTEND,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(out.strip()[-1500:])
    return out


def cloudflared() -> str:
    candidates = [
        shutil.which("cloudflared"),
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
        "/usr/local/bin/cloudflared",
        "/opt/homebrew/bin/cloudflared",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    fail(
        "cloudflared is not installed. Windows: winget install Cloudflare.cloudflared · "
        "macOS: brew install cloudflared · Linux: "
        "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    )
    raise AssertionError  # unreachable


# ---------------------------------------------------------------- Worker


def put_secret(name: str, value: str) -> None:
    wrangler("secret", "put", name, "--name", WORKER, stdin=value)
    say(f"secret {name} set")


def build_frontend() -> None:
    npm = shutil.which("npm") or fail("npm not found")
    if not (FRONTEND / "node_modules").exists():
        subprocess.run([npm, "ci", "--no-fund", "--no-audit"], cwd=FRONTEND, check=True)
    say("building the web app ...")
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def deploy() -> str | None:
    say("deploying the Worker ...")
    out = wrangler("deploy", "--name", WORKER)
    urls = WORKER_URL.findall(out)
    if urls:
        set_env("CLOUDFLARE_SITE_URL", urls[-1])
    return urls[-1] if urls else None


def site_url() -> str:
    return read_env().get("CLOUDFLARE_SITE_URL") or f"https://{WORKER}.<subdomain>.workers.dev"


# ---------------------------------------------------------------- commands


def cmd_setup(args: argparse.Namespace) -> None:
    env = read_env()
    secret = env.get("API_SHARED_SECRET") or secrets.token_urlsafe(32)
    password = args.password or env.get("CLOUDFLARE_SITE_PASSWORD") or secrets.token_urlsafe(12)
    set_env("API_SHARED_SECRET", secret)
    set_env("CLOUDFLARE_SITE_PASSWORD", password)
    say("saved API_SHARED_SECRET and CLOUDFLARE_SITE_PASSWORD in .env (never committed)")
    if args.no_build and (FRONTEND / "dist" / "index.html").exists():
        say("reusing frontend/dist")
    else:
        build_frontend()
    url = deploy()  # the Worker must exist before it can hold secrets
    put_secret("BACKEND_SECRET", secret)
    put_secret("SITE_PASSWORD", password)
    say(f"deployed: {url or site_url()}")
    print(
        "\nNext:\n"
        "  1. Restart the server so it reads API_SHARED_SECRET (make start).\n"
        "  2. Run:  python deploy/cloudflare/connect.py      (starts the tunnel)\n"
        f"  3. Open {site_url()}\n"
        "     any user name; the password is CLOUDFLARE_SITE_PASSWORD in .env\n"
    )


def _health(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def cmd_set_backend(args: argparse.Namespace) -> None:
    url = args.url.rstrip("/")
    put_secret("BACKEND_URL", url)
    say(f"{site_url()} now forwards /api to {url}")


def cmd_deploy(args: argparse.Namespace) -> None:
    build_frontend()
    say(f"deployed: {deploy() or site_url()}")


def cmd_tunnel(args: argparse.Namespace) -> None:
    env = read_env()
    if not env.get("API_SHARED_SECRET"):
        fail("run `python deploy/cloudflare/connect.py setup` first")
    port = args.port or int(env.get("API_PORT") or 8010)
    local = f"http://127.0.0.1:{port}"
    if not _health(local):
        fail(
            f"the TranslateBook server is not answering on {local}. Start it first "
            "(make start, or `uv run translatebook serve` in backend/), then run this again."
        )

    say(f"starting a quick tunnel to {local} ...")
    proc = subprocess.Popen(
        [cloudflared(), "tunnel", "--no-autoupdate", "--url", local],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    found: list[str] = []
    ready = threading.Event()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = TUNNEL_URL.search(line)
            if match and not found:
                found.append(match.group(0))
                ready.set()
            if args.verbose or " ERR " in line:
                print("   [tunnel] " + line.rstrip())

    threading.Thread(target=pump, daemon=True).start()
    if not ready.wait(60):
        proc.terminate()
        fail("cloudflared did not report a tunnel address within 60 s (try --verbose)")
    tunnel = found[0]
    say(f"tunnel: {tunnel}")
    for _ in range(30):
        if _health(tunnel, timeout=8):
            break
        time.sleep(2)
    else:
        say("the tunnel address does not answer yet; continuing anyway")
    try:
        put_secret("BACKEND_URL", tunnel)
    except RuntimeError as exc:
        proc.terminate()
        fail(f"could not update the Worker: {exc}")
    print(
        f"\n  TranslateBook AI is online at {site_url()}\n"
        "  any user name; the password is CLOUDFLARE_SITE_PASSWORD in .env\n"
        "  Keep this window open; press Ctrl+C to take it offline.\n",
        flush=True,
    )
    try:
        while proc.poll() is None:
            time.sleep(1)
        fail(f"cloudflared exited with code {proc.returncode}")
    except KeyboardInterrupt:
        say("stopping the tunnel ...")
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        say("offline. The site answers 'not connected' until you run this again.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser("setup", help="build, deploy the Worker, create its secrets")
    setup.add_argument("--password", help="site password (default: generated)")
    setup.add_argument("--no-build", action="store_true", help="reuse frontend/dist")
    sub.add_parser("deploy", help="rebuild the web app and redeploy the Worker")
    setb = sub.add_parser("set-backend", help="point the site at a fixed backend URL")
    setb.add_argument("url")
    tun = sub.add_parser("tunnel", help="(default) start a quick tunnel and connect the site")
    for p in (parser, tun):
        p.add_argument("--port", type=int, help="local API port (default: API_PORT or 8010)")
        p.add_argument("--verbose", action="store_true", help="show cloudflared logs")
    args = parser.parse_args()
    commands = {"setup": cmd_setup, "deploy": cmd_deploy, "set-backend": cmd_set_backend}
    commands.get(args.command, cmd_tunnel)(args)


if __name__ == "__main__":
    main()
