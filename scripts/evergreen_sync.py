#!/usr/bin/env python3
"""evergreen_sync.py - keep one trunk current when the plugin updates itself elsewhere.

Baseline snapshots, update bundles (digest + unified diff), an email transport
ladder, and a merge that folds a bundle into the trunk. Pure standard library.
Imported by evergreen.py (commands: baseline, diff, notify, merge, where); it can
also run on its own: python evergreen_sync.py <cmd> ...

Flow
  trunk   : pack            -> MANIFEST.json in the archive, baseline taken, zip kept in EVERGREEN_HOME/packs/
  install : baseline        -> snapshot of the installed files (from the tree, or --from the zip)
  anywhere: diff            -> EVERGREEN_HOME/outbox/<stamp>/ {UPDATE.md, changes.patch, manifest.json}
            notify          -> email the bundle to notify.to via outlook | graph | smtp; outbox always
  trunk   : merge <bundle>  -> 3-way per file (git when possible), entry union for the logs, JSON merge for state

Everything fails soft (prints a note, exits 0) so hooks never break a session.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evergreen as eg  # noqa: E402

LOG_FILES = {"CHANGELOG.md", "RESEARCH.md", "LEARNINGS.md", "TESTS.md"}
ENTRY_HEAD_RE = re.compile(r"^###\s+((?:R|C|T)-\d{8}-\d+|L-\d{3,})\b")  # R-, C-, T- share the dated scheme; L- is a running number
PATCH_BEGIN = "-----BEGIN EVERGREEN PATCH-----"
PATCH_END = "-----END EVERGREEN PATCH-----"
TRANSPORTS = ("outlook", "graph", "smtp", "compose-url")
PROTECTED = {"evergreen.config.json"}          # never changed by a merge: it holds the recipient and machine paths
CODE_DIRS = ("scripts/", "hooks/", ".claude-plugin/")  # merged only with --allow-code

NOTIFY_DEFAULTS = {
    "auto": True,
    "to": None,
    "subject_prefix": "[evergreen]",
    "transports": ["outlook", "graph", "smtp"],
    "report_trunk": False,
    "env_name": None,
    "inline_patch_max_kb": 48,
    "attach_pack": True,
    "pack_split_kb": 0,
    "outbox_copy_to": None,
    "smtp": {"host": "smtp.gmail.com", "port": 587, "user_env": "EVERGREEN_SMTP_USER",
             "password_env": "EVERGREEN_SMTP_PASS", "password_file": None, "from_env": "EVERGREEN_SMTP_FROM"},
    "graph": {"timeout": 60},
    "outlook": {"timeout": 45},
}


# ---------- config and small helpers ----------

def per_os(v):
    if isinstance(v, dict):
        return v.get(os.name) or v.get("default")
    return v


def notify_config() -> dict:
    cfg = json.loads(json.dumps(NOTIFY_DEFAULTS))
    p = eg.plugin_root() / "evergreen.config.json"
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8")).get("notify") or {}
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    env_t = os.environ.get("EVERGREEN_NOTIFY_TRANSPORTS")  # machine-local override, set by the user
    if env_t is not None:
        cfg["transports"] = [t.strip() for t in env_t.split(",") if t.strip()]
    return cfg


def is_trunk() -> bool:
    """True when this plugin folder is the canonical source named in its own evergreen.json."""
    try:
        _, st = eg.load_state(eg.plugin_root())
        src = st.get("source")
        if not src:
            return False
        if os.name != "nt" and eg._looks_windows(str(src)):
            return False
        return Path(str(src)).resolve() == eg.plugin_root().resolve()
    except Exception:
        return False


def safe_rel(rel: str) -> bool:
    """A patch path may only name a file inside the tree: relative, no '..', no '.git', no drive or root."""
    r = rel.replace("\\", "/")
    if not r or r.startswith("/") or r.startswith("~") or re.match(r"^[A-Za-z]:", r):
        return False
    parts = r.split("/")
    if any(p in ("", ".", "..") for p in parts) or parts[0] == ".git" or any(p.startswith(".git") for p in parts):
        return False
    return True


def inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def env_name(cfg: dict | None = None) -> str:
    cfg = cfg or notify_config()
    name = os.environ.get("EVERGREEN_ENV") or per_os(cfg.get("env_name"))
    if not name:
        try:
            name = socket.gethostname()
        except Exception:
            name = "unknown"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-") or "unknown"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_blob(b: bytes) -> str:
    h = hashlib.sha1()
    h.update(f"blob {len(b)}\0".encode())
    h.update(b)
    return h.hexdigest()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


def is_text(b: bytes) -> bool:
    if b"\0" in b[:8000]:
        return False
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def lines_of(b: bytes) -> list[str]:
    return b.decode("utf-8", errors="replace").splitlines()


def eol_of(b: bytes | None) -> str:
    if b and b"\r\n" in b:
        return "\r\n"
    return "\n"


def join_lines(lines: list[str], eol: str, trailing: bool = True) -> str:
    if not lines:
        return ""
    return eol.join(lines) + (eol if trailing else "")


def home() -> Path:
    return eg.evergreen_home()


def outbox_dir() -> Path:
    return home() / "outbox"


def baseline_dir() -> Path:
    """One baseline per plugin folder, so two copies sharing a store do not overwrite each other."""
    key = hashlib.sha1(str(eg.plugin_root().resolve()).encode("utf-8")).hexdigest()[:8]
    return home() / "baselines" / f"evergreen-{key}"


def current_files() -> dict[str, bytes]:
    out = {}
    for p, rel in eg.iter_plugin_files():
        out[rel.as_posix()] = p.read_bytes()
    return out


def git_ok(repo: Path) -> bool:
    return eg.git(["rev-parse", "--is-inside-work-tree"], repo) == "true"


# ---------- baseline ----------

def load_baseline() -> dict | None:
    p = baseline_dir() / "baseline.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def baseline_bytes(rel: str) -> bytes | None:
    p = baseline_dir() / "files" / rel
    return p.read_bytes() if p.exists() else None


def files_from_zip(zpath: Path) -> tuple[dict[str, bytes], str | None]:
    """Files inside a pack archive (folder form or flat .plugin), keyed by plugin-relative posix path."""
    files, pack_id = {}, None
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        prefix = "evergreen/" if any(n.startswith("evergreen/") for n in names) else ""
        for n in names:
            if n.endswith("/"):
                continue
            # the archive's own convenience files sit beside the plugin folder, not inside it; a baseline that
            # counted them reported them deleted on the next diff (L-014, same edit). templates/INSTALL-PROMPT.txt,
            # which is inside the folder, must survive this.
            if prefix and not n.startswith(prefix) and n in ("INSTALL.txt", "INSTALL-PROMPT.txt"):
                continue
            rel = n[len(prefix):] if n.startswith(prefix) else n
            if not rel or rel in ("INSTALL.txt", "INSTALL-PROMPT.txt"):
                continue
            data = z.read(n)
            if rel == "MANIFEST.json":
                try:
                    pack_id = json.loads(data.decode("utf-8")).get("pack_id")
                except Exception:
                    pass
                continue
            if rel.endswith(".txt") and Path(rel[:-4]).suffix.lower() in eg.MAIL_BLOCKED:
                rel = rel[:-4]  # the --mail form stores blocked script types as name.ext.txt
            files[rel] = data
    return files, pack_id


def manifest_pack_id() -> str | None:
    mp = eg.plugin_root() / "MANIFEST.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8")).get("pack_id")
        except Exception:
            return None
    return None


def take_baseline(note: str = "", pack_id: str | None = None, files: dict[str, bytes] | None = None) -> dict:
    files = files if files is not None else current_files()
    d = baseline_dir()
    d.mkdir(parents=True, exist_ok=True)
    fdir = d / "files"
    tmp = d / "files.new"
    if tmp.exists():
        shutil.rmtree(tmp)
    meta = {"taken": datetime.now().strftime("%Y-%m-%dT%H:%M"), "version": eg.plugin_version(), "pack_id": pack_id,
            "plugin_root": str(eg.plugin_root().resolve()), "env": env_name(), "note": note, "files": {}}
    for rel, data in sorted(files.items()):
        target = tmp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        meta["files"][rel] = {"sha256": sha256(data), "blob": git_blob(data)}
    tmp.mkdir(parents=True, exist_ok=True)
    if fdir.exists():
        shutil.rmtree(fdir)
    tmp.rename(fdir)
    (d / "baseline.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def advance_baseline_with(bundle_dir: Path, note: str) -> None:
    """Baseline = old baseline overlaid with the bundle's snapshot of the files it changed (not the live tree,
    which may have moved on since the bundle was built)."""
    base = load_baseline() or {"files": {}}
    files = {rel: baseline_bytes(rel) for rel in base.get("files", {})}
    files = {k: v for k, v in files.items() if v is not None}
    snap = bundle_dir / "files"
    if snap.exists():
        for p in snap.rglob("*"):
            if p.is_file():
                files[p.relative_to(snap).as_posix()] = p.read_bytes()
    dl = bundle_dir / "deleted.json"
    if dl.exists():
        try:
            for rel in json.loads(dl.read_text(encoding="utf-8")):
                files.pop(rel, None)
        except Exception:
            pass
    take_baseline(note=note, pack_id=base.get("pack_id") or manifest_pack_id(), files=files)


# ---------- diff and bundle ----------

def unified(rel: str, base: bytes | None, new: bytes | None) -> str:
    """git-style unified diff for one file (index line carries blob ids so `git apply --3way` can use history)."""
    a = f"a/{rel}"
    b = f"b/{rel}"
    head = [f"diff --git {a} {b}"]
    if base is not None and new is not None and (not is_text(base) or not is_text(new)):
        return "\n".join(head + [f"index {git_blob(base)[:12]}..{git_blob(new)[:12]}", f"Binary files {a} and {b} differ"]) + "\n"
    if base is None:
        head.append("new file mode 100644")
        head.append(f"index {'0' * 12}..{git_blob(new or b'')[:12]}")
        old_lines, from_name = [], "/dev/null"
    else:
        old_lines, from_name = lines_of(base), a
    if new is None:
        head.append("deleted file mode 100644")
        head.append(f"index {git_blob(base or b'')[:12]}..{'0' * 12}")
        new_lines, to_name = [], "/dev/null"
    else:
        new_lines, to_name = lines_of(new), b
    if base is not None and new is not None:
        head.append(f"index {git_blob(base)[:12]}..{git_blob(new)[:12]} 100644")
    body = list(difflib.unified_diff(old_lines, new_lines, fromfile=from_name, tofile=to_name, n=3, lineterm=""))
    if not body:
        return ""
    return "\n".join(head + body) + "\n"


def entry_heads(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if ENTRY_HEAD_RE.match(line):
            out.append(line.strip())
    return out


def new_entry_heads(base: bytes | None, new: bytes) -> list[str]:
    old = set(entry_heads(base.decode("utf-8", errors="replace"))) if base else set()
    ids_old = {ENTRY_HEAD_RE.match(h).group(1) for h in old}
    return [h for h in entry_heads(new.decode("utf-8", errors="replace")) if ENTRY_HEAD_RE.match(h).group(1) not in ids_old]


def state_delta(base: bytes | None, new: bytes) -> list[str]:
    try:
        b = json.loads(base.decode("utf-8")) if base else {}
        n = json.loads(new.decode("utf-8"))
    except Exception:
        return ["(state file not parseable)"]
    out = []
    for k in ("tier", "interval_days", "last_checked", "next_due", "verify_at_use", "contradiction"):
        if b.get(k) != n.get(k):
            out.append(f"{k}: {b.get(k)} -> {n.get(k)}")
    hb, hn = b.get("history") or [], n.get("history") or []
    if len(hn) > len(hb):
        for h in hn[len(hb):]:
            out.append(f"history: {h.get('date')} m={h.get('m')} {h.get('note', '')}".rstrip())
    if (b.get("counts") or {}) != (n.get("counts") or {}):
        out.append(f"counts: {n.get('counts')}")
    t = n.get("tests") or {}
    if t != (b.get("tests") or {}):
        out.append(f"tests: last_run {t.get('last_run')} {t.get('passed')}/{t.get('cases')} passed, failing {t.get('failing')}")
    return out


def compute_changes(base_files: dict[str, bytes], cur: dict[str, bytes]) -> list[dict]:
    changes = []
    for rel in sorted(set(base_files) | set(cur)):
        base, new = base_files.get(rel), cur.get(rel)
        if base == new:
            continue
        if base is not None and new is not None and is_text(base) and is_text(new) and lines_of(base) == lines_of(new):
            continue  # line-ending only; not a change worth reporting
        status = "added" if base is None else "deleted" if new is None else "modified"
        c = {"path": rel, "status": status,
             "base_sha256": sha256(base) if base is not None else None, "new_sha256": sha256(new) if new is not None else None,
             "base_blob": git_blob(base) if base is not None else None, "new_blob": git_blob(new) if new is not None else None}
        if new is not None and is_text(new) and (base is None or is_text(base)):
            ol, nl = (lines_of(base) if base is not None else []), lines_of(new)
            sm = difflib.SequenceMatcher(None, ol, nl)
            plus = minus = 0
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag in ("replace", "delete"):
                    minus += i2 - i1
                if tag in ("replace", "insert"):
                    plus += j2 - j1
            c["plus"], c["minus"] = plus, minus
            if Path(rel).name in LOG_FILES:
                c["entries"] = new_entry_heads(base, new)
            if Path(rel).name == "evergreen.json":
                c["state"] = state_delta(base, new)
                try:
                    c["state_new"] = json.loads(new.decode("utf-8"))
                except Exception:
                    pass
        changes.append(c)
    return changes


def build_update_md(changes: list[dict], base_meta: dict | None, bundle_id: str, env: str, patch_bytes: int) -> str:
    ver = eg.plugin_version()
    added = sum(1 for c in changes if c["status"] == "added")
    mod = sum(1 for c in changes if c["status"] == "modified")
    dele = sum(1 for c in changes if c["status"] == "deleted")
    base_desc = "none"
    if base_meta:
        base_desc = f"taken {base_meta.get('taken')} (v{base_meta.get('version')}" + (f", pack {base_meta.get('pack_id')})" if base_meta.get("pack_id") else ")")
    lines = [f"# Evergreen update from {env} · {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             f"Bundle `{bundle_id}`. Plugin version {ver}. Baseline: {base_desc}. {len(changes)} file(s) changed "
             f"(+{added} added, ~{mod} modified, -{dele} deleted); patch {patch_bytes // 1024 + 1} KB.", ""]
    for label, fname in (("New changelog entries", "CHANGELOG.md"), ("New research findings", "RESEARCH.md"), ("New learnings", "LEARNINGS.md"),
                         ("New test runs", "TESTS.md")):
        rows = []
        for c in changes:
            if Path(c["path"]).name == fname:
                for h in c.get("entries") or []:
                    rows.append(f"- {h.lstrip('# ').strip()}" + (f"  ({c['path']})" if "/" in c["path"] else ""))
        if rows:
            lines += [f"## {label}", ""] + rows + [""]
    state_rows = []
    for c in changes:
        if c.get("state"):
            state_rows += [f"- {c['path']}: " + "; ".join(c["state"])]
    if state_rows:
        lines += ["## State", ""] + state_rows + [""]
    lines += ["## Files", ""]
    for c in changes:
        mark = {"added": "A", "modified": "M", "deleted": "D"}[c["status"]]
        stat = f" (+{c['plus']} -{c['minus']})" if "plus" in c else ""
        lines.append(f"- {mark} {c['path']}{stat}")
    lines += ["", "## How to merge at the trunk", "",
              "`python <trunk>/scripts/evergreen.py merge` (`python3` on macOS and Linux) ` <this bundle folder, its changes.patch, or this email saved as .txt>` "
              "then `pack` and reinstall elsewhere. The patch is attached and, when small, inline below between the BEGIN/END markers.", ""]
    return "\n".join(lines)


def ensure_baseline(cur: dict[str, bytes]) -> tuple[dict | None, str]:
    """The baseline to diff against. An install that still matches its shipped MANIFEST.json baselines itself."""
    base_meta = load_baseline()
    note = ""
    mp = eg.plugin_root() / "MANIFEST.json"
    if mp.exists():
        try:
            man = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            man = None
        if man and (base_meta is None or base_meta.get("pack_id") != man.get("pack_id")):
            pristine = set(cur) == set(man.get("files", {})) and all(sha256(cur[k]) == v for k, v in man["files"].items())
            if pristine:
                base_meta = take_baseline(note=f"auto from MANIFEST.json ({man.get('pack_id')})", pack_id=man.get("pack_id"), files=cur)
                note = f"baseline taken from the pristine install ({man.get('pack_id')})"
            elif base_meta is None:
                raise RuntimeError(f"installed from pack {man.get('pack_id')} but files already differ and no baseline exists; "
                                   "run `evergreen.py baseline --from <that pack zip>`")
            else:
                note = (f"baseline is from pack {base_meta.get('pack_id')} but this install is pack {man.get('pack_id')}; "
                        "the diff may include the upgrade itself (run `baseline --from <pack zip>` to fix)")
    if base_meta is None:
        raise RuntimeError("no baseline for this install; run `evergreen.py baseline` (or `baseline --from <pack zip>`) first")
    return base_meta, note


def build_bundle(out_dir: Path | None = None, quiet: bool = False) -> dict | None:
    """Diff the plugin tree against its baseline and write UPDATE.md, changes.patch, manifest.json. None when nothing changed."""
    cur = current_files()
    base_meta, note = ensure_baseline(cur)
    if note and not quiet:
        print(f"[evergreen] {note}", file=sys.stderr)
    base_files = {rel: baseline_bytes(rel) for rel in base_meta.get("files", {})}
    base_files = {k: v for k, v in base_files.items() if v is not None}
    changes = compute_changes(base_files, cur)
    if not changes:
        return None
    patch = "".join(unified(c["path"], base_files.get(c["path"]), cur.get(c["path"])) for c in changes)
    content_hash = sha256(patch.encode("utf-8"))
    env = env_name()
    root = out_dir or outbox_dir()
    d = None
    if root.exists():  # reuse an unsent bundle with this exact content instead of stamping a new folder
        for old in sorted(root.iterdir()):
            s = old / "STATUS"
            if old.name.endswith(content_hash[:8]) and s.exists() and s.read_text(encoding="utf-8").startswith("unsent"):
                d = old
                break
    bundle_id = d.name if d else f"{now_stamp()}-{env}-{content_hash[:8]}"
    d = d or root / bundle_id
    d.mkdir(parents=True, exist_ok=True)
    update = build_update_md(changes, base_meta, bundle_id, env, len(patch.encode("utf-8")))
    manifest = {"bundle_id": bundle_id, "env": env, "date": datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "plugin_version": eg.plugin_version(), "content_hash": content_hash,
                "baseline": {k: base_meta.get(k) for k in ("taken", "version", "pack_id", "env")},
                "files": [{k: v for k, v in c.items() if k not in ("entries", "state", "state_new")} for c in changes],
                "state": {c["path"]: c["state_new"] for c in changes if c.get("state_new")}}
    (d / "UPDATE.md").write_text(update, encoding="utf-8")
    with open(d / "changes.patch", "w", encoding="utf-8", newline="\n") as f:  # Path.write_text(newline=) is 3.10+
        f.write(patch)
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (d / "STATUS").write_text("unsent\n", encoding="utf-8")
    # snapshot of the changed files as they are now, so a later --mark-sent advances the baseline to exactly this
    snap = d / "files"
    if snap.exists():
        shutil.rmtree(snap)
    for c in changes:
        if c["status"] != "deleted":
            t = snap / c["path"]
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(cur[c["path"]])
    (d / "deleted.json").write_text(json.dumps([c["path"] for c in changes if c["status"] == "deleted"]) + "\n", encoding="utf-8")
    return {"dir": d, "id": bundle_id, "patch": d / "changes.patch", "update": d / "UPDATE.md", "manifest": d / "manifest.json",
            "content_hash": content_hash, "n": len(changes), "changes": changes, "env": env}


# ---------- notify ----------

def notify_state_path() -> Path:
    return home() / "notify.json"


def load_notify_state() -> dict:
    p = notify_state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last": None, "log": []}


def record_send(bundle_dir: Path, content_hash: str, transport: str, status: str, subject: str, detail: str = "") -> None:
    st = load_notify_state()
    entry = {"date": datetime.now().strftime("%Y-%m-%dT%H:%M"), "bundle_id": bundle_dir.name, "content_hash": content_hash,
             "transport": transport, "status": status, "subject": subject, "detail": detail[:300]}
    st.setdefault("log", []).append(entry)
    st["log"] = st["log"][-100:]
    if status == "sent":
        st["last"] = entry
    notify_state_path().parent.mkdir(parents=True, exist_ok=True)
    notify_state_path().write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    try:
        (bundle_dir / "STATUS").write_text(f"{status} via {transport} {entry['date']}\n{detail}\n", encoding="utf-8")
    except Exception:
        pass


def compose(bundle: dict, cfg: dict) -> tuple[str, str, list[Path]]:
    """Subject, body, attachments for an update email. The body opens with the one-paste install prompt, then the
    digest and (when small) the inline patch. With notify.attach_pack the current tree is packed in its mail-safe form
    into the bundle folder and attached, so the email alone is enough to install or upgrade on another machine (L-012);
    notify.pack_split_kb > 0 also attaches .partNN pieces for routes with a small per-attachment ceiling (L-013)."""
    update = bundle["update"].read_text(encoding="utf-8")
    patch = bundle["patch"].read_text(encoding="utf-8")
    ver = eg.plugin_version()
    subject = (f"{cfg.get('subject_prefix') or '[evergreen]'} update from {bundle['env']}: v{ver}, {bundle['n']} file(s) "
               f"({datetime.now().strftime('%Y-%m-%d')})")
    attachments: list[Path] = []
    pack_note = ""
    if cfg.get("attach_pack", True):
        try:
            made = eg.pack(Path(bundle["dir"]), mail=True, git_tag=False, split_kb=int(cfg.get("pack_split_kb") or 0), after=False)
            attachments += [p for p in made if not p.name.endswith("-INSTALL-PROMPT.txt")]
            pieces = [p for p in attachments if ".part" in p.suffix]
            pack_note = (f"Attached: {attachments[0].name} (the whole plugin, {attachments[0].stat().st_size // 1024} KB)"
                         + (f", also as {len(pieces)} pieces" if pieces else "") + ".")
            subject += " + full plugin"
        except Exception as e:
            pack_note = f"(The full plugin archive could not be built here: {e}. The patch below still merges at the trunk.)"
    body = ("TO INSTALL OR UPGRADE: save the attachments to one folder, paste the prompt below into Claude Code, "
            "and replace its one placeholder with that folder's path.\n" + (pack_note + "\n" if pack_note else "") + "\n"
            + eg.install_prompt(ver) + "\n" + "=" * 72 + "\n\n" + update)
    if len(patch.encode("utf-8")) <= int(cfg.get("inline_patch_max_kb") or 48) * 1024:
        body += "\n" + PATCH_BEGIN + "\n" + patch + ("" if patch.endswith("\n") else "\n") + PATCH_END + "\n"
    else:
        body += "\n(The patch is larger than the inline limit; it is attached as changes.patch.)\n"
    return subject, body, attachments + [bundle["patch"], bundle["manifest"], bundle["update"]]


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def run_powershell(script: str, timeout: int) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "not Windows"
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return False, "powershell not found"
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:  # BOM: PS 5.1 reads BOM-less as ANSI
        f.write(script)
        path = f.name
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
                           capture_output=True, text=True, timeout=timeout, creationflags=0x08000000)  # CREATE_NO_WINDOW
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        ok = r.returncode == 0 and "OK" in out.splitlines()[-1:] if out else False
        return ok, (out + ("\n" + err if err else "")).strip()[-600:]
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def _body_file(body: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(body)
        return f.name


def send_outlook(subject: str, body: str, to: str, attachments: list[Path], cfg: dict) -> tuple[bool, str]:
    """Classic Outlook only (the new Outlook has no COM object model)."""
    bf = _body_file(body)
    atts = ", ".join(_ps_quote(str(a)) for a in attachments)
    script = f"""$ErrorActionPreference = 'Stop'
try {{
  $o = New-Object -ComObject Outlook.Application
  $m = $o.CreateItem(0)
  $m.To = {_ps_quote(to)}
  $m.Subject = {_ps_quote(subject)}
  $m.Body = Get-Content -Raw -Encoding UTF8 {_ps_quote(bf)}
  foreach ($a in @({atts})) {{ [void]$m.Attachments.Add($a) }}
  $m.Send()
  Write-Output 'OK'
}} catch {{ Write-Output ("outlook: " + $_.Exception.Message); exit 1 }}
"""
    try:
        return run_powershell(script, int(cfg.get("outlook", {}).get("timeout", 45)))
    finally:
        try:
            os.unlink(bf)
        except Exception:
            pass


def send_graph(subject: str, body: str, to: str, attachments: list[Path], cfg: dict) -> tuple[bool, str]:
    """Microsoft Graph via the Graph PowerShell SDK (delegated Mail.Send; a cached token from an earlier
    interactive `Connect-MgGraph -Scopes Mail.Send` is required, since this runs non-interactively)."""
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / ".IdentityService" / "mg.msal.cache.bin"
    if os.name == "nt" and not cache.exists():
        return False, "no Graph token cache; run `Connect-MgGraph -Scopes Mail.Send` once interactively"
    bf = _body_file(body)
    atts = ", ".join(_ps_quote(str(a)) for a in attachments)
    script = f"""$ErrorActionPreference = 'Stop'
try {{
  Import-Module Microsoft.Graph.Users.Actions -ErrorAction Stop
  Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
  $ctx = Get-MgContext
  if (-not $ctx) {{ Connect-MgGraph -Scopes 'Mail.Send' -NoWelcome -ErrorAction Stop | Out-Null; $ctx = Get-MgContext }}
  if (-not $ctx) {{ throw 'no Graph context; run Connect-MgGraph -Scopes Mail.Send once interactively' }}
  $body = Get-Content -Raw -Encoding UTF8 {_ps_quote(bf)}
  $atts = @()
  foreach ($a in @({atts})) {{
    $bytes = [IO.File]::ReadAllBytes($a)
    $atts += @{{ '@odata.type' = '#microsoft.graph.fileAttachment'; name = [IO.Path]::GetFileName($a); contentType = 'text/plain'; contentBytes = [Convert]::ToBase64String($bytes) }}
  }}
  $msg = @{{ subject = {_ps_quote(subject)}; body = @{{ contentType = 'Text'; content = $body }};
            toRecipients = @(@{{ emailAddress = @{{ address = {_ps_quote(to)} }} }}); attachments = $atts }}
  Send-MgUserMail -UserId $ctx.Account -BodyParameter @{{ message = $msg; saveToSentItems = $true }} -ErrorAction Stop
  Write-Output 'OK'
}} catch {{ Write-Output ("graph: " + $_.Exception.Message); exit 1 }}
"""
    try:
        return run_powershell(script, int(cfg.get("graph", {}).get("timeout", 60)))
    finally:
        try:
            os.unlink(bf)
        except Exception:
            pass


def smtp_credentials(cfg: dict) -> tuple[str | None, str | None, str | None, str]:
    s = cfg.get("smtp") or {}
    user = os.environ.get(s.get("user_env") or "EVERGREEN_SMTP_USER")
    pw = os.environ.get(s.get("password_env") or "EVERGREEN_SMTP_PASS")
    pf = per_os(s.get("password_file"))
    if not pw and pf:
        try:
            pw = Path(os.path.expandvars(str(pf))).expanduser().read_text(encoding="utf-8").strip()
        except Exception:
            pw = None
    sender = os.environ.get(s.get("from_env") or "EVERGREEN_SMTP_FROM") or user
    why = "" if (user and pw) else f"set {s.get('user_env')} and {s.get('password_env')} (or notify.smtp.password_file)"
    return user, pw, sender, why


def send_smtp(subject: str, body: str, to: str, attachments: list[Path], cfg: dict) -> tuple[bool, str]:
    import smtplib
    from email.message import EmailMessage
    s = cfg.get("smtp") or {}
    user, pw, sender, why = smtp_credentials(cfg)
    if not (user and pw):
        return False, why
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(body)
    for a in attachments:
        sub = "json" if a.suffix == ".json" else "plain"
        main = "application" if sub == "json" else "text"
        msg.add_attachment(a.read_bytes(), maintype=main, subtype=sub, filename=a.name)
    host, port = s.get("host") or "smtp.gmail.com", int(s.get("port") or 587)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as sm:
                sm.login(user, pw)
                sm.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as sm:
                sm.ehlo()
                sm.starttls()
                sm.ehlo()
                sm.login(user, pw)
                sm.send_message(msg)
        return True, f"{host}:{port} as {user}"
    except Exception as e:
        return False, f"{host}:{port}: {e}"


def compose_url(subject: str, body: str, to: str, bundle_dir: Path, limit: int = 1900) -> str:
    short = body.split(PATCH_BEGIN)[0].strip()
    tail = f"\n\n(Full bundle: {bundle_dir})"
    url = ""
    while True:
        q = urllib.parse.urlencode({"view": "cm", "fs": "1", "to": to, "su": subject, "body": short + tail})
        url = "https://mail.google.com/mail/?" + q
        if len(url) <= limit or len(short) < 80:
            return url
        short = short[: int(len(short) * 0.8)].rstrip() + "\n..."


def open_compose_url(subject: str, body: str, to: str, bundle_dir: Path) -> tuple[bool, str]:
    import webbrowser
    url = compose_url(subject, body, to, bundle_dir)
    try:
        ok = webbrowser.open(url)
    except Exception as e:
        return False, str(e)
    return (True, "compose window opened; attach changes.patch and click Send") if ok else (False, "no browser could be opened")


def copy_to_outbox_mirror(bundle: dict, cfg: dict, extra: list[Path] | None = None) -> str | None:
    """Mirror the bundle into a synced folder so an agent can attach it from Drive without an upload. The mirror
    carries everything the recipient needs, the archive and install prompt included, not just the digest and patch
    (L-014): an agent attaching from the mirror is the normal route when no transport works."""
    target = per_os(cfg.get("outbox_copy_to"))
    if not target:
        return None
    if os.name != "nt" and eg._looks_windows(str(target)):
        return None
    t = Path(os.path.expandvars(str(target))).expanduser()
    try:
        if not t.parent.exists():
            return None
        dest = t / bundle["id"]
        dest.mkdir(parents=True, exist_ok=True)
        seen = set()
        for f in list(extra or []) + [bundle["update"], bundle["patch"], bundle["manifest"]]:
            f = Path(f)
            if f.name in seen or not f.is_file():
                continue
            seen.add(f.name)
            shutil.copy2(f, dest / f.name)
        return str(dest)
    except Exception:
        return None


def load_bundle(d: Path) -> dict:
    d = Path(d)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return {"dir": d, "id": man["bundle_id"], "patch": d / "changes.patch", "update": d / "UPDATE.md", "manifest": d / "manifest.json",
            "content_hash": man.get("content_hash"), "n": len(man.get("files", [])), "env": man.get("env")}


def detach_self(args: list[str]) -> None:
    """Re-run evergreen.py with `args` as a detached background process (for 1.5 s hook budgets)."""
    log = home() / "notify.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "evergreen.py")] + args
    kw: dict = {"stdin": subprocess.DEVNULL, "close_fds": True}
    lf = open(log, "a", encoding="utf-8")
    lf.write(f"\n[{datetime.now().strftime('%Y-%m-%dT%H:%M')}] detached: {' '.join(args)}\n")
    kw["stdout"], kw["stderr"] = lf, subprocess.STDOUT
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def notify(if_changed: bool = False, transport: str | None = None, to: str | None = None, dry_run: bool = False,
           resend: Path | None = None, mark_sent: Path | None = None, via: str | None = None, out_dir: Path | None = None,
           from_hook: bool = False) -> str:
    if update_transport() == "git" and not (mark_sent or resend or transport):
        return publish(if_changed=if_changed, dry_run=dry_run, from_hook=from_hook)  # protocol 1.4: git first
    cfg = notify_config()
    to = to or cfg.get("to")
    if mark_sent:
        b = load_bundle(mark_sent)
        record_send(b["dir"], b["content_hash"] or "", via or "agent", "sent", f"(sent by agent via {via or 'unknown'})")
        advance_baseline_with(b["dir"], note=f"after send of {b['id']}")
        return f"marked {b['id']} sent via {via or 'agent'}; baseline advanced"
    if if_changed and not cfg.get("auto"):
        return ""  # unattended entry points respect notify.auto; an explicit `notify` still sends
    gate = contribute_gate(if_changed or from_hook)
    if gate is not None:
        return gate
    if from_hook and is_trunk() and not cfg.get("report_trunk"):
        return ""  # the trunk does not mail itself at every session end while being edited; checked/bump/explicit still do
    if not to:
        return "notify.to is not set in evergreen.config.json; nothing sent"
    if resend:
        bundle = load_bundle(resend)
    else:
        bundle = build_bundle(out_dir=out_dir)
        if bundle is None:
            return "" if if_changed else "no changes since the baseline; nothing to send"
    st = load_notify_state()
    last = st.get("last") or {}
    if not resend and last.get("content_hash") == bundle["content_hash"]:
        try:
            shutil.rmtree(bundle["dir"])
        except Exception:
            pass
        return "" if if_changed else f"already sent this exact content ({last.get('date')}, {last.get('bundle_id')}); nothing to send"
    subject, body, attachments = compose(bundle, cfg)
    if dry_run:
        return f"dry run: would send '{subject}' to {to} with {[a.name for a in attachments]} via {transport or cfg.get('transports')}; bundle {bundle['dir']}"
    mirror = copy_to_outbox_mirror(bundle, cfg, extra=attachments)
    ladder = [transport] if transport else list(cfg.get("transports") or [])
    tried = []
    for t in ladder:
        if t == "outlook":
            ok, detail = send_outlook(subject, body, to, attachments, cfg)
        elif t == "graph":
            ok, detail = send_graph(subject, body, to, attachments, cfg)
        elif t == "smtp":
            ok, detail = send_smtp(subject, body, to, attachments, cfg)
        elif t == "compose-url":
            ok, detail = open_compose_url(subject, body, to, bundle["dir"])
            if ok:
                record_send(bundle["dir"], bundle["content_hash"], t, "pending-human", subject, detail)
                return f"compose window opened for {to}; {detail}. Bundle {bundle['dir']} (mark it sent with `notify --mark-sent <dir> --via compose-url`)"
        else:
            ok, detail = False, "unknown transport"
        tried.append(f"{t}: {detail}")
        if ok:
            record_send(bundle["dir"], bundle["content_hash"], t, "sent", subject, detail)
            advance_baseline_with(bundle["dir"], note=f"after send of {bundle['id']}")
            return f"sent via {t} to {to}: {subject}" + (f" (also mirrored to {mirror})" if mirror else "")
    record_send(bundle["dir"], bundle["content_hash"], "none", "unsent", subject, "; ".join(tried))
    return (f"unsent: no transport worked ({'; '.join(tried) or 'no transports configured'}). Bundle at {bundle['dir']}"
            + (f", mirrored to {mirror}" if mirror else "")
            + ". An agent can send it (Gmail connector, Chrome) and then run `notify --mark-sent <bundle> --via <name>`.")


# ---------- patch parsing and applying ----------

class Hunk:
    __slots__ = ("old_start", "old_len", "new_start", "new_len", "lines")

    def __init__(self, old_start, old_len, new_start, new_len):
        self.old_start, self.old_len, self.new_start, self.new_len = old_start, old_len, new_start, new_len
        self.lines: list[tuple[str, str]] = []  # (tag ' ', '-', '+', text)

    def old_lines(self) -> list[str]:
        return [t for tag, t in self.lines if tag in (" ", "-")]

    def new_lines(self) -> list[str]:
        return [t for tag, t in self.lines if tag in (" ", "+")]


class FilePatch:
    def __init__(self, path: str):
        self.path = path
        self.status = "modified"
        self.base_blob: str | None = None
        self.new_blob: str | None = None
        self.binary = False
        self.hunks: list[Hunk] = []


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def extract_patch_text(text: str) -> str:
    """Pull the patch out of a saved email body, a fenced block, or a bare patch."""
    if PATCH_BEGIN in text and PATCH_END in text:
        return text.split(PATCH_BEGIN, 1)[1].split(PATCH_END, 1)[0].lstrip("\n")
    m = re.search(r"```(?:diff|patch)?\s*\n(diff --git .*?)\n```", text, flags=re.S)
    if m:
        return m.group(1) + "\n"
    i = text.find("diff --git ")
    return text[i:] if i >= 0 else text


def parse_patch(text: str) -> list[FilePatch]:
    """Parse git-style unified diffs. Hunks are bounded by their line counts, so a blank context line whose
    leading space a mailer stripped still parses."""
    files: list[FilePatch] = []
    cur: FilePatch | None = None
    hunk: Hunk | None = None
    rem_old = rem_new = 0
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            cur = FilePatch(m.group(2) if m else line[11:].split(" b/")[-1])
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        m = HUNK_RE.match(line)
        if m and (hunk is None or (rem_old <= 0 and rem_new <= 0)):
            hunk = Hunk(int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1))
            cur.hunks.append(hunk)
            rem_old, rem_new = hunk.old_len, hunk.new_len
            continue
        if hunk is None:
            if line.startswith("new file mode"):
                cur.status = "added"
            elif line.startswith("deleted file mode"):
                cur.status = "deleted"
            elif line.startswith("index "):
                mi = re.match(r"index ([0-9a-f]+)\.\.([0-9a-f]+)", line)
                if mi:
                    cur.base_blob, cur.new_blob = mi.group(1), mi.group(2)
            elif line.startswith("Binary files"):
                cur.binary = True
            continue
        if rem_old <= 0 and rem_new <= 0:
            hunk = None  # trailing text after a complete hunk (e.g. email footer)
            continue
        if line.startswith("\\ No newline"):
            continue
        tag, body = (line[0], line[1:]) if line else (" ", "")
        if tag not in (" ", "-", "+"):
            tag, body = " ", line
        hunk.lines.append((tag, body))
        if tag in (" ", "-"):
            rem_old -= 1
        if tag in (" ", "+"):
            rem_new -= 1
    return files


def _find(lines: list[str], needle: list[str], hint: int) -> int:
    """Index where `needle` occurs in `lines`, nearest to `hint`; -1 when absent."""
    if not needle:
        return max(0, min(hint, len(lines)))
    n = len(needle)
    best, best_d = -1, None
    for i in range(0, len(lines) - n + 1):
        if lines[i:i + n] == needle:
            d = abs(i - hint)
            if best_d is None or d < best_d:
                best, best_d = i, d
    return best


def apply_hunks(lines: list[str], hunks: list[Hunk], fuzz: int = 2) -> tuple[list[str], list[Hunk], list[str]]:
    """Apply hunks in order with position search and edge fuzz. Returns (lines, failed hunks, notes)."""
    out = list(lines)
    failed, notes = [], []
    offset = 0
    for h in hunks:
        old, new = h.old_lines(), h.new_lines()
        hint = max(0, h.old_start - 1 + offset)
        applied = False
        has_plus = any(tag == "+" for tag, _ in h.lines)
        for f in range(0, fuzz + 1):
            # drop up to f context lines from each edge (only context lines may be dropped)
            lead = trail = 0
            L = h.lines
            while lead < f and lead < len(L) and L[lead][0] == " ":
                lead += 1
            while trail < f and trail < len(L) - lead and L[-1 - trail][0] == " ":
                trail += 1
            core = L[lead: len(L) - trail] if trail else L[lead:]
            o = [t for tag, t in core if tag in (" ", "-")]
            n = [t for tag, t in core if tag in (" ", "+")]
            # already applied? (an insertion's old side stays present after applying, so any hunk that adds
            # lines counts as applied once its new side is found; a pure deletion needs the old side gone)
            if n and n != o and _find(out, n, hint) >= 0 and (has_plus or not o or _find(out, o, hint) < 0):
                applied = True
                notes.append(f"hunk @@ -{h.old_start} already applied")
                break
            pos = _find(out, o, hint)
            if pos >= 0:
                out[pos:pos + len(o)] = n
                offset += len(n) - len(o)
                applied = True
                if f:
                    notes.append(f"hunk @@ -{h.old_start} applied with fuzz {f}")
                break
        if not applied:
            failed.append(h)
    return out, failed, notes


def entries_from_hunks(fp: FilePatch) -> list[tuple[str, list[str]]]:
    """Whole entries added by the patch: contiguous '+' blocks that start with an entry heading."""
    out = []
    for h in fp.hunks:
        block: list[str] | None = None
        eid = None
        for tag, text in h.lines + [(" ", "")]:
            m = ENTRY_HEAD_RE.match(text) if tag == "+" else None
            if tag == "+" and m:
                if block is not None:
                    out.append((eid, block))
                block, eid = [text], m.group(1)
            elif tag == "+" and block is not None:
                if text.startswith("## ") or text.startswith("# "):
                    out.append((eid, block))
                    block, eid = None, None
                else:
                    block.append(text)
            else:
                if block is not None:
                    out.append((eid, block))
                    block, eid = None, None
    return [(e, _rstrip_blank(b)) for e, b in out if b]


def _rstrip_blank(b: list[str]) -> list[str]:
    while b and not b[-1].strip():
        b.pop()
    return b


def _next_id(existing: set[str], eid: str) -> str:
    if eid.startswith("L-"):
        nums = [int(x[2:]) for x in existing if x.startswith("L-") and x[2:].isdigit()]
        return f"L-{(max(nums) + 1 if nums else 1):03d}"
    prefix = eid.rsplit("-", 1)[0]  # C-20260903
    nums = [int(x.rsplit("-", 1)[1]) for x in existing if x.startswith(prefix + "-")]
    return f"{prefix}-{(max(nums) + 1 if nums else 1)}"


def existing_heads(text: str) -> dict[str, str]:
    out = {}
    for ln in text.splitlines():
        m = ENTRY_HEAD_RE.match(ln)
        if m:
            out[m.group(1)] = ln.strip()
    return out


def _title_of(head: str) -> str:
    m = ENTRY_HEAD_RE.match(head)
    return head[m.end():].strip(" ·") if m else head.strip()


def plan_renames(text: str, entries: list[tuple[str, list[str]]]) -> dict[str, str]:
    """Incoming ids that clash with a different entry in `text` get the next free number, free in both sides.
    An entry that was renumbered by an earlier merge is recognised by its title, so re-merging is idempotent."""
    existing = existing_heads(text)
    by_title = {_title_of(h): i for i, h in existing.items()}
    taken = set(existing) | {eid for eid, _ in entries}
    renamed: dict[str, str] = {}
    for eid, block in entries:
        head = block[0].strip()
        if eid in existing and existing[eid] != head:
            prior = by_title.get(_title_of(head))
            if prior and prior != eid:
                renamed[eid] = prior
                continue
            new_id = _next_id(taken, eid)
            renamed[eid] = new_id
            taken.add(new_id)
    return renamed


def rewrite_ids(s: str, renamed: dict[str, str]) -> str:
    for a, b in renamed.items():
        s = re.sub(rf"(?<![\w.:-]){re.escape(a)}\b", b, s)
    return s


def union_entries(text: str, entries: list[tuple[str, list[str]]], section_of: dict[str, str] | None = None,
                  renamed: dict[str, str] | None = None) -> tuple[str, list[str], dict[str, str]]:
    """Insert entries not already present. Same id with a different title gets renumbered (references inside the incoming
    entries are rewritten; pass `renamed` to apply a plan computed across several files). Each entry goes at the top of
    its section (newest first), or after the header when no section."""
    lines = text.splitlines()
    existing = existing_heads(text)
    renamed = dict(renamed) if renamed is not None else plan_renames(text, entries)
    to_add = []
    for eid, block in entries:
        eid2 = renamed.get(eid, eid)
        head = rewrite_ids(block[0].strip(), renamed)
        if eid2 in existing and existing[eid2] == head:
            continue  # same entry already there
        if eid2 in existing:
            # still clashing (a plan computed elsewhere did not cover it): renumber now
            eid2 = _next_id(set(existing) | {e for e, _ in entries} | set(renamed.values()), eid)
            renamed[eid] = eid2
            head = rewrite_ids(block[0].strip(), renamed)
        existing[eid2] = head
        to_add.append((eid2, block))
    if not to_add:
        return text, [], renamed
    added = []
    for eid, block in to_add:
        block = [rewrite_ids(x, renamed) for x in block]
        sec = (section_of or {}).get(eid.split("-")[0] if not eid.startswith("L-") else "L")
        insert_at = None
        if sec:
            for i, ln in enumerate(lines):
                if ln.strip() == sec.strip():
                    insert_at = i + 1
                    break
        if insert_at is None:
            # first existing entry heading of the same kind, else end of file
            for i, ln in enumerate(lines):
                m = ENTRY_HEAD_RE.match(ln)
                if m and m.group(1)[0] == eid[0]:
                    insert_at = i
                    break
        if insert_at is None:
            insert_at = len(lines)
        else:
            # skip blank lines directly after a section heading so the entry sits after them
            while sec and insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
        chunk = block + [""]
        lines[insert_at:insert_at] = chunk
        added.append(eid)
    return "\n".join(lines) + ("\n" if text.endswith("\n") or not text else ""), added, renamed


def section_map(text: str) -> dict[str, str]:
    """Which '## ' heading holds the first entry of each kind (C, R, L) in this file."""
    out, cur = {}, None
    for ln in text.splitlines():
        if ln.startswith("## "):
            cur = ln
        m = ENTRY_HEAD_RE.match(ln)
        if m and cur:
            out.setdefault(m.group(1)[0], cur)
    return out


def merge_state(trunk: dict, incoming: dict) -> dict:
    out = json.loads(json.dumps(trunk))
    ti, ii = str(trunk.get("last_checked") or ""), str(incoming.get("last_checked") or "")
    newer = incoming if ii > ti else trunk
    for k in ("tier", "interval_days", "last_checked", "next_due", "verify_at_use", "volatile_claims", "contradiction", "events", "streak"):
        if k in newer:
            out[k] = newer[k]
    seen, hist = set(), []
    for h in (trunk.get("history") or []) + (incoming.get("history") or []):
        key = (h.get("date"), h.get("note"), h.get("m"))
        if key in seen:
            continue
        seen.add(key)
        hist.append(h)
    out["history"] = sorted(hist, key=lambda h: str(h.get("date") or ""))
    tc, ic = trunk.get("counts") or {}, incoming.get("counts") or {}
    out["counts"] = {k: max(int(tc.get(k, 0)), int(ic.get(k, 0))) for k in set(tc) | set(ic)}
    if incoming.get("files"):  # a test-init elsewhere adds files.tests; the TESTS.md itself arrives as an added file
        out["files"] = {**(trunk.get("files") or {}), **incoming["files"]}
    tt, it = trunk.get("tests"), incoming.get("tests")
    if isinstance(it, dict) and (not isinstance(tt, dict) or str(it.get("last_run") or "") > str(tt.get("last_run") or "")):
        out["tests"] = it  # the block from the later suite run wins whole (a later all-pass run clears the failing list)
    return out


def read_text_any(p: Path) -> str:
    """Saved emails may be UTF-16 (Outlook) or carry a BOM."""
    b = p.read_bytes()
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return b.decode("utf-16", errors="replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", errors="replace")
    if len(b) > 1 and b[1:2] == b"\x00" and b[0:1] != b"\x00":
        return b.decode("utf-16-le", errors="replace")
    return b.decode("utf-8", errors="replace")


def merge(source: Path, trunk: Path | None = None, dry_run: bool = False, use_git: bool = True, allow_code: bool = False) -> dict:
    source = Path(source).expanduser()
    trunk = Path(trunk).expanduser().resolve() if trunk else eg.plugin_root().resolve()
    manifest: dict = {}
    bundle_dir: Path | None = None
    tmp: tempfile.TemporaryDirectory | None = None
    if source.is_dir():
        bundle_dir = source
    elif source.suffix.lower() == ".zip":
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(source) as z:
            z.extractall(tmp.name)
        cands = list(Path(tmp.name).rglob("changes.patch"))
        if not cands:
            raise RuntimeError("zip holds no changes.patch")
        bundle_dir = cands[0].parent
    if bundle_dir:
        patch_text = (bundle_dir / "changes.patch").read_text(encoding="utf-8", errors="replace")
        mp = bundle_dir / "manifest.json"
        if mp.exists():
            manifest = json.loads(mp.read_text(encoding="utf-8"))
    else:
        patch_text = extract_patch_text(read_text_any(source))
        sib = source.with_name("manifest.json")
        if sib.exists():
            manifest = json.loads(sib.read_text(encoding="utf-8"))
    files = parse_patch(patch_text)
    if not files:
        raise RuntimeError("no file diffs found in the source (expected 'diff --git' sections)")
    is_git = use_git and shutil.which("git") is not None and git_ok(trunk)
    report = {"trunk": str(trunk), "bundle": manifest.get("bundle_id") or source.name, "applied": [], "already": [], "union": [],
              "conflicts": [], "skipped": [], "notes": [], "git": is_git, "dry_run": dry_run, "renamed": {}, "written": []}

    # Refuse anything that does not name a plain file inside the tree (a patch is data from elsewhere).
    safe = []
    for fp in files:
        if not safe_rel(fp.path) or not inside(trunk / fp.path, trunk):
            report["skipped"].append(f"{fp.path}: unsafe path; refused")
            continue
        safe.append(fp)
    files = safe

    # Pass 1: incoming log entries whose ids clash with different trunk entries get new ids, and every incoming
    # line of the same unit (ids are per unit: the plugin root, profile/, ...) that cites them is rewritten.
    unit_dirs = [Path(fp.path).parent.as_posix() for fp in files if Path(fp.path).name in LOG_FILES] + ["."]
    for p_ in trunk.rglob("CHANGELOG.md"):  # units already in the trunk count too (profile/ has its own id space)
        if ".git" not in p_.parts:
            unit_dirs.append(p_.parent.relative_to(trunk).as_posix())
    unit_dirs = sorted(set(unit_dirs), key=len, reverse=True)

    def unit_of(path: str) -> str:
        for d in unit_dirs:
            if d != "." and (path == d or path.startswith(d + "/")):
                return d
        return "."

    renamed_by_unit: dict[str, dict[str, str]] = {}
    for fp in files:  # a log created on both sides (test-init here and there) is planned like a modified one
        if Path(fp.path).name in LOG_FILES and fp.status in ("modified", "added") and (trunk / fp.path).exists():
            ttxt = (trunk / fp.path).read_text(encoding="utf-8", errors="replace")
            renamed_by_unit.setdefault(unit_of(fp.path), {}).update(plan_renames(ttxt, entries_from_hunks(fp)))
    for unit, renamed in renamed_by_unit.items():
        if not renamed:
            continue
        for fp in files:
            if unit_of(fp.path) == unit:
                for h in fp.hunks:
                    h.lines = [(tag, rewrite_ids(t, renamed) if tag == "+" else t) for tag, t in h.lines]
        report["renamed"].update(renamed)
        report["notes"].append(f"renumbered incoming ids in {unit}: " + ", ".join(f"{a} -> {b}" for a, b in renamed.items()))

    def write(p: Path, text: str, eol: str):
        if dry_run:
            return
        if not inside(p, trunk):
            raise RuntimeError(f"refusing to write outside the trunk: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.replace("\n", eol).encode("utf-8") if eol != "\n" else text.encode("utf-8"))
        report["written"].append(str(p.relative_to(trunk).as_posix()))

    def park(p: Path, text: str, suffix: str):
        if not dry_run and inside(p, trunk):
            p.with_suffix(p.suffix + suffix).write_text(text, encoding="utf-8")

    for fp in files:
        rel = fp.path
        p = trunk / rel
        if fp.binary:
            report["skipped"].append(f"{rel}: binary; copy by hand")
            continue
        incoming_text = "\n".join(t for h in fp.hunks for tag, t in h.lines if tag == "+") + "\n"
        if Path(rel).name in PROTECTED or rel in PROTECTED:
            park(p, incoming_text, ".incoming")
            report["conflicts"].append(f"{rel}: protected (recipient and machine paths live here); incoming lines saved as {rel}.incoming, apply by hand")
            continue
        if any(rel.startswith(d) for d in CODE_DIRS) and not allow_code:
            park(p, incoming_text, ".incoming")
            report["conflicts"].append(f"{rel}: CODE CHANGED; not merged without --allow-code (incoming lines in {rel}.incoming)")
            continue
        exists = p.exists()
        cur_b = p.read_bytes() if exists else None
        cur_blob = git_blob(cur_b) if cur_b is not None else None
        new_full = [t for h in fp.hunks for tag, t in h.lines if tag == "+"] if fp.status == "added" else None

        if fp.status == "added":
            if not exists:
                write(p, join_lines(new_full or [], "\n"), "\n")
                report["applied"].append(rel)
            elif fp.new_blob and cur_blob and cur_blob.startswith(fp.new_blob):
                report["already"].append(rel)
            elif lines_of(cur_b) == new_full:
                report["already"].append(rel)
            elif Path(rel).name in LOG_FILES:  # both sides scaffolded the same log: union its entries, never a conflict
                text = "\n".join(lines_of(cur_b)) + "\n"
                merged_text, added, late = union_entries(text, entries_from_hunks(fp), section_map(text), renamed={})
                if added:
                    write(p, merged_text, eol_of(cur_b))
                    report["union"].append(f"{rel}: added {', '.join(added)}" + (f" (renumbered {late})" if late else ""))
                else:
                    report["already"].append(rel)
            else:
                park(p, join_lines(new_full or [], "\n"), ".incoming")
                report["conflicts"].append(f"{rel}: exists with different content; incoming saved as {rel}.incoming")
            continue
        if fp.status == "deleted":
            if not exists:
                report["already"].append(rel)
            elif fp.base_blob and cur_blob and cur_blob.startswith(fp.base_blob):
                if not dry_run:
                    p.unlink()
                    report["written"].append(rel)
                report["applied"].append(f"{rel} (deleted)")
            else:
                report["conflicts"].append(f"{rel}: deleted upstream but changed here; kept")
            continue
        if not exists:
            report["conflicts"].append(f"{rel}: missing at the trunk; cannot apply a modification")
            continue
        if fp.new_blob and cur_blob and cur_blob.startswith(fp.new_blob):
            report["already"].append(rel)
            continue
        eol = eol_of(cur_b)
        cur_lines = lines_of(cur_b)
        name = Path(rel).name

        # state files: merge as data, never as text
        if name == "evergreen.json":
            incoming = (manifest.get("state") or {}).get(rel)
            if incoming is None and is_git and fp.base_blob:
                base_txt = _git_blob_text(trunk, fp.base_blob)
                if base_txt is not None:
                    merged, failed, _ = apply_hunks(base_txt.splitlines(), fp.hunks, fuzz=0)
                    if not failed:
                        incoming = _json_or_none("\n".join(merged))
            if incoming is None:
                merged, failed, notes = apply_hunks(cur_lines, fp.hunks)
                if not failed:
                    incoming = _json_or_none("\n".join(merged))
                elif notes and all("already applied" in n for n in notes):
                    report["already"].append(rel)
                    continue
            if incoming is None:
                report["skipped"].append(f"{rel}: state not merged (could not reconstruct the incoming state); run `checked` at the trunk if its history matters")
                continue
            try:
                trunk_state = json.loads(cur_b.decode("utf-8"))
            except Exception:
                report["conflicts"].append(f"{rel}: trunk state unreadable")
                continue
            new_state = merge_state(trunk_state, incoming)
            if new_state != trunk_state:
                write(p, json.dumps(new_state, indent=2, ensure_ascii=False) + "\n", "\n")
                report["applied"].append(f"{rel} (state merged)")
            else:
                report["already"].append(rel)
            continue

        # identical to the patch's base: exact apply
        if fp.base_blob and cur_blob and cur_blob.startswith(fp.base_blob):
            merged, failed, notes = apply_hunks(cur_lines, fp.hunks, fuzz=0)
            if not failed:
                write(p, join_lines(merged, "\n"), eol)
                report["applied"].append(rel)
                continue

        # every hunk's result already present: nothing to do
        merged, failed, notes = apply_hunks(cur_lines, fp.hunks)
        if not failed and merged == cur_lines:
            report["already"].append(rel)
            continue

        # diverged: logs get entry union first, then the remaining hunks with fuzz
        if name in LOG_FILES:
            entries = entries_from_hunks(fp)
            text = "\n".join(cur_lines) + "\n"
            merged_text, added, late = union_entries(text, entries, section_map(text), renamed={})
            cur_lines2 = merged_text.splitlines()
            leftover = [r for r in (_strip_entry_lines(h, entries) for h in fp.hunks) if r is not None]
            merged, failed, notes = apply_hunks(cur_lines2, leftover) if leftover else (cur_lines2, [], [])
            if merged != cur_lines and (added or not failed):
                write(p, join_lines(merged, "\n"), eol)
            if added:
                report["union"].append(f"{rel}: added {', '.join(added)}" + (f" (renumbered {late})" if late else ""))
            elif not failed:
                report["already" if merged == cur_lines else "applied"].append(rel if merged == cur_lines else f"{rel} (fuzzy)")
            if failed:
                _write_rej(p, failed, dry_run)
                report["conflicts"].append(f"{rel}: {len(failed)} hunk(s) did not apply; see {rel}.rej")
            report["notes"] += [f"{rel}: {n}" for n in notes]
            continue

        # other files: git 3-way when history has the base blob, else fuzzy apply
        if is_git and fp.base_blob:
            single = _single_file_patch(patch_text, rel)
            if single and not dry_run:
                with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8", newline="\n") as f:
                    f.write(single)
                    sp = f.name
                r = subprocess.run(["git", "apply", "--3way", sp], cwd=str(trunk), capture_output=True, text=True, encoding="utf-8", errors="replace")
                os.unlink(sp)
                if r.returncode == 0:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    report["written"].append(rel)
                    if "<<<<<<<" in txt and ">>>>>>>" in txt:
                        report["conflicts"].append(f"{rel}: git 3-way left conflict markers; resolve by hand")
                    else:
                        report["applied"].append(f"{rel} (git 3-way)")
                    continue
                report["notes"].append(f"{rel}: git apply --3way declined ({(r.stderr or '').strip().splitlines()[-1] if r.stderr else 'no detail'}); trying fuzzy apply")
            elif single and dry_run:
                report["notes"].append(f"{rel}: the real run tries git apply --3way first")
        merged, failed, notes = apply_hunks(cur_lines, fp.hunks)
        if failed:
            _write_rej(p, failed, dry_run)
            if len(failed) < len(fp.hunks):
                write(p, join_lines(merged, "\n"), eol)
            report["conflicts"].append(f"{rel}: {len(failed)}/{len(fp.hunks)} hunk(s) did not apply; see {rel}.rej")
        else:
            write(p, join_lines(merged, "\n"), eol)
            report["applied"].append(f"{rel} (fuzzy)" if notes else rel)
        report["notes"] += [f"{rel}: {n}" for n in notes]

    if tmp:
        tmp.cleanup()
    if not dry_run:
        rec = {"date": datetime.now().strftime("%Y-%m-%dT%H:%M"), "bundle": report["bundle"], "from_env": manifest.get("env"),
               "applied": len(report["applied"]), "union": len(report["union"]), "conflicts": len(report["conflicts"])}
        mp = home() / "merges.json"
        try:
            log = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []
        except Exception:
            log = []
        log.append(rec)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(log[-200:], indent=2) + "\n", encoding="utf-8")
        if not report["conflicts"] and trunk.resolve() == eg.plugin_root().resolve():
            take_baseline(note=f"after merge of {report['bundle']}", pack_id=(load_baseline() or {}).get("pack_id"))
            report["notes"].append("baseline advanced")
        if is_git and not report["conflicts"] and report["written"]:
            eg.git(["add", "-A", "--"] + sorted(set(report["written"])), trunk)  # only what the merge touched
            msg = f"merge evergreen update {report['bundle']}" + (f" from {manifest.get('env')}" if manifest.get("env") else "")
            if eg.git(["commit", "-q", "-m", msg, "--"] + sorted(set(report["written"])), trunk) is not None:
                report["notes"].append(f"committed: {msg}")
            else:
                report["notes"].append("git commit failed (identity not set?); changes are staged")
    return report


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def _git_blob_text(trunk: Path, blob_prefix: str) -> str | None:
    """Content of a blob from the trunk's history (the patch's `index` line names it), or None."""
    full = eg.git(["rev-parse", "--verify", "--quiet", f"{blob_prefix}^{{blob}}"], trunk)
    if not full:
        return None
    try:
        r = subprocess.run(["git", "cat-file", "-p", full], cwd=str(trunk), capture_output=True, timeout=20)
        return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None
    except Exception:
        return None


def _strip_entry_lines(h: Hunk, entries: list[tuple[str, list[str]]]) -> Hunk | None:
    """The hunk minus the '+' lines that belong to whole entries (already unioned). None when nothing else changes."""
    blocks = [set(b) for _, b in entries]
    out = Hunk(h.old_start, h.old_len, h.new_start, h.new_len)
    inside = False
    for tag, t in h.lines:
        if tag == "+":
            if ENTRY_HEAD_RE.match(t) and any(t in b for b in blocks):
                inside = True
                continue
            if inside and (any(t in b for b in blocks) or not t.strip()):
                continue
            inside = False
        else:
            inside = False
        out.lines.append((tag, t))
    if not any(tag in ("+", "-") and t.strip() for tag, t in out.lines):
        return None
    out.old_len = sum(1 for tag, _ in out.lines if tag in (" ", "-"))
    out.new_len = sum(1 for tag, _ in out.lines if tag in (" ", "+"))
    return out


def _write_rej(p: Path, failed: list[Hunk], dry_run: bool) -> None:
    if dry_run or ".." in p.parts:
        return
    out = []
    for h in failed:
        out.append(f"@@ -{h.old_start},{h.old_len} +{h.new_start},{h.new_len} @@")
        out += [tag + t for tag, t in h.lines]
    p.with_suffix(p.suffix + ".rej").write_text("\n".join(out) + "\n", encoding="utf-8")


def _single_file_patch(patch_text: str, rel: str) -> str | None:
    parts = re.split(r"(?m)^(?=diff --git )", patch_text)
    for part in parts:
        if part.startswith(f"diff --git a/{rel} b/{rel}"):
            return part if part.endswith("\n") else part + "\n"
    return None


# ---------- where ----------

def where() -> dict:
    root = eg.plugin_root()
    cfg = notify_config()
    note = ""
    try:
        base, note = ensure_baseline(current_files())  # a pristine install baselines itself here (the install check)
    except Exception as e:
        base, note = load_baseline(), str(e)
    reg = eg.load_registry()
    ns = load_notify_state()
    trunk_git = git_ok(root) if shutil.which("git") else False
    branch = eg.git(["rev-parse", "--abbrev-ref", "HEAD"], root) if trunk_git else None
    dirty = bool(eg.git(["status", "--porcelain"], root)) if trunk_git else None
    unsent = []
    ob = outbox_dir()
    if ob.exists():
        for d in sorted(ob.iterdir()):
            s = d / "STATUS"
            if s.exists() and s.read_text(encoding="utf-8").startswith(("unsent", "pending-human")):
                unsent.append(d.name + ("" if s.read_text(encoding="utf-8").startswith("unsent") else " (pending a click)"))
    uses = None
    up = eg.uses_path()
    if up.exists():
        lines = [ln for ln in up.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        last = (_json_or_none(lines[-1]) or {}).get("ts") if lines else None
        uses = {"path": str(up), "lines": len(lines), "last": last}
    return {"plugin_root": str(root), "version": eg.plugin_version(), "script": str(Path(__file__).resolve().parent / "evergreen.py"),
            "uses": uses,
            "protocol": str(root / "protocol" / "PROTOCOL.md"), "home": str(home()), "registry": str(eg.registry_path()),
            "registry_plugin_root": reg.get("plugin_root"), "env": env_name(cfg), "is_trunk": is_trunk(),
            "baseline": {k: base.get(k) for k in ("taken", "version", "pack_id", "note")} if base else None, "baseline_note": note,
            "git": {"repo": trunk_git, "branch": branch, "dirty": dirty},
            "contribute": eg.contribute_setting(),
            "update": {"transport": update_transport(), **git_status_summary(root, git_config()), "last_publish": load_publish_state().get("last")},
            "notify": {"auto": cfg.get("auto"), "to": cfg.get("to"), "transports": cfg.get("transports"),
                       "smtp_ready": all(smtp_credentials(cfg)[:2]), "outbox_copy_to": per_os(cfg.get("outbox_copy_to"))},
            "last_sent": ns.get("last"), "unsent_bundles": unsent}



# ---------- git transport (PROTOCOL.md §10, protocol 1.4) ----------
# The trunk is a git repository on a host (GitHub by default). Every install is a clone. A maintainer's clone pushes
# its self-updates straight to the trunk branch; anyone else's clone pushes an update branch and opens a pull request.
# The email transport (notify) stays as the fallback for machines that cannot reach the host.

GIT_DEFAULTS = {
    "remote": "origin",
    "branch": "master",
    "upstream": None,          # owner/repo of the trunk on the host; a contributor's origin is their fork of it
    "role": "auto",            # maintainer | contributor | auto (auto: a dry-run push to the trunk branch decides)
    "auto": True,              # unattended entry points (checked, bump, the session-end hook) may publish
    "pr": True,                # open a pull request with gh when the update went to a branch
    "branch_prefix": "update", # update branches are named <prefix>/<env>-<stamp>
    "commit_prefix": "evergreen:",
}


def update_transport() -> str:
    """'git' (default) or 'email': which route the plugin's self-updates take. EVERGREEN_UPDATE_TRANSPORT overrides."""
    env = os.environ.get("EVERGREEN_UPDATE_TRANSPORT")
    if env:
        return env.strip().lower()
    p = eg.plugin_root() / "evergreen.config.json"
    if p.exists():
        try:
            return str((json.loads(p.read_text(encoding="utf-8")).get("update") or {}).get("transport") or "git").lower()
        except Exception:
            pass
    return "git"


def git_config() -> dict:
    cfg = dict(GIT_DEFAULTS)
    p = eg.plugin_root() / "evergreen.config.json"
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")).get("git") or {})
        except Exception:
            pass
    role = os.environ.get("EVERGREEN_GIT_ROLE")  # machine-local override, set by the user
    if role:
        cfg["role"] = role.strip().lower()
    return cfg


def git_run(args: list[str], cwd: Path, timeout: int = 90) -> tuple[int, str]:
    """git with its stderr kept: publish needs to read rejection reasons (auth, non-fast-forward, conflicts)."""
    try:
        r = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def git_role(cfg: dict, root: Path) -> tuple[str, str]:
    """(role, how). Explicit config wins; 'auto' asks the remote with a dry-run push, which needs no extra tool
    and never changes anything. No answer (offline, no remote) counts as contributor, the safe side."""
    role = str(cfg.get("role") or "auto")
    if role in ("maintainer", "contributor"):
        return role, "config"
    rc, out = git_run(["push", "--dry-run", cfg["remote"], f"HEAD:refs/heads/{cfg['branch']}"], root, timeout=45)
    if rc == 0:
        return "maintainer", "dry-run push accepted"
    low = out.lower()
    if "rejected" in low and ("fetch first" in low or "non-fast-forward" in low or "behind" in low):
        return "maintainer", "dry-run push rejected only for being behind"  # write access is there; pull first
    return "contributor", f"dry-run push refused: {out.splitlines()[-1] if out else 'no output'}"


def git_new_entries(root: Path, ref: str = "HEAD") -> list[str]:
    """Entry heads (C-, R-, L-, T-) present in the worktree's log files and absent at `ref`."""
    heads: list[str] = []
    for rel in sorted(LOG_FILES | {"profile/" + f for f in LOG_FILES}):
        p = root / rel
        if not p.exists():
            continue
        base = eg.git(["show", f"{ref}:{rel}"], root)
        heads += new_entry_heads(base.encode("utf-8") if base is not None else None, p.read_bytes())
    return heads


def commit_message(root: Path, cfg: dict, env: str, changed: list[str]) -> str:
    """One subject line an owner can scan in `git log`, then the new entry IDs and the changed files."""
    heads = [re.sub(r"^###\s+", "", h) for h in git_new_entries(root)]
    ids = [h.split()[0] for h in heads]
    logs = [c for c in changed if c.split("/")[-1] in LOG_FILES]
    other = [c for c in changed if c not in logs]
    what = ", ".join(ids[:6]) + (f" +{len(ids) - 6}" if len(ids) > 6 else "") if ids else (
        f"{len(other)} file(s)" if other else "state")
    subject = f"{cfg.get('commit_prefix') or 'evergreen:'} update from {env} ({what})"[:72]
    body = ""
    if heads:
        body += "\n\nNew entries:\n" + "\n".join(f"- {h}" for h in heads)
    if other:
        body += "\n\nOther files:\n" + "\n".join(f"- {c}" for c in other)
    body += f"\n\nPublished by evergreen.py publish (env {env}, v{eg.plugin_version()})."
    return subject + body


def publish_state_path() -> Path:
    return home() / "publish.json"


def record_publish(entry: dict) -> None:
    p = publish_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    st = {}
    if p.exists():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    hist = st.get("history") or []
    hist.append(entry)
    st["history"] = hist[-50:]
    st["last"] = entry
    p.write_text(json.dumps(st, indent=2), encoding="utf-8")


def load_publish_state() -> dict:
    p = publish_state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


PORCELAIN_RE = re.compile(r"^([ MTADRCU?!]{1,2}) (.+)$")


def changed_paths(root: Path) -> list[str]:
    # eg.git() strips its output, which eats the leading space of a first line like " M LEARNINGS.md"; a fixed
    # `ln[3:]` then cut the path to "EARNINGS.md" in commit messages. Parse the status columns instead (L-022).
    out = eg.git(["-c", "core.quotepath=off", "status", "--porcelain", "--untracked-files=all"], root) or ""
    paths = []
    for ln in out.splitlines():
        m = PORCELAIN_RE.match(ln)
        if not m:
            continue
        rel = m.group(2).strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1].strip('"')
        paths.append(rel.replace("\\", "/"))
    return paths


def open_pull_request(root: Path, cfg: dict, branch: str, title: str, body: str) -> tuple[bool, str]:
    """`gh pr create` against the trunk (cfg.upstream when set; gh detects a fork's parent otherwise)."""
    if not shutil.which("gh"):
        return False, "gh is not installed; open the pull request by hand"
    # a draft, in the user's name: the person who said yes at install reviews it before anyone else does
    body = body.rstrip() + f"\n\nOpened by the evergreen plugin from `{env_name()}` with the owner's consent (`evergreen.py contribute yes`); file diffs only, no transcripts. Reviewer: the repository owner."
    args = ["gh", "pr", "create", "--draft", "--base", cfg["branch"], "--head", branch, "--title", title, "--body", body]
    if cfg.get("upstream"):
        args += ["--repo", str(cfg["upstream"])]
    try:
        r = subprocess.run(args, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out.splitlines()[-1] if out else ""
    except Exception as e:
        return False, str(e)


def contribute_gate(unattended: bool) -> str | None:
    """None when this install may send; otherwise the message to return instead of sending. The install-time
    choice (PROTOCOL.md section 10): 'no' means nothing leaves the machine by any route; undecided means nothing
    leaves unattended, and an explicit publish or notify says what to decide."""
    v = eg.contribute_setting()
    if v == "yes":
        return None
    if v == "no":
        return "" if unattended else "contribution is off on this install (`evergreen.py contribute yes` to allow pull requests); updates still arrive with `pull`"
    return "" if unattended else "not decided on this install: " + eg.CONTRIBUTE_QUESTION


def publish(if_changed: bool = False, dry_run: bool = False, from_hook: bool = False, message: str | None = None,
            as_branch: bool = False) -> str:
    """Commit the plugin's self-changes and push them to the trunk: to the trunk branch when this clone may write
    there, otherwise (or when the trunk moved underneath and the rebase conflicts) to an update branch plus a pull
    request. Idempotent: nothing to commit and nothing ahead means nothing to do."""
    root = eg.plugin_root()
    cfg = git_config()
    env = env_name()
    if not shutil.which("git"):
        return "" if if_changed else "git is not installed; nothing published"
    if eg.git(["rev-parse", "--is-inside-work-tree"], root) != "true":
        return "" if if_changed else f"{root} is not a git clone; install from the repository first (README section Install)"
    if if_changed and not cfg.get("auto", True):
        return ""
    gate = contribute_gate(if_changed or from_hook)
    if gate is not None:
        return gate
    if from_hook and is_trunk() and not (notify_config().get("report_trunk")):
        return ""  # the maintainer's editing clone does not push half-done work from a session-end hook
    remote = cfg["remote"]
    if eg.git(["config", "--get", f"remote.{remote}.url"], root) is None:
        return "" if if_changed else f"no remote '{remote}' in {root}; add one (git remote add {remote} <url>)"
    head_branch = eg.git(["rev-parse", "--abbrev-ref", "HEAD"], root) or ""
    changed = changed_paths(root)
    ahead = 0
    if eg.git(["rev-parse", "--verify", "-q", f"{remote}/{head_branch}"], root):
        ahead = int(eg.git(["rev-list", "--count", f"{remote}/{head_branch}..HEAD"], root) or 0)
    if not changed and not ahead:
        return "" if if_changed else "nothing to publish: worktree clean and nothing ahead of the remote"
    msg = message or (commit_message(root, cfg, env, changed) if changed else "")
    if dry_run:
        role, how = git_role(cfg, root)
        return (f"dry run: would commit {len(changed)} file(s) on {head_branch} as '{msg.splitlines()[0] if msg else '(nothing)'}', "
                f"then push as {role} ({how}) to {remote}/{cfg['branch']}" + (" via an update branch and a PR" if role != "maintainer" or as_branch else ""))
    if changed:
        eg.git(["add", "-A"], root)
        rc, out = git_run(["commit", "-q", "-m", msg], root)
        if rc != 0:
            if "please tell me who you are" in out.lower() or "author identity unknown" in out.lower():
                return ("unpublished: git has no user.name/user.email on this machine; set them once "
                        "(git config --global user.name ...; git config --global user.email ...) and run `publish` again")
            return f"unpublished: commit failed: {out.splitlines()[-1] if out else rc}"
    sha = eg.git(["rev-parse", "--short", "HEAD"], root) or "?"
    subject = (msg.splitlines()[0] if msg else (eg.git(["log", "-1", "--format=%s"], root) or f"evergreen: update from {env}"))
    on_update_branch = head_branch != cfg["branch"]
    role, how = ("contributor", "update branch already checked out") if on_update_branch else git_role(cfg, root)
    if as_branch:
        role, how = "contributor", "--branch requested"
    # 1. maintainer on the trunk branch: rebase on the remote, push.
    if role == "maintainer" and not on_update_branch:
        git_run(["fetch", remote, cfg["branch"]], root)
        rc, out = git_run(["pull", "--rebase", "--no-autostash", remote, cfg["branch"]], root)
        if rc != 0:
            git_run(["rebase", "--abort"], root)
            how = f"rebase on {remote}/{cfg['branch']} conflicted; opening a pull request instead"
            role = "contributor"
        else:
            rc, out = git_run(["push", remote, f"HEAD:refs/heads/{cfg['branch']}"], root)
            if rc == 0:
                record_publish({"date": datetime.now().strftime("%Y-%m-%dT%H:%M"), "env": env, "sha": sha, "route": "push",
                                "branch": cfg["branch"], "subject": subject})
                try:
                    take_baseline(note=f"after push {sha}")
                except Exception:
                    pass
                return f"pushed {sha} to {remote}/{cfg['branch']} as maintainer ({how}): {subject}"
            how = f"push to {cfg['branch']} refused ({out.splitlines()[-1] if out else rc}); opening a pull request instead"
            role = "contributor"
    # 2. contributor (or a maintainer whose push could not land): update branch + pull request.
    if on_update_branch:
        branch = head_branch
    else:
        branch = f"{cfg.get('branch_prefix') or 'update'}/{env}-{now_stamp()}".replace(" ", "-")
        rc, out = git_run(["checkout", "-q", "-b", branch], root)
        if rc != 0:
            return f"unpublished: could not create branch {branch}: {out}"
    rc, out = git_run(["push", "-u", remote, branch], root)
    if rc != 0:
        return (f"unpublished: committed {sha} on {branch} but the push to {remote} failed: "
                f"{out.splitlines()[-1] if out else rc}. Fix access (a fork as '{remote}', a token, the network) and run `publish` again.")
    existing = None
    if shutil.which("gh") and cfg.get("pr", True):
        try:
            r = subprocess.run(["gh", "pr", "view", branch, "--json", "url", "-q", ".url"] + (["--repo", str(cfg["upstream"])] if cfg.get("upstream") else []),
                               cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            existing = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
        except Exception:
            existing = None
    pr_line = ""
    if existing:
        pr_line = f"; pull request updated: {existing}"
    elif cfg.get("pr", True):
        ok, detail = open_pull_request(root, cfg, branch, subject, "Self-update published by evergreen.py from "
                                       f"environment `{env}` (v{eg.plugin_version()}).\n\nReview the new entries; the log files merge by union.")
        pr_line = f"; pull request: {detail}" if ok else f"; open a pull request from {branch} by hand ({detail})"
    record_publish({"date": datetime.now().strftime("%Y-%m-%dT%H:%M"), "env": env, "sha": sha, "route": "branch",
                    "branch": branch, "subject": subject, "pr": existing or pr_line})
    return f"pushed {sha} to {remote}/{branch} as {role} ({how}){pr_line}"


def pull(dry_run: bool = False) -> str:
    """Bring this clone up to date with the trunk: fast-forward the trunk branch; if this clone sits on an update
    branch whose pull request has merged, switch back first. Says whether an installed copy needs a reinstall."""
    root = eg.plugin_root()
    cfg = git_config()
    remote = cfg["remote"]
    if not shutil.which("git") or eg.git(["rev-parse", "--is-inside-work-tree"], root) != "true":
        return f"{root} is not a git clone"
    if changed_paths(root):
        return "worktree has uncommitted changes; run `publish` (or commit/stash) before `pull`"
    head_branch = eg.git(["rev-parse", "--abbrev-ref", "HEAD"], root) or ""
    rc, out = git_run(["fetch", "--prune", remote], root)
    if rc != 0:
        return f"fetch from {remote} failed: {out.splitlines()[-1] if out else rc}"
    before = eg.git(["rev-parse", "HEAD"], root) or ""
    notes = []
    if head_branch != cfg["branch"]:
        merged = eg.git(["branch", "-r", "--contains", head_branch, f"{remote}/{cfg['branch']}"], root)
        if merged:
            if dry_run:
                return f"dry run: {head_branch} is merged into {remote}/{cfg['branch']}; would switch back and fast-forward"
            git_run(["checkout", "-q", cfg["branch"]], root)
            git_run(["branch", "-D", head_branch], root)
            notes.append(f"{head_branch} merged; back on {cfg['branch']}")
        else:
            return f"on update branch {head_branch}, not yet merged into {remote}/{cfg['branch']}; nothing pulled (merge the PR first)"
    if dry_run:
        n = eg.git(["rev-list", "--count", f"HEAD..{remote}/{cfg['branch']}"], root) or "0"
        return f"dry run: {n} commit(s) to fast-forward from {remote}/{cfg['branch']}"
    rc, out = git_run(["merge", "--ff-only", f"{remote}/{cfg['branch']}"], root)
    if rc != 0:
        return f"cannot fast-forward {cfg['branch']} onto {remote}/{cfg['branch']} ({out.splitlines()[-1] if out else rc}); publish first, or rebase by hand"
    after = eg.git(["rev-parse", "HEAD"], root) or ""
    if before == after:
        return "already up to date" + (f" ({'; '.join(notes)})" if notes else "")
    files = (eg.git(["diff", "--name-only", f"{before}..{after}"], root) or "").splitlines()
    code = [f for f in files if f.startswith(("skills/", "protocol/", "scripts/", "hooks/", "agents/", ".claude-plugin/", "templates/"))]
    try:
        take_baseline(note=f"after pull {after[:8]}")
    except Exception:
        pass
    tail = f"; reinstall the plugin copy (claude plugin uninstall/install) to pick up {len(code)} changed skill/protocol/script file(s)" if code else ""
    return f"fast-forwarded {before[:8]}..{after[:8]}: {len(files)} file(s)" + (f" ({'; '.join(notes)})" if notes else "") + tail


def git_status_summary(root: Path, cfg: dict) -> dict:
    if not shutil.which("git") or eg.git(["rev-parse", "--is-inside-work-tree"], root) != "true":
        return {"repo": False}
    branch = eg.git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    remote_url = eg.git(["config", "--get", f"remote.{cfg['remote']}.url"], root)
    ahead = behind = None
    if remote_url and eg.git(["rev-parse", "--verify", "-q", f"{cfg['remote']}/{cfg['branch']}"], root):
        ahead = int(eg.git(["rev-list", "--count", f"{cfg['remote']}/{cfg['branch']}..HEAD"], root) or 0)
        behind = int(eg.git(["rev-list", "--count", f"HEAD..{cfg['remote']}/{cfg['branch']}"], root) or 0)
    return {"repo": True, "branch": branch, "dirty": bool(changed_paths(root)), "remote": remote_url,
            "trunk_branch": cfg["branch"], "ahead": ahead, "behind": behind, "role": cfg.get("role"), "upstream": cfg.get("upstream")}


def cmd_publish(a):
    if a.detach:
        args = ["publish"]
        for flag, val in (("--if-changed", a.if_changed), ("--from-hook", a.from_hook), ("--dry-run", a.dry_run), ("--branch", a.branch)):
            if val:
                args.append(flag)
        if a.message:
            args += ["--message", a.message]
        detach_self(args)
        print("publish detached to the background (log: EVERGREEN_HOME/notify.log)")
        return
    msg = publish(if_changed=a.if_changed, dry_run=a.dry_run, from_hook=a.from_hook, message=a.message, as_branch=a.branch)
    if msg:
        print(msg)


def cmd_pull(a):
    print(pull(dry_run=a.dry_run))


# ---------- CLI ----------

def cmd_baseline(a):
    if a.show:
        b = load_baseline()
        print(json.dumps({k: v for k, v in (b or {}).items() if k != "files"} | {"files": len((b or {}).get("files", {}))}, indent=2) if b else "no baseline")
        return
    if getattr(a, "from_zip", None):
        files, pack_id = files_from_zip(Path(a.from_zip).expanduser())
        meta = take_baseline(note=a.note or f"from {Path(a.from_zip).name}", pack_id=pack_id, files=files)
    else:
        pid = manifest_pack_id() or (load_baseline() or {}).get("pack_id")
        meta = take_baseline(note=a.note or "manual", pack_id=pid)
    print(f"baseline taken {meta['taken']} (v{meta['version']}, {len(meta['files'])} files, env {meta['env']}) -> {baseline_dir()}")


def cmd_diff(a):
    b = build_bundle(out_dir=Path(a.out).expanduser() if a.out else None)
    if b is None:
        print("no changes since the baseline")
        return
    if a.stdout:
        print(b["patch"].read_text(encoding="utf-8"))
        return
    if a.json:
        print(json.dumps({"bundle": str(b["dir"]), "id": b["id"], "files": b["n"], "content_hash": b["content_hash"]}))
        return
    print(b["update"].read_text(encoding="utf-8"))
    print(f"bundle: {b['dir']}")


def cmd_notify(a):
    if a.detach:
        args = ["notify"]
        for flag, val in (("--if-changed", a.if_changed), ("--from-hook", a.from_hook), ("--dry-run", a.dry_run)):
            if val:
                args.append(flag)
        for flag, val in (("--transport", a.transport), ("--to", a.to), ("--resend", a.resend), ("--out", a.out)):
            if val:
                args += [flag, str(val)]
        detach_self(args)
        print("notify detached to the background (log: EVERGREEN_HOME/notify.log)")
        return
    msg = notify(if_changed=a.if_changed, transport=a.transport, to=a.to, dry_run=a.dry_run,
                 resend=Path(a.resend).expanduser() if a.resend else None,
                 mark_sent=Path(a.mark_sent).expanduser() if a.mark_sent else None, via=a.via,
                 out_dir=Path(a.out).expanduser() if a.out else None, from_hook=a.from_hook)
    if msg:
        print(msg)


def cmd_merge(a):
    rep = merge(Path(a.source), Path(a.trunk) if a.trunk else None, dry_run=a.dry_run, use_git=not a.no_git, allow_code=a.allow_code)
    if a.json:
        print(json.dumps(rep, indent=2))
        return
    head = "DRY RUN " if rep["dry_run"] else ""
    print(f"{head}merge of {rep['bundle']} into {rep['trunk']} (git {'yes' if rep['git'] else 'no'})")
    for k in ("applied", "union", "already", "conflicts", "skipped"):
        for x in rep[k]:
            print(f"  {k:<9} {x}")
    for n in rep["notes"]:
        print(f"  note      {n}")
    if rep["conflicts"]:
        print(f"{len(rep['conflicts'])} conflict(s): resolve, delete the .rej/.incoming files, then `git add -A && git commit` (or re-run baseline).")


def cmd_where(a):
    w = where()
    if a.json:
        print(json.dumps(w, indent=2))
        return
    print(f"plugin  {w['plugin_root']} (v{w['version']})")
    print(f"script  {w['script']}")
    print(f"home    {w['home']}   registry {w['registry']}")
    print(f"env     {w['env']}" + ("  (this is the trunk)" if w["is_trunk"] else ""))
    b = w["baseline"]
    print(f"baseline {b['taken']} v{b['version']} pack {b['pack_id']} ({b['note']})" if b else "baseline none (run `evergreen.py baseline`)")
    if w.get("baseline_note"):
        print(f"        {w['baseline_note']}")
    g = w["git"]
    print(f"git     {'repo on ' + str(g['branch']) + (' (dirty)' if g['dirty'] else ' (clean)') if g['repo'] else 'not a repo'}")
    c = w.get("contribute")
    print(f"contribute {c}" if c else "contribute not decided (ask the user; `evergreen.py contribute yes|no`)")
    u = w["update"]
    if u.get("repo"):
        print(f"update  transport={u['transport']} remote={u.get('remote')} trunk={u.get('trunk_branch')} role={u.get('role')}"
              f" ahead={u.get('ahead')} behind={u.get('behind')}" + (f" upstream={u['upstream']}" if u.get("upstream") else ""))
    else:
        print(f"update  transport={u['transport']} (not a git clone)")
    lp = u.get("last_publish")
    if lp:
        print(f"pushed  {lp['date']} {lp['sha']} via {lp['route']} ({lp['branch']}): {lp['subject']}")
    n = w["notify"]
    print(f"notify  auto={n['auto']} to={n['to']} transports={n['transports']} smtp_ready={n['smtp_ready']} mirror={n['outbox_copy_to']}")
    ls = w["last_sent"]
    print(f"last    {ls['date']} via {ls['transport']}: {ls['subject']}" if ls else "last    never sent")
    if w["unsent_bundles"]:
        print(f"unsent  {', '.join(w['unsent_bundles'])}")
    u = w.get("uses")
    print(f"uses    {u['path']} ({u['lines']} lines, last {u['last']})" if u else "uses    none")


def add_parsers(sp, common):
    s = sp.add_parser("baseline", parents=[common], help="snapshot the plugin as the base for diff")
    s.add_argument("--from", dest="from_zip", help="use a pack archive as the baseline instead of the current tree")
    s.add_argument("--note"); s.add_argument("--show", action="store_true"); s.add_argument("--keep-pack-id", action="store_true")
    s.set_defaults(fn=cmd_baseline)
    s = sp.add_parser("diff", parents=[common], help="update bundle: UPDATE.md + changes.patch + manifest.json")
    s.add_argument("--out"); s.add_argument("--stdout", action="store_true"); s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_diff)
    s = sp.add_parser("notify", parents=[common], help="publish the self-update: git (default, same as `publish`) or email the bundle to notify.to when update.transport is email")
    s.add_argument("--if-changed", action="store_true", help="silent when nothing changed or already sent; honours notify.auto")
    s.add_argument("--from-hook", action="store_true", help="called by a session-end hook: the trunk stays quiet unless notify.report_trunk")
    s.add_argument("--transport", choices=TRANSPORTS); s.add_argument("--to"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--detach", action="store_true", help="run in the background (for session-end hooks); --mark-sent is not detachable")
    s.add_argument("--resend", help="bundle folder to send again"); s.add_argument("--mark-sent", help="bundle folder an agent sent")
    s.add_argument("--via", help="transport name to record with --mark-sent"); s.add_argument("--out")
    s.set_defaults(fn=cmd_notify)
    s = sp.add_parser("merge", parents=[common], help="fold a bundle, patch, or saved email into the trunk")
    s.add_argument("source"); s.add_argument("--trunk"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-git", action="store_true"); s.add_argument("--json", action="store_true")
    s.add_argument("--allow-code", action="store_true", help="also merge scripts/, hooks/, .claude-plugin/ (review the patch first)")
    s.set_defaults(fn=cmd_merge)
    s = sp.add_parser("publish", parents=[common], help="commit and push the plugin's self-changes: to the trunk branch as maintainer, else an update branch + PR")
    s.add_argument("--if-changed", action="store_true", help="silent when nothing changed; honours git.auto")
    s.add_argument("--from-hook", action="store_true", help="called by a session-end hook: the trunk's editing clone stays quiet unless notify.report_trunk")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--detach", action="store_true", help="run in the background (for session-end hooks)")
    s.add_argument("--branch", action="store_true", help="always go through an update branch and a pull request, even with write access")
    s.add_argument("--message", help="commit subject to use instead of the generated one")
    s.set_defaults(fn=cmd_publish)
    s = sp.add_parser("pull", parents=[common], help="fast-forward this clone from the trunk; switch back from a merged update branch")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_pull)
    s = sp.add_parser("where", parents=[common], help="plugin root, store, env, baseline, git, notify readiness")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_where)


if __name__ == "__main__":
    sys.exit(eg.main())
