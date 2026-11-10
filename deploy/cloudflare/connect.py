#!/usr/bin/env python3
"""Put TranslateBook AI on Cloudflare's free tier (docs/CLOUDFLARE.md).

    python deploy/cloudflare/connect.py setup     # once: secrets, Pages project, first deploy
    python deploy/cloudflare/connect.py           # each session: tunnel + point the site at it

How it fits together:

* The React app is deployed to **Cloudflare Pages** (free) with two Pages
  Functions: a password gate for the whole site and a proxy for ``/api``.
* The API, worker, database and OCR keep running on **your machine**. A free
  **Cloudflare quick tunnel** gives it a public https address, and the proxy
  forwards ``/api`` there with a shared secret the API checks.
* A quick tunnel gets a new address every time it starts, so this script
  starts it, stores the address as the ``BACKEND_URL`` secret of the Pages
  project and redeploys (about 20 seconds). With your own domain on
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
PROJECT = os.environ.get("CF_PAGES_PROJECT", "translatebook-ai")
WRANGLER_JS = HERE / "node_modules" / "wrangler" / "bin" / "wrangler.js"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
PAGES_URL = re.compile(r"https://[a-z0-9.-]+\.pages\.dev")


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


def wrangler(*args: str, stdin: str | None = None, quiet: bool = False) -> str:
    """Run wrangler from the frontend folder (where functions/ and wrangler.toml live)."""
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
    if not quiet:
        for line in out.splitlines():
            if line.strip() and "out-of-date" not in line and "WARNING" not in line:
                print("   " + line)
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


# ---------------------------------------------------------------- Pages


def ensure_project() -> None:
    try:
        wrangler("pages", "project", "create", PROJECT, "--production-branch", "main", quiet=True)
        say(f"created Pages project {PROJECT}")
    except RuntimeError as exc:
        if "already exists" in str(exc) or "8000002" in str(exc):
            return
        raise


def put_secret(name: str, value: str) -> None:
    wrangler("pages", "secret", "put", name, "--project-name", PROJECT, stdin=value, quiet=True)
    say(f"secret {name} set")


def build_frontend() -> None:
    npm = shutil.which("npm") or fail("npm not found")
    if not (FRONTEND / "node_modules").exists():
        subprocess.run([npm, "ci", "--no-fund", "--no-audit"], cwd=FRONTEND, check=True)
    say("building the web app ...")
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def deploy() -> str | None:
    say("deploying to Cloudflare Pages ...")
    out = wrangler(
        "pages", "deploy", "dist", "--project-name", PROJECT, "--branch", "main",
        "--commit-dirty=true", quiet=True,
    )
    urls = PAGES_URL.findall(out)
    return urls[-1] if urls else None


def production_url() -> str:
    return f"https://{PROJECT}.pages.dev"


# ---------------------------------------------------------------- commands


def cmd_setup(args: argparse.Namespace) -> None:
    env = read_env()
    secret = env.get("API_SHARED_SECRET") or secrets.token_urlsafe(32)
    password = args.password or env.get("CLOUDFLARE_SITE_PASSWORD") or secrets.token_urlsafe(12)
    set_env("API_SHARED_SECRET", secret)
    set_env("CLOUDFLARE_SITE_PASSWORD", password)
    say("saved API_SHARED_SECRET and CLOUDFLARE_SITE_PASSWORD in .env (never committed)")
    ensure_project()
    put_secret("BACKEND_SECRET", secret)
    put_secret("SITE_PASSWORD", password)
    if not (FRONTEND / "dist" / "index.html").exists() or not args.no_build:
        build_frontend()
    url = deploy()
    say(f"deployed: {url or production_url()}")
    print(
        "\nNext:\n"
        "  1. Restart the server so it picks up API_SHARED_SECRET (make dev, or translatebook serve).\n"
        "  2. Run:  python deploy/cloudflare/connect.py      (starts the tunnel)\n"
        f"  3. Open {production_url()}  -  any user name, password: {password}\n"
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
    if not (FRONTEND / "dist" / "index.html").exists():
        build_frontend()
    deploy()
    say(f"{production_url()} now forwards /api to {url}")


def cmd_tunnel(args: argparse.Namespace) -> None:
    env = read_env()
    if not env.get("API_SHARED_SECRET"):
        fail("run `python deploy/cloudflare/connect.py setup` first")
    port = args.port or int(env.get("API_PORT") or 8010)
    local = f"http://127.0.0.1:{port}"
    if not _health(local):
        fail(
            f"the TranslateBook server is not answering on {local}. Start it first "
            "(make dev, or `uv run translatebook serve` in backend/), then run this again."
        )
    if args.build or not (FRONTEND / "dist" / "index.html").exists():
        build_frontend()

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
        deploy()
    except RuntimeError as exc:
        proc.terminate()
        fail(f"could not update the Pages project: {exc}")
    print(
        f"\n  TranslateBook AI is online at {production_url()}\n"
        f"  password: {env.get('CLOUDFLARE_SITE_PASSWORD', '(see .env)')}\n"
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
        say("offline. The site now answers 'not connected' until you run this again.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser("setup", help="create secrets and the Pages project, first deploy")
    setup.add_argument("--password", help="site password (default: generated)")
    setup.add_argument("--no-build", action="store_true", help="reuse frontend/dist")
    setb = sub.add_parser("set-backend", help="point the site at a fixed backend URL")
    setb.add_argument("url")
    tun = sub.add_parser("tunnel", help="(default) start a quick tunnel and connect the site")
    for p in (parser, tun):
        p.add_argument("--port", type=int, help="local API port (default: API_PORT or 8010)")
        p.add_argument("--build", action="store_true", help="rebuild the web app first")
        p.add_argument("--verbose", action="store_true", help="show cloudflared logs")
    args = parser.parse_args()
    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "set-backend":
        cmd_set_backend(args)
    else:
        cmd_tunnel(args)


if __name__ == "__main__":
    main()
