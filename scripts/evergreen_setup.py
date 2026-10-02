#!/usr/bin/env python3
"""evergreen_setup.py - what a skill needs to run, and how to get it here. The `setup` command of evergreen.py.

A unit that depends on anything outside itself (a command line tool, a Python package, an environment variable, a
local server, a model, an MCP server, an account) lists it in SETUP.md (protocol/SETUP.md):

  ## Needs          a table: id | kind | check | for | if missing
  ## Install        one `### <id>` block per need, one recipe line per environment key:
                    - <key>: `<command>` then `<command>` (tags)
                    - <key>: prose steps for what a script cannot do (manual)
  ## Environments met   a table the `--log` flag appends to: date | os | harness | missing | notes

`setup <unit>` detects the environment (operating system, agent harness, package managers on PATH), checks every
need it can check without side effects, and prints, per missing need, what it is for and the recipes that match
this environment, best first, each classed as one the agent may run after saying so (`self`), one that needs the
user (`user`: admin rights, an account, a licence, a large download, a secret) or none known yet (`none`). A recipe
missing from the unit is looked up in the store's book (EVERGREEN_HOME/setup/RECIPES.md, private to this machine)
and then the plugin's shared book (setup/RECIPES.md).

  --script PATH   write a reviewable install script (.ps1 on Windows, .sh elsewhere) for the missing needs
  --record ID --env KEY --how TEXT [--tags admin,large] [--verified] [--to unit|store|plugin]
                  add or replace one recipe line (delta edit); --verified stamps today and this environment key
  --log           append this environment and what is missing to Environments met and evergreen.json setup.envs
  --init          write SETUP.md from the template and add it to the unit's files map
  --attempt ID --result granted|done|pending|refused|failed [--route KEY] [--took TEXT] [--note TEXT]
                  log how getting a need went (Attempts table); a granted or done result with --route stamps that recipe
                  verified for this environment
  --skip-access   do not run the `access` probes (each is a read-only command that may take a few seconds)
  --request ID    print a least-privilege access request for an administrator: who, resource, read role, narrowest
                  scope, duration, the probe that will prove it; the agent fills it in with the user, never sends it alone

Access needs (a database, a telemetry store, a cloud role, an API scope, a repository, a VPN) are kind `access`: the
check is a read-only, non-interactive probe command that exits 0 only when the access works. A failed probe says
whether it looks like a sign-in problem (401, not logged in) or a permission problem (403, forbidden). Access is
always the user's to obtain: recipes for it are steps (indented numbered lines under the recipe line) the agent
walks the user through, one at a time, re-probing at the end, and the Attempts table keeps how each try went,
including requests still pending with an administrator.

Checks never install, never print a secret's value, and time out in seconds. Exit codes: 0 every required need is
present, 1 one is missing, 2 a usage error. Pure standard library.
"""
from __future__ import annotations

import importlib.util
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import evergreen as eg

SETUP_FILE = "SETUP.md"
CHECKABLE = ("command", "python", "env", "file", "url", "ollama", "access")
AGENT_CHECKED = ("mcp", "account", "manual")  # the script cannot see these; the agent checks them and says so
USER_TAGS = ("admin", "manual", "large", "secret", "paid")  # a recipe with any of these waits for the user's yes
MANAGERS = ("winget", "scoop", "choco", "brew", "port", "apt", "apt-get", "dnf", "yum", "pacman", "zypper", "apk",
            "nix", "pip", "pipx", "uv", "npm", "pnpm", "cargo", "go", "dotnet", "ollama", "docker")
TIMEOUT = 4
ACCESS_TIMEOUT = 20  # a probe is a network call with the user's credentials; long enough for a cold CLI, short enough to catch a prompt
RESULTS = ("granted", "done", "pending", "refused", "failed", "partial")
SIGNIN_RE = re.compile(r"\b401\b|unauthori[sz]ed|not logged in|az login|please (?:run|sign in|log ?in)|login required|"
                       r"authentication (?:failed|required)|expired (?:token|credentials)|no credentials|AADSTS", re.I)
DENIED_RE = re.compile(r"\b403\b|forbidden|AuthorizationFailed|does not have (?:authorization|permission)|permission denied|"
                       r"access (?:is )?denied|insufficient (?:privileges|permissions)|not authorized|InsufficientAccountPermissions", re.I)
SECRETISH_RE = re.compile(r"[A-Za-z0-9_\-.=+/]{32,}")
CREDENTIAL_RE = re.compile(r"(bearer\s+|(?:password|pwd|passwd|apikey|api_key|token|secret|sig)\s*[=:]\s*)[^\s;&'\"]+", re.I)
NETWORK_RE = re.compile(r"could not resolve|name or service not known|getaddrinfo|nodename nor servname|connection (?:refused|timed out|reset)|"
                        r"network is unreachable|no route to host|ETIMEDOUT|ECONNREFUSED|server was not found|login timeout expired|"
                        r"timeout expired|could not connect", re.I)

# Harness detection (R-20261002-1): Cowork first (it also sets CLAUDECODE), then AI_AGENT (Claude Code since 2.1.120
# sets `claude-code_<version>_agent`, Copilot `github_copilot_<surface>_agent`, Vercel's convention `name@version`),
# then AGENT (Goose, Amp), then each tool's own variables. Variables are inherited by child processes, so a tool started
# from inside another reads as the outer one unless it overwrites AI_AGENT: --harness or EVERGREEN_HARNESS overrides,
# because the agent always knows which harness it is running in.
FLAG_VALUES = ("1", "true", "yes", "on")
OFF_VALUES = ("", "0", "false", "no", "off")
AI_AGENT_PREFIXES = (("claude-code", "claude-code"), ("claude", "claude-code"), ("github_copilot", "copilot"),
                     ("github-copilot", "copilot"), ("copilot", "copilot"), ("gemini", "gemini-cli"), ("codex", "codex"),
                     ("cursor", "cursor"), ("opencode", "opencode"), ("amp", "amp"), ("goose", "goose"), ("devin", "devin"))
HARNESS_VARS = (
    ("codex", lambda e: any(k in e for k in ("CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_THREAD_ID", "CODEX_CI"))),
    ("gemini-cli", lambda e: e.get("GEMINI_CLI") == "1"),
    ("copilot", lambda e: e.get("COPILOT_CLI") == "1" or "COPILOT_AGENT_SESSION_ID" in e),
    ("opencode", lambda e: e.get("OPENCODE") == "1" or "OPENCODE_CLIENT" in e),
    ("augment", lambda e: e.get("AUGMENT_AGENT") == "1"),
    ("cline", lambda e: e.get("CLINE_ACTIVE") == "true"),
    ("goose", lambda e: e.get("GOOSE_TERMINAL") == "1"),
    ("claude-code", lambda e: e.get("CLAUDECODE") == "1" or "CLAUDE_CODE" in e or bool(e.get("CLAUDE_CODE_ENTRYPOINT"))),
    ("cursor", lambda e: e.get("CURSOR_AGENT") == "1"),  # CURSOR_TRACE_ID is set for a person typing in Cursor too
    ("replit", lambda e: e.get("REPLIT_MODE") == "assistant"),
)


def _agent_name(value: str) -> str | None:
    v = value.strip().lower()
    if v in OFF_VALUES:
        return None
    if v in FLAG_VALUES:
        return "agent"  # some agent, name unknown
    if "@" in v:
        v = v.rsplit("@", 1)[0]
    for prefix, name in AI_AGENT_PREFIXES:
        if v == prefix or v.startswith(prefix + "_") or v.startswith(prefix + "-"):
            return name
    return re.split(r"[_@]", v, 1)[0] or None


# ---------- environment ----------

def detect_os() -> tuple[str, list[str]]:
    """The operating system key and any extra facets (wsl)."""
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows", []
    if s == "darwin":
        return "macos", []
    extra = []
    try:
        if "microsoft" in platform.release().lower() or os.environ.get("WSL_DISTRO_NAME"):
            extra.append("wsl")
    except Exception:
        pass
    return ("linux" if s == "linux" else s or "unknown"), extra


def detect_harness(environ: dict | None = None) -> str:
    e = dict(os.environ if environ is None else environ)
    forced = (e.get("EVERGREEN_HARNESS") or "").strip().lower()
    if forced:
        return forced
    if e.get("CLAUDE_CODE_IS_COWORK"):
        return "cowork"
    for var in ("AI_AGENT", "AGENT"):
        name = _agent_name(e.get(var) or "")
        if name:
            return name
    for name, test in HARNESS_VARS:
        try:
            if test(e):
                return name
        except Exception:
            continue
    return "unknown"


def environment(harness: str | None = None, os_key: str | None = None) -> dict:
    o, extra = detect_os()
    o = os_key or o
    h = (harness or detect_harness()).lower()
    managers = [m for m in MANAGERS if shutil.which(m)]
    return {"os": o, "extra": extra, "harness": h, "managers": managers, "key": f"{o}/{h}",
            "facets": set([o, h, *extra, *managers])}


# ---------- parsing ----------

def section(text: str, title: str) -> str | None:
    m = re.search(rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S | re.I)
    return m.group(1) if m else None


def _cells(line: str) -> list[str]:
    """Table cells; an escaped pipe (a backslash before it) stays inside its cell, as GitHub renders it."""
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith(chr(92) + "|") else s
    return [c.replace(chr(92) + "|", "|").strip() for c in re.split(r"(?<!\\)\|", s)]


def parse_needs(text: str) -> list[dict]:
    body = section(text, "Needs")
    if body is None:
        return []
    rows = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 2:
        return []
    head = [h.lower() for h in _cells(rows[0])]
    out = []
    for ln in rows[2:]:
        c = _cells(ln)
        row = {head[i]: c[i] for i in range(min(len(head), len(c)))}
        nid = row.get("id", "").strip("` ")
        if not nid or nid.startswith("<"):
            continue
        when = row.get("if missing") or row.get("required") or "required"
        out.append({"id": nid, "kind": row.get("kind", "manual").strip("` ").lower(),
                    "check": row.get("check", "").strip().strip("`").strip(), "for": row.get("for", ""),
                    "optional": when.lower().startswith("optional"), "if_missing": when})
    return out


RECIPE_RE = re.compile(r"^-\s+([a-z0-9][a-z0-9_.+/-]*):\s+(.*?)\s*$", re.I)
STEP_RE = re.compile(r"^\s{2,}(?:\d+[.)]|[-*])\s+(.*\S)\s*$")
TAIL_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
CMD_RE = re.compile(r"`([^`]+)`")


def parse_recipe_line(line: str) -> dict | None:
    m = RECIPE_RE.match(line)
    if not m:
        return None
    key, how = m.group(1).lower(), m.group(2)
    tags, verified = [], None
    t = TAIL_RE.search(how)
    if t and not CMD_RE.search(t.group(1)):
        for part in re.split(r"[;,]", t.group(1)):
            part = part.strip()
            v = re.match(r"verified\s+(\d{4}-\d{2}-\d{2})(?:\s+on\s+(\S+))?", part, flags=re.I)
            if v:
                verified = {"date": v.group(1), "on": v.group(2)}
            elif part.lower() in USER_TAGS or part.lower() in ("unverified",):
                tags.append(part.lower())
            elif part:
                tags.append(part)
        how = how[:t.start()].rstrip()
    stripped = CMD_RE.sub("", how)
    commands = CMD_RE.findall(how) if re.fullmatch(r"[\s;]*(?:then[\s;]*)*", stripped, flags=re.I) else []
    return {"key": key, "how": how, "commands": commands, "tags": tags, "verified": verified, "steps": []}


def parse_recipes(text: str, source: str) -> dict[str, list[dict]]:
    body = section(text, "Install")
    body = text if body is None else body
    out: dict[str, list[dict]] = {}
    current, last = None, None
    for ln in body.splitlines():
        h = re.match(r"^###\s+`?([^`\s]+)`?\s*$", ln)
        if h:
            current, last = h.group(1), None
            out.setdefault(current, [])
            continue
        if current and ln.startswith("## "):
            current = last = None
        if current:
            r = parse_recipe_line(ln)
            if r:
                r["source"] = source
                out[current].append(r)
                last = r
                continue
            s = STEP_RE.match(ln)
            if s and last is not None:
                last["steps"].append(s.group(1))
            elif ln.strip():
                last = None
    return out


def key_matches(key: str, env: dict) -> int | None:
    """Specificity of a recipe key in this environment (number of parts), or None when it does not apply."""
    if key == "any":
        return 0
    parts = key.split("/")
    return len(parts) if all(p in env["facets"] for p in parts) else None


def classify(r: dict) -> str:
    if not r["commands"] or r.get("steps") or any(t in USER_TAGS for t in r["tags"]):
        return "user"
    return "self"


# ---------- books ----------

def plugin_book() -> Path:
    return eg.plugin_root() / "setup" / "RECIPES.md"


def store_book() -> Path:
    return eg.evergreen_home() / "setup" / "RECIPES.md"


def recipes_for(nid: str, books: list[tuple[str, dict]], env: dict) -> list[dict]:
    found = []
    for rank, (source, book) in enumerate(books):
        for order, r in enumerate(book.get(nid, [])):
            spec = key_matches(r["key"], env)
            if spec is None:
                continue
            found.append((rank, -spec, 0 if r["verified"] else 1, order, r))
    found.sort(key=lambda x: x[:4])
    seen, out = set(), []
    for *_, r in found:
        sig = (r["key"], r["how"])
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


def load_books(d: Path | None) -> list[tuple[str, dict]]:
    books = []
    for source, p in (("unit", (d / SETUP_FILE) if d else None), ("store", store_book()), ("plugin", plugin_book())):
        if p and p.exists():
            books.append((source, parse_recipes(p.read_text(encoding="utf-8", errors="replace"), source)))
    return books


# ---------- checks ----------

def _version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def check_command(spec: str) -> tuple[bool, str]:
    minimum = None
    m = re.match(r"^(.*?)\s*>=\s*([\d.]+)\s*$", spec)
    if m:
        spec, minimum = m.group(1), tuple(int(x) for x in m.group(2).split(".") if x)
    for alt in [s.strip() for s in spec.split("|") if s.strip()]:
        argv = alt.split()
        exe = shutil.which(argv[0])
        if not exe:
            continue
        if minimum is None:
            return True, exe
        try:
            args = argv[1:] or ["--version"]  # a bare interpreter would wait on stdin
            p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
            v = _version((p.stdout or "") + (p.stderr or ""))
        except Exception as e:
            return False, f"{argv[0]} found but did not run: {e}"
        if v and v >= minimum:
            return True, f"{argv[0]} {'.'.join(map(str, v))}"
        return False, f"{argv[0]} {'.'.join(map(str, v)) if v else '(no version)'} is older than {'.'.join(map(str, minimum))}"
    return False, "not on PATH"


def _http_ok(url: str) -> tuple[bool, str, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "evergreen-setup"}), timeout=TIMEOUT) as r:
            return True, f"HTTP {r.status}", r.read(200000)
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}", b""
    except Exception as e:
        return False, f"unreachable ({type(e).__name__})", b""


def _redact(line: str) -> str:
    return SECRETISH_RE.sub("<redacted>", CREDENTIAL_RE.sub(lambda m: m.group(1) + "<redacted>", line))[:160]


def check_access(probe: str) -> tuple[bool, str]:
    """Run a read-only, non-interactive probe through the platform shell; exit 0 means the access works. Only the
    exit code and one redacted error line are kept: a probe's output can hold data the user did not ask to see."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", PGCONNECT_TIMEOUT="10", AZURE_CORE_ONLY_SHOW_ERRORS="true")
    try:
        p = subprocess.run(probe, shell=True, capture_output=True, text=True, timeout=ACCESS_TIMEOUT,
                           stdin=subprocess.DEVNULL, env=env, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, (f"probe timed out after {ACCESS_TIMEOUT}s: a sign-in, password or install prompt (probes must be "
                       "non-interactive), or the network or VPN")
    if p.returncode == 0:
        return True, "probe passed"
    text = (p.stderr or "") + "\n" + (p.stdout or "")
    lines = [ln.strip() for ln in (p.stderr or p.stdout or "").splitlines() if ln.strip()]
    first = _redact(lines[-1]) if lines else ""
    if SIGNIN_RE.search(text):
        why = "not signed in or the sign-in expired (401)"
    elif DENIED_RE.search(text):
        why = "signed in but not permitted (403): needs a role, grant or scope"
    elif p.returncode in (127, 9009) or re.search(r"not recognized|command not found|No such file|extension .* not installed|"
                                                   r"is misspelled or not recognized", text, re.I):
        why = "the probe's tool or extension is missing (an install need, not access)"
    elif NETWORK_RE.search(text):
        why = "the resource is unreachable: network, VPN or firewall, not permission"
    else:
        why = f"probe exit {p.returncode}"
    return False, why + (f": {first}" if first else "")


def check_need(n: dict, skip_access: bool = False) -> tuple[str, str]:
    """('ok' | 'missing' | 'agent', detail). Never installs; never prints a secret."""
    kind, spec = n["kind"], os.path.expandvars(n["check"])
    try:
        if kind == "command":
            ok, why = check_command(spec or n["id"])
        elif kind == "python":
            ok = importlib.util.find_spec(spec or n["id"]) is not None
            why = "importable" if ok else f"not importable by {Path(sys.executable).name}"
        elif kind == "env":
            ok = bool(os.environ.get(spec or n["id"]))
            why = "set" if ok else "not set"
        elif kind == "file":
            pat = os.path.expanduser(spec)
            ok = bool(glob.glob(pat)) if any(ch in pat for ch in "*?[") else Path(pat).exists()
            why = "present" if ok else "not found"
        elif kind == "url":
            ok, why, _ = _http_ok(spec)
        elif kind == "access":
            if skip_access or not spec:
                return "agent", (n["check"] or "no probe") + (" (probe skipped)" if skip_access else "")
            ok, why = check_access(spec)
        elif kind == "ollama":
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            host = host if host.startswith("http") else f"http://{host}"
            reached, why, body = _http_ok(host.rstrip("/") + "/api/tags")
            names = [m.get("name", "") for m in (json.loads(body or b"{}").get("models") or [])] if reached and body else []
            want = spec or n["id"]
            ok = any(x == want or x.split(":")[0] == want for x in names)
            why = ("pulled" if ok else f"not pulled ({len(names)} models on {host})") if reached else f"ollama {why}"
        else:
            return "agent", n["check"] or "check by hand"
    except Exception as e:
        return "missing", f"check failed: {e}"
    return ("ok" if ok else "missing"), why


def parse_attempts(text: str) -> list[dict]:
    body = section(text, "Attempts")
    if body is None:
        return []
    rows = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 2:
        return []
    head = [h.lower() for h in _cells(rows[0])]
    out = []
    for ln in rows[2:]:
        c = _cells(ln)
        row = {head[i]: c[i] for i in range(min(len(head), len(c)))}
        if row.get("need"):
            out.append(row)
    return out


def latest_attempts(text: str) -> dict[str, dict]:
    last: dict[str, dict] = {}
    for row in parse_attempts(text):
        last[row["need"]] = row  # rows are appended, so the last one is the newest
    return last


def run_checks(d: Path | None, needs: list[dict], env: dict, skip_access: bool = False) -> list[dict]:
    books = load_books(d)
    sp = (d / SETUP_FILE) if d else None
    attempts = latest_attempts(sp.read_text(encoding="utf-8", errors="replace")) if sp and sp.exists() else {}
    out = []
    for n in needs:
        status, why = check_need(n, skip_access)
        row = dict(n, status=status, detail=why)
        if n["id"] in attempts:
            row["last_attempt"] = attempts[n["id"]]
        if status != "ok":
            rs = recipes_for(n["id"], books, env)
            row["recipes"] = [dict(r, cls=classify(r)) for r in rs]
            row["cls"] = rs and classify(rs[0]) or "none"
            if n["kind"] in ("env", "access") and row["cls"] == "self":
                row["cls"] = "user"  # a value or a grant a person holds; an agent never invents, handles or grants it
        out.append(row)
    return out


# ---------- files ----------

def unit_setup(d: Path, st: dict) -> Path:
    return d / ((st.get("files") or {}).get("setup") or SETUP_FILE)


def envs_met(st: dict) -> list[str]:
    return list((st.get("setup") or {}).get("envs") or [])


def ensure_section(text: str, title: str, after: str = "") -> str:
    if section(text, title) is not None:
        return text
    return text.rstrip("\n") + f"\n\n## {title}\n\n{after}"


def record_recipe(path: Path, nid: str, key: str, how: str, tags: list[str]) -> str:
    """Add or replace one recipe line under `### nid`; returns 'added' or 'replaced'."""
    text = path.read_text(encoding="utf-8") if path.exists() else f"# Setup recipes\n\nShared install recipes, one `### <id>` block per need (protocol/SETUP.md).\n"
    if path.name == SETUP_FILE:
        text = ensure_section(text, "Install")
    line = f"- {key}: {how}" + (f" ({', '.join(tags)})" if tags else "")
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^###\s+`?{re.escape(nid)}`?\s*$", ln)), None)
    if start is None:
        # new block: at the end of ## Install when the file has one, else at the end of the file
        sec = next((i for i, ln in enumerate(lines) if re.match(r"^##\s+Install\s*$", ln, flags=re.I)), None)
        end = len(lines)
        if sec is not None:
            end = next((i for i in range(sec + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > 0 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = ["", f"### {nid}", "", line, ""]
        result = "added"
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
        hit = next((i for i in range(start + 1, end) if (parse_recipe_line(lines[i]) or {}).get("key") == key), None)
        if hit is not None:
            lines[hit] = line
            result = "replaced"
        else:
            last = max([i for i in range(start + 1, end) if lines[i].strip()] or [start])
            ins = last + 1 if last > start else start + 1
            lines[ins:ins] = ([""] if last == start else []) + [line]
            result = "added"
    path.parent.mkdir(parents=True, exist_ok=True)
    eg.write_lf(path, "\n".join(lines).rstrip("\n") + "\n")
    return result


ATTEMPTS_HEADER = "| date | need | env | route | result | took | notes |\n|---|---|---|---|---|---|---|\n"


def append_row(p: Path, title: str, header: str, row: str) -> None:
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    text = ensure_section(text, title, header)
    if section(text, title).strip() == "":
        text = text.rstrip("\n") + "\n\n" + header
    body = section(text, title)
    i = text.index(body) + len(body.rstrip("\n"))
    text = text[:i] + "\n" + row + text[i:]
    eg.write_lf(p, text.rstrip("\n") + "\n")


def stamp_verified(path: Path, nid: str, key: str, env_key: str) -> bool:
    """Mark one recipe line verified today on this environment, keeping its other tags; False when it is not there."""
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^###\s+`?{re.escape(nid)}`?\s*$", ln)), None)
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    for i in range(start + 1, end):
        r = parse_recipe_line(lines[i])
        if r and r["key"] == key:
            tags = [t for t in r["tags"] if t != "unverified"] + [f"verified {date.today().isoformat()} on {env_key}"]
            lines[i] = f"- {key}: {r['how']} ({', '.join(tags)})"
            eg.write_lf(path, "\n".join(lines).rstrip("\n") + "\n")
            return True
    return False


def log_attempt(d: Path, st: dict, env: dict, nid: str, result: str, route: str = "", took: str = "", note: str = "") -> str:
    p = unit_setup(d, st)
    clean = lambda s: (s or "").replace("|", "/").replace("\n", " ").strip()
    append_row(p, "Attempts", ATTEMPTS_HEADER, f"| {date.today().isoformat()} | {nid} | {env['key']} | {clean(route)} | {result} | {clean(took)} | {clean(note)} |")
    if result in ("granted", "done") and route:
        for book in (p, store_book()):
            if stamp_verified(book, nid, route.lower(), env["key"]):
                return f"logged; recipe {route} stamped verified in {book.name if book == p else 'the store book'}"
        return f"logged; no recipe '{route}' under ### {nid} to stamp (record it with --record {nid} --env {route} --how ... --verified)"
    return "logged"


def log_environment(d: Path, st: dict, env: dict, missing: list[str], note: str = "") -> None:
    p = unit_setup(d, st)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    header = "| date | os | harness | missing | notes |\n|---|---|---|---|---|\n"
    text = ensure_section(text, "Environments met", header)
    if section(text, "Environments met").strip() == "":
        text = text.rstrip("\n") + "\n\n" + header
    row = f"| {date.today().isoformat()} | {env['os']}{'+' + '+'.join(env['extra']) if env['extra'] else ''} | {env['harness']} | {', '.join(missing) or 'none'} | {note} |"
    body = section(text, "Environments met")
    i = text.index(body) + len(body.rstrip("\n"))
    text = text[:i] + "\n" + row + text[i:]
    eg.write_lf(p, text.rstrip("\n") + "\n")
    s = st.setdefault("setup", {})
    envs = s.setdefault("envs", [])
    if env["key"] not in envs:
        envs.append(env["key"])
    s["last_check"] = date.today().isoformat()
    eg.save_state(d, st)


PRIVATE_RE = re.compile(r"([A-Za-z]:\\Users\\|/Users/|/home/)[^\s`'\"]+")


def scrub(how: str) -> tuple[str, bool]:
    home = str(Path.home())
    out = how.replace(home, "~")
    return out, bool(PRIVATE_RE.search(out))


# ---------- output ----------

def render(name: str, env: dict, rows: list[dict], new_env: bool, unit_arg: str) -> str:
    lines = [f"setup {name} · {env['key']}" + ("  (new environment: not in Environments met)" if new_env else "")]
    ok = [r["id"] for r in rows if r["status"] == "ok"]
    if ok:
        lines.append("ok       " + ", ".join(ok))
    for r in rows:
        la = r.get("last_attempt") or {}
        if r["status"] == "ok" and la.get("result") == "pending":
            lines.append(f"GRANTED? {r['id']} works now; its {la.get('date', '')} attempt via {la.get('route') or '?'} is still logged as pending: "
                         f"--attempt {r['id']} --result granted --route {la.get('route') or '<key>'} --took \"...\"")
    counts = {"self": 0, "user": 0, "none": 0, "agent": 0}
    for r in rows:
        if r["status"] == "ok":
            continue
        want = "optional" if r["optional"] else "required"
        if r["status"] == "agent":
            counts["agent"] += 1
            lines.append(f"CHECK    {r['id']} ({r['kind']}) for {r['for']} [{want}]: {r['detail']}")
            for rc in r.get("recipes", [])[:3]:
                lines.append(f"  {rc['key']}: {rc['how']}")
            continue
        counts[r["cls"]] += 1
        lines.append(f"MISSING  {r['id']} ({r['kind']}: {r['detail']}) for {r['for']} [{r['if_missing'] if r['optional'] else want}]")
        la = r.get("last_attempt")
        if la:
            lines.append(f"  last attempt {la.get('date', '?')} via {la.get('route') or '?'}: {la.get('result', '?')}"
                         + (f", took {la['took']}" if la.get("took") else "") + (f" ({la['notes']})" if la.get("notes") else ""))
        if not r["recipes"]:
            route = "way to get this access (the resource owner's docs, the team's request process)" if r["kind"] == "access" else "install route"
            lines.append(f"  no recipe for {env['key']}: find the official {route}, tell the user, then record it with")
            lines.append(f"  evergreen.py setup {unit_arg} --record {r['id']} --env {'any' if r['kind'] == 'access' else env['os']} --how \"...\" [--tags admin] --verified")
        if r["kind"] == "access" and "(403)" in r["detail"]:
            lines.append(f"  access request draft: evergreen.py setup {unit_arg} --request {r['id']}; after sending, --attempt {r['id']} --result pending")
        for rc in r["recipes"][:4]:
            tag = []
            if rc["verified"]:
                tag.append(f"verified {rc['verified']['date']}" + (f" on {rc['verified']['on']}" if rc['verified'].get('on') else ""))
            tag += [t for t in rc["tags"] if t != "unverified"]
            src = "" if rc["source"] == "unit" else f" [{rc['source']} book]"
            lines.append(f"  {rc['cls']:<4} {rc['key']}: {rc['how']}" + (f" ({', '.join(tag)})" if tag else "") + src)
            for k, step in enumerate(rc.get("steps", [])[:10], 1):
                lines.append(f"         {k}. {step}")
    if len(lines) == 1 + (1 if ok else 0) and not any(counts.values()):
        lines.append("all needs present")
    else:
        lines.append(f"next: {counts['self']} the agent can install after saying so, {counts['user']} need the user, "
                     f"{counts['none']} have no recipe here, {counts['agent']} to check by hand")
    return "\n".join(lines)


def write_script(path: Path, env: dict, rows: list[dict], unit_arg: str) -> Path:
    ps = env["os"] == "windows"
    path = path if path.suffix else path.with_suffix(".ps1" if ps else ".sh")
    out = ["#!/usr/bin/env sh" if not ps else "# PowerShell", "# Install what this skill is missing. Generated by evergreen.py setup "
           f"on {date.today().isoformat()} for {env['key']}.", "# Read every line before running it. Lines marked NEEDS YOU are left commented out.", ""]
    if not ps:
        out.insert(1, "set -e")
    for r in rows:
        if r["status"] == "ok" or not r.get("recipes"):
            if r["status"] != "ok":
                out.append(f"# {r['id']}: no recipe for {env['key']} yet ({r['for']})")
            continue
        rc = next((x for x in r["recipes"] if x["commands"]), r["recipes"][0])
        out.append(f"# {r['id']} ({r['kind']}): {r['for']}")
        if not rc["commands"]:
            out.append(f"# NEEDS YOU: {rc['how']}")
        for k, step in enumerate(rc.get("steps", []), 1):
            out.append(f"#   {k}. {step}")
        for c in rc["commands"]:
            user = rc["cls"] == "user" or r["kind"] == "env"
            out.append(("# NEEDS YOU (" + ", ".join(t for t in rc["tags"] if t in USER_TAGS) + "): " if user else "") + c)
        out.append("")
    py = "python" if ps else "python3"
    out.append(f"# then re-check:\n# {py} <plugin root>/scripts/evergreen.py setup {unit_arg}")
    path.parent.mkdir(parents=True, exist_ok=True)
    eg.write_lf(path, "\n".join(out) + "\n")
    return path


REQUEST_TEMPLATE = """Subject: read access request: {id}

Hello <the resource owner or admin>,

Could I have read-only access for the following? It is for {for_}.

- Who: <your account or the identity that will use it>
- Resource: <the exact resource: server and database, the Application Insights or Log Analytics resource, the repository>
- Role: <the narrowest read role{role_hint}>
- Scope: <that resource, or its resource group; not the whole subscription or server>
- Duration: <permanent, until a date, or eligible through PIM / just-in-time activation>
- How I will check it works: a read-only call ({probe})

Thank you."""


def request_draft(n: dict, recipes: list[dict]) -> str:
    lines = [s for r in recipes for s in [r["how"], *r.get("steps", [])]]
    hint = next((s for s in lines if re.search(r"\b(?:[A-Z][\w-]* )*(?:Reader|Viewer|Contributor|Read(?:Only)?)\b", s)), "") or \
        next((s for s in lines if re.search(r"read role|role|grant|scope", s, re.I)), "")  # a named role first
    return REQUEST_TEMPLATE.format(id=n["id"], for_=n["for"] or "<what the skill needs it for>",
                                   role_hint=f"; the recipe says: {hint}" if hint else "",
                                   probe=f"`{n['check']}`" if n["check"] else "the skill's own check")


# ---------- command ----------

def cmd_setup(a):
    env = environment(a.harness, a.os)
    if a.record:
        if not (a.env and a.how):
            print("usage: --record needs --env KEY and --how TEXT", file=sys.stderr)
            raise SystemExit(2)
        how, private = scrub(a.how)
        tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
        if a.verified:
            tags.append(f"verified {date.today().isoformat()} on {env['key']}")
        if a.to == "plugin":
            target = plugin_book()
            if private:
                print("refused: the shared book is public and this recipe names a private path; use --to store", file=sys.stderr)
                raise SystemExit(2)
        elif a.to == "store":
            target = store_book()
        else:
            d, st = eg.load_state(a.unit)
            target = unit_setup(d, st)
        res = record_recipe(target, a.record, a.env.lower(), how, tags)
        print(f"{res} {a.record} · {a.env.lower()} in {target}" + ("  (note: names a private path; keep it out of public books)" if private else ""))
        return
    d, st = eg.load_state(a.unit)
    name = st.get("name", d.name)
    p = unit_setup(d, st)
    if a.attempt:
        if a.result not in RESULTS:
            print(f"usage: --attempt needs --result {'|'.join(RESULTS)}", file=sys.stderr)
            raise SystemExit(2)
        print(f"{a.attempt} · {a.result}: " + log_attempt(d, st, env, a.attempt, a.result, a.route or "", a.took or "", a.note or ""))
        return
    if a.request:
        if not p.exists():
            raise SystemExit(f"no {p.name}")
        need = next((n for n in parse_needs(p.read_text(encoding="utf-8", errors="replace")) if n["id"] == a.request), None)
        if not need:
            print(f"usage: no need '{a.request}' in {p.name}", file=sys.stderr)
            raise SystemExit(2)
        print(request_draft(need, recipes_for(need["id"], load_books(d), env)))
        print(f"\n(fill the <...> parts with the user; after sending: --attempt {need['id']} --result pending --route <key> --note \"request sent to ...\")")
        return
    if a.init:
        if p.exists():
            print(f"exists: {p}")
        else:
            tpl = (eg.plugin_root() / "templates" / "SETUP.md.template").read_text(encoding="utf-8")
            eg.write_lf(p, tpl.replace("{{NAME}}", name).replace("{{MAIN}}", st.get("main", "SKILL.md")))
            print(f"wrote {p}")
        st.setdefault("files", {})["setup"] = p.name
        st.setdefault("setup", {}).setdefault("envs", [])
        eg.save_state(d, st)
        main = d / st.get("main", "SKILL.md")
        if main.exists() and p.name not in main.read_text(encoding="utf-8", errors="replace"):
            print(f"next: link [{p.name}]({p.name}) from {main.name} (its Step 0 and Maintenance section), fill the Needs table")
        return
    if not p.exists():
        print(f"setup {name}: no {p.name} (nothing declared). `--init` writes one from the template.")
        return
    needs = parse_needs(p.read_text(encoding="utf-8", errors="replace"))
    rows = run_checks(d, needs, env, a.skip_access)
    new_env = env["key"] not in envs_met(st)
    missing = [r["id"] for r in rows if r["status"] == "missing"]
    if a.json:
        print(json.dumps({"unit": name, "env": {k: v for k, v in env.items() if k != "facets"}, "new_environment": new_env,
                          "needs": rows}, indent=2, default=str))
    else:
        print(render(name, env, rows, new_env, a.unit))
    if a.script:
        print(f"script: {write_script(Path(a.script), env, rows, a.unit)}")
    if a.log:
        log_environment(d, st, env, missing, a.note or "")
        print(f"logged {env['key']} in {p.name} and evergreen.json setup.envs")
    if any(r["status"] == "missing" and not r["optional"] for r in rows):
        raise SystemExit(1)  # 0 ready, 1 a required need is missing, 2 usage (R-20261002-2)


def add_parsers(sp, common):
    s = sp.add_parser("setup", parents=[common], help="what a unit needs to run here: check, install recipes per environment, record what worked")
    s.add_argument("unit", help="a folder with evergreen.json (with --record --to store|plugin: any value)")
    s.add_argument("--harness", help="agent harness key (default: detected; EVERGREEN_HARNESS overrides)")
    s.add_argument("--os", help="operating system key (default: detected): windows, macos, linux")
    s.add_argument("--json", action="store_true")
    s.add_argument("--script", metavar="PATH", help="write a reviewable install script for the missing needs (.ps1 on Windows, .sh elsewhere)")
    s.add_argument("--log", action="store_true", help="record this environment and what is missing in SETUP.md and evergreen.json")
    s.add_argument("--note", help="with --log or --attempt: a short note for the row")
    s.add_argument("--init", action="store_true", help="write SETUP.md from the template and add it to the unit's files map")
    s.add_argument("--record", metavar="ID", help="add or replace the recipe for this need under --env")
    s.add_argument("--env", metavar="KEY", help="with --record: windows, macos, linux, wsl, a harness, a package manager, a/b, or any")
    s.add_argument("--how", help="with --record: backticked commands joined by 'then', or prose steps")
    s.add_argument("--tags", help="with --record: comma list of admin, manual, large, secret, paid")
    s.add_argument("--verified", action="store_true", help="with --record: it just worked here; stamps today and this environment")
    s.add_argument("--to", choices=("unit", "store", "plugin"), default="unit", help="with --record: which book (default: the unit's SETUP.md)")
    s.add_argument("--attempt", metavar="ID", help="log how getting this need went, in the Attempts table")
    s.add_argument("--result", help="with --attempt: " + ", ".join(RESULTS))
    s.add_argument("--route", metavar="KEY", help="with --attempt: the recipe key that was followed; granted or done stamps it verified")
    s.add_argument("--took", help="with --attempt: how long it took, e.g. '10 min' or '2 days (ticket)'")
    s.add_argument("--skip-access", action="store_true", help="do not run the read-only access probes")
    s.add_argument("--request", metavar="ID", help="print a least-privilege access request draft for this need, to fill in with the user and send")
    s.set_defaults(fn=cmd_setup)
