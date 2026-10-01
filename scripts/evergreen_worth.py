#!/usr/bin/env python3
"""evergreen_worth.py - is a skill worth its tokens? The `worth` and `worth-hook` commands of evergreen.py.

Two kinds of evidence, cheapest first (protocol/TESTING.md section 8):

  static   read SKILL.md and its folder: what the skill costs (the description in every session's listing, the body
           on every use), how much of it is specific (commands, paths, versions, names the model cannot guess) rather
           than general advice the model already follows, how much repeats itself, the repo's own docs or another
           skill, what an edit added, and how often the skill is used. It can only warn; it cannot prove a skill helps.
  A/B      read `claude plugin eval` results (aggregate-result.json, a with-plugin and a without-plugin arm per case)
           for the action and outcome cases: pass rate with against without, and what the gain cost in dollars,
           turns and time. This is the proof, and when present it decides the verdict.

  usage    Skill calls in Claude Code's own transcripts over 60 days, split into interactive sessions, subagents and
           headless runs (`claude -p`, the SDK: evals and scripts), so test traffic never counts as use.
  evidence what the unit's evals.json already knows: how many value cases the skill owns, which baselines passed,
           failed or were never run, and which cases pass only on the skill's own script (a process grader).

Verdicts: KEEP (a measured gain, or the same result for less), TRIM (a measured gain at a high price, or a lean
test with a suspect body), CUT (no gain beyond noise at a higher cost, a loss, or a model that already passes
without the skill), UNPROVEN (no A/B yet and nothing suspect), SUSPECT (no A/B yet and the static signals say
mostly general advice, bloat or duplication; run the A/B before investing more). FIX and SUPERSEDED are a person's
rulings, recorded with `--set`: a fixable failure, or a better tool that now does the job.

Failure modes (why a skill is useless; TESTING.md section 8): 1 never fires, 2 already known, 3 no gain, 4 worse,
5 superseded. `modes` lists the ones the evidence points to, each with the evidence.

Pure standard library; fails soft like the rest of evergreen.py.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import evergreen as eg

# Thresholds. The research behind each is in RESEARCH.md (R-20260930-1 to R-20260930-4); change them there first.
LISTING_CAP_CHARS = 1536        # Claude Code: description + when_to_use share this cap in the skill listing
BODY_TOKENS_WARN = 5000         # after compaction only the first 5,000 tokens of an invoked skill are re-attached
BODY_LINES_WARN = 500           # Anthropic's authoring guide and Cursor's rules guide: under 500 lines
SPECIFIC_SHARE_WARN = 0.40      # SkillReducer: over 60 percent of public skill bodies is not actionable
MIN_PROSE_FOR_SHARE = 8         # too few sentences to judge a share
PLATITUDE_WARN = 4              # sentences of general advice with no specific anchor
REPEAT_WARN = 0.12              # share of the body's 8-word shingles that occur twice or more
DOC_OVERLAP_WARN = 0.25         # share of the body's 8-word shingles found in the repo's README, AGENTS.md or CLAUDE.md
PEER_COSINE_WARN = 0.45         # TF-IDF cosine between two skill descriptions that makes selection ambiguous
MUST_WARN = 25                  # hard imperatives (MUST, ALWAYS, NEVER, "do not report done until") that turn optional work mandatory
UPDATE_TOKENS_MIN = 150         # an edit smaller than this is never judged
UPDATE_SPECIFIC_WARN = 0.40     # share of an edit's new sentences that carry a specific anchor
UPDATE_GROWTH_WARN = 0.50       # an edit that grows the body by half or more
AB_COST_CUT = 1.15              # no gain beyond noise and this much more cost: CUT
AB_COST_TRIM = 1.50             # a real gain at this cost ratio or more: TRIM, then re-run
AB_CHEAPER = 0.85               # the same result at this cost ratio or less counts as a gain
AB_CEILING = 0.90               # the model passes the value cases this often without the skill
USAGE_DAYS = 60                 # the window for "never fires": long enough for a skill used once a month to show up
NEVER_FIRES_MIN_AGE_DAYS = 14   # a skill younger than this has not had its chance to be used
MANUAL_VERDICTS = ("KEEP", "TRIM", "FIX", "CUT", "SUPERSEDED")

GENERIC_MARKERS = re.compile(
    r"\b(best practices?|clean code|readab(?:le|ility)|maintainab(?:le|ility)|robust(?:ness)?|high[- ]quality|"
    r"be careful|carefully|thorough(?:ly)?|make sure|ensure|it is (?:important|essential|crucial)|important to|"
    r"always consider|keep in mind|remember to|don't forget|do not forget|pay attention|double[- ]check|"
    r"appropriate(?:ly)?|as needed|when necessary|if needed|where appropriate|properly|correctly|"
    r"effective(?:ly)?|efficient(?:ly)?|comprehensive(?:ly)?|clear and concise|well[- ]structured|"
    r"follow (?:the )?(?:project'?s? )?conventions|handle errors?(?: gracefully)?|edge cases|good practice|"
    r"you are an? (?:expert|senior|world[- ]class)|as an expert|step by step|strive|aim to|try to)\b",
    re.I)
ANCHOR_RES = [
    re.compile(r"`[^`\n]+`"),                                  # inline code
    re.compile(r"https?://\S+"),                               # URLs
    re.compile(r"\d"),                                         # numbers, versions, ports, dates
    re.compile(r"[\w.-]+[/\\][\w.-]+"),                        # paths
    re.compile(r"\b[\w-]+\.(?:md|json|py|sh|ps1|ya?ml|toml|js|ts|cs|txt|csv|html)\b", re.I),  # file names
    re.compile(r"(?<![\w-])--?[a-z][\w-]+"),                   # CLI flags
    re.compile(r"'[^'\n]{3,}'|\"[^\"\n]{3,}\"|‘[^’\n]{3,}’|“[^”\n]{3,}”"),  # quoted phrasings
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"),                     # env vars, acronyms, constants
    re.compile(r"\b[a-z]+[A-Z]\w*\b|\b[A-Z][a-z]+[A-Z]\w*\b"),  # camelCase, CamelCase identifiers
    re.compile(r"(?<=[a-z,;:] )[A-Z][a-z]{2,}"),               # a capitalised word mid-sentence: a product, tool or name
]
MUST_RE = re.compile(r"\b(?:MUST|ALWAYS|NEVER|REQUIRED)\b"  # capitals only: the shouted form
                     r"|(?i:\bdo not (?:report|say|claim) (?:done|finished|complete)\b|\bbefore (?:reporting|saying) done\b)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1\s*$", re.S | re.M)
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(])")
VALUE_KINDS = ("action", "outcome")


# ---------- reading a skill ----------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Top-level `key: value` pairs from YAML frontmatter (quoted, plain, or folded `>`/`|` blocks), and the body."""
    m = eg.FM_RE.match(text)
    if not m:
        return {}, text
    fm, key, buf = {}, None, []

    def flush():
        if key is not None:
            v = " ".join(s.strip() for s in buf if s.strip())
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1].replace('\\"', '"')
            fm[key] = v

    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km and not line[:1].isspace():
            flush()
            key, first = km.group(1).lower(), km.group(2)
            buf = [] if first in (">", "|", ">-", "|-", ">+", "|+") else [first]
        elif key is not None:
            buf.append(line)
    flush()
    return fm, text[m.end():]


def est_tokens(text: str) -> int:
    """About four characters per token for English and markdown; an estimate, labelled as one wherever shown."""
    return int(math.ceil(len(text) / 4.0))


def prose_units(body: str) -> tuple[list[str], int]:
    """Sentences, list items and table rows of the body outside code fences, headings excluded; and fenced code lines."""
    code_lines = sum(m.group(0).count("\n") - 1 for m in FENCE_RE.finditer(body))
    text = FENCE_RE.sub("\n", eg.COMMENT_RE.sub("", body))
    units, para = [], []

    def flush():
        if para:
            joined = " ".join(para)
            units.extend(s.strip() for s in SENT_SPLIT_RE.split(joined) if len(s.strip()) > 12)
            para.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or TABLE_SEP_RE.match(line):
            flush()
            continue
        if line.startswith("|"):
            flush()
            units.append(line)
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", line):
            flush()
            line = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
        para.append(line)
    flush()
    return units, code_lines


def is_specific(sentence: str) -> bool:
    return any(r.search(sentence) for r in ANCHOR_RES)


def shingles(text: str, n: int = 8) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))]


def repeat_share(text: str) -> float:
    sh = shingles(text)
    if len(sh) < 40:
        return 0.0
    seen, dup = set(), 0
    for s in sh:
        if s in seen:
            dup += 1
        seen.add(s)
    return dup / len(sh)


def doc_overlap(body: str, docs: list[Path]) -> tuple[float, str | None]:
    """Largest share of the body's shingles that one of the given documents also contains."""
    sh = set(shingles(body))
    if len(sh) < 40:
        return 0.0, None
    best, which = 0.0, None
    for p in docs:
        try:
            other = set(shingles(p.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            continue
        share = len(sh & other) / len(sh)
        if share > best:
            best, which = share, p.name
    return best, which


def tfidf_cosine(target: str, peers: dict[str, str]) -> list[tuple[float, str]]:
    """Cosine of the target description against each peer's, TF-IDF over the target plus its peers."""
    docs = {"\0target": target, **peers}
    toks = {k: eg.search_tokens(v) for k, v in docs.items()}
    n = len(docs)
    df: dict[str, int] = {}
    for t in toks.values():
        for w in set(t):
            df[w] = df.get(w, 0) + 1

    def vec(ts):
        tf: dict[str, int] = {}
        for w in ts:
            tf[w] = tf.get(w, 0) + 1
        # smoothed IDF (+1): with only two or three skills, plain IDF gives every shared word zero weight
        return {w: c * (math.log((1 + n) / (1 + df[w])) + 1.0) for w, c in tf.items()}

    tv = vec(toks["\0target"])
    tn = math.sqrt(sum(x * x for x in tv.values())) or 1.0
    out = []
    for k in peers:
        pv = vec(toks[k])
        pn = math.sqrt(sum(x * x for x in pv.values())) or 1.0
        out.append((sum(tv.get(w, 0.0) * x for w, x in pv.items()) / (tn * pn), k))
    return sorted(out, reverse=True)


def claude_dir() -> Path:
    """Claude Code's config folder: CLAUDE_CONFIG_DIR when set, else ~/.claude."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def enabled_plugins() -> dict[str, Path]:
    """{name@marketplace: install path} for plugins that are installed and enabled in the user's settings. Every
    cached version of every plugin, disabled ones included, sits under plugins/cache; only these reach the listing."""
    reg = _read_json(claude_dir() / "plugins" / "installed_plugins.json", {}) or {}
    reg = reg.get("plugins", reg) if isinstance(reg, dict) else {}
    on = (_read_json(claude_dir() / "settings.json", {}) or {}).get("enabledPlugins") or {}
    out = {}
    for key, entries in reg.items():
        if not on.get(key):
            continue
        for e in entries if isinstance(entries, list) else [entries]:
            if isinstance(e, dict) and e.get("installPath"):
                out[key] = Path(e["installPath"])
    return out


def installed_as(name: str) -> str | None:
    """Where the agent here loads a skill of this name from: 'plugin <key>', 'user', 'project', or None."""
    for key, root in enabled_plugins().items():
        if (root / "skills" / name / "SKILL.md").exists():
            return f"plugin {key}"
    if (claude_dir() / "skills" / name / "SKILL.md").exists():
        return "user"
    if (Path.cwd() / ".claude" / "skills" / name / "SKILL.md").exists():
        return "project"
    return None


def peer_skill_files(target: Path, extra: list[Path] | None = None) -> list[Path]:
    """SKILL.md files the model would see beside the target: its siblings, the user's skill folders, enabled plugins."""
    home = Path.home()
    pats = [(target.parent.parent, "*/SKILL.md"), (claude_dir() / "skills", "*/SKILL.md"),
            (Path.cwd() / ".claude" / "skills", "*/SKILL.md"), (Path.cwd() / ".agents" / "skills", "*/SKILL.md")]
    plugins = enabled_plugins()
    if plugins:
        pats += [(root, "skills/*/SKILL.md") for root in plugins.values()]
    elif not (claude_dir() / "plugins" / "installed_plugins.json").exists():
        pats.append((home / ".claude" / "plugins" / "cache", "*/*/*/skills/*/SKILL.md"))  # no registry: best guess
    for e in extra or []:
        pats.append((e, "*/SKILL.md"))
        pats.append((e, "skills/*/SKILL.md"))
    seen, out = set(), []
    for root, pat in pats:
        try:
            for p in root.glob(pat):
                key = str(p.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(p)
        except Exception:
            continue
    return out


CMD_RE = re.compile(r"<command-name>/?([A-Za-z0-9:_-]+)</command-name>")
_USES: dict[int, dict[str, dict]] = {}


def in_temp(cwd: str | None) -> bool:
    """A session whose working folder is under the temp directory is a test or a script, not a person's work: eval
    harnesses run `claude -p` in fresh temp folders, and a -p child started from an IDE session inherits the IDE's
    entrypoint, so the entrypoint alone cannot tell (seen 2026-09-30: wikiwright suites logged as claude-vscode)."""
    if not cwd:
        return False
    import tempfile
    c = os.path.normcase(os.path.abspath(cwd))
    roots = {tempfile.gettempdir(), os.environ.get("TEMP") or "", os.environ.get("TMP") or "", "/tmp", "/var/folders"}
    return any(r and c.startswith(os.path.normcase(os.path.abspath(r))) for r in roots)


def transcript_uses(days: int = USAGE_DAYS) -> dict[str, dict]:
    """Skill invocations per skill (plugin prefix dropped) from Claude Code's transcripts, split by where they ran:
    `interactive` (a person's session; typed slash commands count), `subagent` (a sidechain), `headless` (`claude -p`
    or the SDK: evals and scripts, which are tests, not use). Also `sessions` (interactive) and `last` (ISO date).
    The JSONL format is internal and unstable; unknown lines are skipped. Read once per process."""
    if days in _USES:
        return _USES[days]
    out: dict[str, dict] = {}
    root = claude_dir() / "projects"
    cut = datetime.now().timestamp() - days * 86400
    for f in root.glob("**/*.jsonl") if root.exists() else []:
        try:
            if f.stat().st_mtime < cut:
                continue
            fh = f.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sub_file, entry, cwd, seen = "subagents" in f.parts, None, None, set()
        with fh:
            for line in fh:
                if entry is None and '"entrypoint"' in line:
                    m = re.search(r'"entrypoint"\s*:\s*"([^"]+)"', line)
                    entry = m.group(1) if m else None
                if cwd is None and '"cwd"' in line:
                    m = re.search(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', line)
                    cwd = json.loads(f'"{m.group(1)}"') if m else None
                if '"Skill"' not in line and "command-name" not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                msg = o.get("message") if isinstance(o.get("message"), dict) else {}
                content, names = msg.get("content"), []
                if o.get("type") == "user" and not o.get("isSidechain"):
                    text = content if isinstance(content, str) else " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text") \
                        if isinstance(content, list) else ""
                    names = [m.group(1) for m in CMD_RE.finditer(text or "")]
                elif o.get("type") == "assistant" and isinstance(content, list):
                    names = [str((c.get("input") or {}).get("skill")) for c in content if isinstance(c, dict)
                             and c.get("type") == "tool_use" and c.get("name") == "Skill" and (c.get("input") or {}).get("skill")]
                for nm in names:
                    key = nm.strip().lstrip("/").split()[0].split(":")[-1] if nm.strip() else ""
                    if not key:
                        continue
                    where = ("subagent" if sub_file or o.get("isSidechain") else
                             "headless" if str(o.get("entrypoint") or entry or "").startswith("sdk")
                             or in_temp(o.get("cwd") or cwd) else "interactive")
                    r = out.setdefault(key, {"interactive": 0, "subagent": 0, "headless": 0, "sessions": 0, "last": None})
                    r[where] += 1
                    if where == "interactive" and key not in seen:
                        seen.add(key)
                        r["sessions"] += 1
                    ts = str(o.get("timestamp") or "")[:10]
                    if ts and (r["last"] is None or ts > r["last"]):
                        r["last"] = ts
    _USES[days] = out
    return out


def skill_age_days(skill_md: Path) -> int | None:
    """Days since SKILL.md was first committed (None outside git): a young skill has not had its chance to be used."""
    first = eg.git(["log", "--follow", "--diff-filter=A", "--format=%as", "--", skill_md.name], skill_md.parent)
    if not first:
        return None
    try:
        return (date.today() - date.fromisoformat(first.strip().splitlines()[-1])).days
    except ValueError:
        return None


def repo_docs(skill_dir: Path) -> list[Path]:
    top = eg.git(["rev-parse", "--show-toplevel"], skill_dir)
    if not top:
        return []
    root = Path(top)
    return [root / n for n in ("README.md", "AGENTS.md", "CLAUDE.md") if (root / n).exists()]


def unreferenced_files(skill_dir: Path, text: str) -> list[str]:
    """Bundled files SKILL.md never names: the model finds them only by listing the folder, which it rarely does."""
    out = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file() or p.name in ("SKILL.md", "evergreen.json") or any(
                part in eg.PACK_EXCLUDE or part in ("evals",) for part in p.relative_to(skill_dir).parts):
            continue
        rel = p.relative_to(skill_dir).as_posix()
        if p.name in ("RESEARCH.md", "CHANGELOG.md", "LEARNINGS.md", "TESTS.md", "MAINTENANCE.md", "LEARNINGS-ARCHIVE.md"):
            continue  # evergreen companions: maintenance records, not content for the task
        parts = rel.split("/")
        # a folder counts when it is named on its own (`templates/npm/`), not as the start of another file's path
        named = rel in text or p.name in text or any(
            re.search(re.escape("/".join(parts[:i])) + r"/?(?![\w./-])", text) for i in range(1, len(parts)))
        if not named:
            out.append(rel)
    return out[:10]


def git_old_text(path: Path, rev: str) -> str | None:
    top = eg.git(["rev-parse", "--show-toplevel"], path.parent)
    if not top:
        return None
    try:
        rel = path.resolve().relative_to(Path(top).resolve()).as_posix()
        r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=top, capture_output=True, timeout=20)
        return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None
    except Exception:
        return None


# ---------- static report ----------

def static_report(skill_md: Path, against: str | None = None, peers: bool = True, uses: bool = True,
                  extra_peer_roots: list[Path] | None = None) -> dict:
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    name = fm.get("name") or skill_md.parent.name
    listing = (fm.get("description") or "") + (" " + fm["when_to_use"] if fm.get("when_to_use") else "")
    units, code_lines = prose_units(body)
    specific = [u for u in units if is_specific(u)]
    platitudes = [u for u in units if not is_specific(u) and GENERIC_MARKERS.search(u)]
    anchors = sum(len(r.findall(body)) for r in ANCHOR_RES[:2]) + code_lines
    body_tokens = est_tokens(body)
    r = {
        "skill": name, "path": str(skill_md),
        "listing_chars": len(listing), "listing_tokens": est_tokens(listing),
        "body_lines": len(body.splitlines()), "body_tokens": body_tokens,
        "prose_units": len(units), "specific_share": round(len(specific) / len(units), 2) if units else None,
        "platitudes": len(platitudes), "platitude_examples": [p[:90] for p in platitudes[:3]],
        "code_lines": code_lines, "anchors_per_1k": round(1000 * anchors / body_tokens, 1) if body_tokens else 0,
        "must_count": len(MUST_RE.findall(body)),
        "repeat_share": round(repeat_share(body), 2),
        "warnings": [],
    }
    w = r["warnings"]
    if not fm.get("description"):
        w.append("no description: the model cannot choose this skill from the listing")
    if len(listing) > LISTING_CAP_CHARS:
        w.append(f"description is {len(listing)} characters; Claude Code truncates the listing entry at {LISTING_CAP_CHARS}")
    if body_tokens > BODY_TOKENS_WARN or r["body_lines"] > BODY_LINES_WARN:
        w.append(f"body is about {body_tokens:,} tokens ({r['body_lines']} lines), paid on every use; move detail to "
                 f"references/ that load on demand")
    if len(units) >= MIN_PROSE_FOR_SHARE and r["specific_share"] is not None and r["specific_share"] < SPECIFIC_SHARE_WARN:
        w.append(f"mostly general advice: only {int(100 * r['specific_share'])}% of {len(units)} sentences name a command, "
                 f"path, value or tool the model could not guess")
    if len(platitudes) >= PLATITUDE_WARN:
        w.append(f"{len(platitudes)} sentences of advice the model already follows (e.g. \"{r['platitude_examples'][0]}\")")
    if r["repeat_share"] >= REPEAT_WARN:
        w.append(f"{int(100 * r['repeat_share'])}% of the body repeats itself")
    if r["must_count"] >= MUST_WARN:
        w.append(f"{r['must_count']} hard imperatives (MUST, ALWAYS, NEVER): mandatory procedure is the largest cause of "
                 f"skill-induced cost regressions; keep only the ones a test needs")
    docs = [d for d in repo_docs(skill_md.parent) if d.resolve() != skill_md.resolve()]
    ov, which = doc_overlap(body, docs)
    r["doc_overlap"] = round(ov, 2)
    if ov >= DOC_OVERLAP_WARN:
        w.append(f"{int(100 * ov)}% of the body is already in the repo's {which}, which the agent reads anyway")
    unref = unreferenced_files(skill_md.parent, text)
    r["unreferenced_files"] = unref
    if unref:
        w.append("bundled files SKILL.md never names (unreachable unless linked): " + ", ".join(unref[:4]))
    r["nearest_peer"] = None
    if peers and fm.get("description"):
        pd = {}
        for p in peer_skill_files(skill_md, extra_peer_roots):
            if p.resolve() == skill_md.resolve():
                continue
            try:
                pfm, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            pname = pfm.get("name") or p.parent.name
            if pname != name and pfm.get("description") and pname not in pd:
                pd[pname] = pfm["description"]
        if pd:
            cos, pname = tfidf_cosine(listing, pd)[0]
            # a pair whose descriptions name each other has already drawn the line between them
            told = pname.lower() in listing.lower() or name.lower() in pd[pname].lower()
            r["nearest_peer"] = {"skill": pname, "cosine": round(cos, 2), "peers": len(pd), "names_each_other": told}
            if cos >= PEER_COSINE_WARN and not told:
                w.append(f"description is close to {pname} (TF-IDF cosine {cos:.2f}): merge them or add a 'Not for ...' "
                         f"clause, or the model will pick the wrong one")
    r["change"] = None
    if against:
        old = git_old_text(skill_md, against)
        if old is not None and old != text:
            _, old_body = parse_frontmatter(old)
            old_units = set(prose_units(old_body)[0])
            new_units = [u for u in units if u not in old_units]
            added = est_tokens(body) - est_tokens(old_body)
            spec = sum(1 for u in new_units if is_specific(u))
            growth = added / max(1, est_tokens(old_body))
            r["change"] = {"against": against, "added_tokens": added, "new_sentences": len(new_units),
                           "new_specific": spec, "growth": round(growth, 2)}
            if added >= UPDATE_TOKENS_MIN and new_units and spec / len(new_units) < UPDATE_SPECIFIC_WARN:
                w.append(f"this edit adds about {added:,} tokens but only {spec} of its {len(new_units)} new sentences say "
                         f"something specific")
            elif added >= UPDATE_TOKENS_MIN and growth >= UPDATE_GROWTH_WARN:
                w.append(f"this edit grows the body by {int(100 * growth)}% (about {added:,} tokens); prove the extra "
                         f"text earns its cost with the A/B")
    r["uses_30d"], r["usage"], r["installed"], r["age_days"] = None, None, None, None
    if uses:
        if eg.uses_path().exists():
            r["uses_30d"] = len(eg.read_uses(name, days=30))
        r["usage"] = {"days": USAGE_DAYS, **transcript_uses(USAGE_DAYS).get(
            name, {"interactive": 0, "subagent": 0, "headless": 0, "sessions": 0, "last": None})}
        r["installed"] = installed_as(name)
        r["age_days"] = skill_age_days(skill_md)
    score = len(w)
    heavy = any(s.startswith(("mostly general", "this edit adds")) for s in w)
    r["static"] = "SUSPECT" if score >= 2 or heavy else ("CHECK" if score == 1 else "LEAN")
    return r


# ---------- A/B from `claude plugin eval` ----------

def case_kinds(unit: Path) -> dict[str, dict]:
    """Cases of the unit's evals.json by id, each with `_skill`: the skill it is about (eg.case_skill)."""
    ev = unit / "evals" / "evals.json"
    try:
        data = json.loads(ev.read_text(encoding="utf-8"))
        return {c["id"]: {**c, "_skill": eg.case_skill(c, data)} for c in data.get("evals", [])
                if isinstance(c, dict) and c.get("id")}
    except Exception:
        return {}


BASELINE_NOT_RUN = re.compile(r"not (?:yet )?run|\(expected|^expected|filled by the first run|^n/?a\b|^-?$", re.I)
BASELINE_PASSED = re.compile(r"\bpass(?:ed|es)?\s+anyway|\bpassed\b(?! only)|\bpasses\b|\bredundant\b|"
                             r"\bbaseline (?:also )?(?:pass|did|wrote|built|found|named)", re.I)
BASELINE_FAILED = re.compile(r"\bfail(?:s|ed)?\b(?! only)|\bFAIL\b|\b0/\d|never (?:ran|run|wrote|created|opened)|"
                             r"did not|didn't|no (?:file|notes|beat files|log line|saved answer)|"
                             r"writes? (?:a|the) [\w ]{0,30}in (?:chat|the reply)", re.I)
SCRIPT_RE = re.compile(r"([\w-]+)\\?\.(py|mjs|cjs|js|sh|ps1)\b")


def baseline_status(case: dict) -> str:
    """'passed', 'failed', 'not-run' or 'described' from a case's `redundant` flag and free-text `baseline` note.
    A note that predicts the baseline ('expected, not yet run', 'filled by the first run') is not a run."""
    if case.get("redundant"):
        return "passed"
    text = str(case.get("baseline") or "").strip()
    if not text or BASELINE_NOT_RUN.search(text[:60]):
        return "not-run"
    if text.lower().startswith(("without the skill", "skill absent: expected")) and not re.search(r"\b20\d\d-\d\d-\d\d\b", text):
        return "not-run"  # a prediction of what a fresh session does, never dated: no run behind it
    passed, failed = bool(BASELINE_PASSED.search(text)), bool(BASELINE_FAILED.search(text))
    if passed and not failed:
        return "passed"
    if failed and not passed:
        return "failed"
    return "described"


def _evidence_leaves(ev) -> list[dict]:
    if not isinstance(ev, dict):
        return []
    out = [ev] if ev.get("type") else []
    for k in ("or", "and"):
        out += _evidence_leaves(ev.get(k))
    for k in ("all", "any"):
        for x in ev.get(k) or []:
            out += _evidence_leaves(x)
    for s in ev.get("steps") or []:
        out.append({"type": "trace", **s})
    return out


def _unit_scripts(unit: Path) -> set[str]:
    names = set()
    for p in unit.rglob("*"):
        if p.suffix in (".py", ".mjs", ".cjs", ".js", ".sh", ".ps1") and not any(
                part in (".git", "node_modules", "fixtures", "results") for part in p.parts):
            names.add(p.stem.lower())
    return names


def process_only(case: dict, scripts: set[str]) -> bool:
    """True when every way the case can pass is a call to one of the unit's own scripts (or the Skill tool): the
    baseline cannot pass it whatever result it produces, so a with-arm gain proves the route, not a better result."""
    leaves = [x for x in _evidence_leaves(case.get("evidence")) if x.get("type") not in ("sequence",)]
    if not leaves:
        return False
    for leaf in leaves:
        if leaf.get("type") != "trace":
            return False
        if str(leaf.get("tool") or "") == "Skill":
            continue
        pat = str(leaf.get("input_match") or "") + " " + str(leaf.get("must_contain") or "")
        if not any(m.group(1).lower() in scripts for m in SCRIPT_RE.finditer(pat)):
            return False
    return True


def evidence_report(unit: Path, skill: str | None = None) -> dict:
    """What the unit's evals.json says about the value of `skill` (None: every case): value cases it owns, the status
    of each case's recorded baseline, and the cases graded only on the unit's own scripts."""
    kinds = case_kinds(unit)
    scripts = _unit_scripts(unit) if kinds else set()
    rep = {"value_cases": [], "baseline": {"passed": [], "failed": [], "not-run": [], "described": []},
           "process_only": [], "trigger_cases": 0}
    for cid, c in kinds.items():
        if skill and c.get("_skill", "").split(":")[-1] != skill:
            continue
        if c.get("kind") == "trigger" and not c.get("decoy") and not cid.startswith("decoy"):
            rep["trigger_cases"] += 1
        if c.get("kind") not in VALUE_KINDS or c.get("decoy"):
            continue
        rep["value_cases"].append(cid)
        rep["baseline"][baseline_status(c)].append(cid)
        if process_only(c, scripts):
            rep["process_only"].append(cid)
    return rep


def failure_modes(st: dict, ev: dict | None, ab: dict | None, manual: dict | None = None) -> list[dict]:
    """The useless-skill failure modes the evidence points to (TESTING.md section 8), each with its evidence."""
    modes = []
    u, inst, age = st.get("usage"), st.get("installed"), st.get("age_days")
    if u is not None and inst and u["interactive"] + u["subagent"] == 0 and (age is None or age >= NEVER_FIRES_MIN_AGE_DAYS):
        modes.append({"mode": 1, "name": "never fires",
                      "evidence": f"installed ({inst}) and no Skill call in {u['days']} days of transcripts"
                                  + (f" ({u['headless']} headless test runs only)" if u["headless"] else "")})
    if ev and ev["value_cases"]:
        known = [c for c in ev["value_cases"] if c not in ev["baseline"]["not-run"] + ev["baseline"]["described"]]
        if known and set(known) <= set(ev["baseline"]["passed"]):
            modes.append({"mode": 2, "name": "already known",
                          "evidence": f"every value case with a recorded baseline passed without the skill: {', '.join(known)}"})
    if st.get("probe") and st["probe"].get("coverage") is not None and st["probe"]["coverage"] >= 0.8:
        modes.append({"mode": 2, "name": "already known",
                      "evidence": f"the knowledge probe covered {int(100 * st['probe']['coverage'])}% of the key anchors"})
    if ab:
        if ab["delta"] <= -ab["margin"]:
            modes.append({"mode": 4, "name": "worse", "evidence": f"pass rate {ab['delta'] * 100:+.0f} points with the skill"})
        elif ab["delta"] < ab["margin"]:
            cr = ab.get("cost_ratio") or 1.0
            if cr >= AB_COST_CUT:
                modes.append({"mode": 4, "name": "worse", "evidence": f"same result at {cr}x the cost"})
            else:
                modes.append({"mode": 3, "name": "no gain", "evidence": f"{ab['delta'] * 100:+.0f} points, inside the "
                                                                       f"{ab['margin'] * 100:.0f}-point noise margin"})
    if manual and manual.get("verdict") == "SUPERSEDED":
        modes.append({"mode": 5, "name": "superseded", "evidence": manual.get("replaced_by") or manual.get("why") or ""})
    return modes


def evidence_gaps(ev: dict | None, ab: dict | None) -> list[str]:
    """Why the worth of a skill is not measured yet: the things to write or run before any verdict is earned."""
    if ev is None:
        return ["no evals/evals.json: write value cases first (evergreen-test Step 2)"]
    gaps = []
    if not ev["value_cases"]:
        gaps.append("no value case (action or outcome): the A/B has nothing to measure")
    elif not ab and not [c for c in ev["value_cases"] if c in ev["baseline"]["passed"] + ev["baseline"]["failed"]]:
        gaps.append("no baseline was ever run for its value cases: `worth --ab` runs both arms")
    if ev["value_cases"] and set(ev["value_cases"]) <= set(ev["process_only"]):
        gaps.append("every value case passes only on the skill's own script: a gain proves the route, not a better "
                    "result; add a case graded on the result")
    return gaps


def result_files(unit: Path, results: list[str] | None) -> list[Path]:
    paths = []
    if results:
        for r in results:
            p = Path(r).expanduser()
            paths += [p] if p.is_file() else sorted(p.rglob("aggregate-result.json"))
    else:
        paths = sorted((unit / "evals" / "results").glob("*/aggregate-result.json"))
    return paths


def ab_report(unit: Path, results: list[str] | None = None, skill: str | None = None, case_glob: str | None = None) -> dict | None:
    """Latest with-and-without result per value case (action or outcome), merged across result files."""
    kinds = case_kinds(unit)
    latest: dict[str, tuple[str, dict]] = {}
    for f in result_files(unit, results):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (d.get("suite") or {}).get("ablation", "with-without") != "with-without":
            continue
        for c in d.get("cases") or []:
            cid = c.get("name") or ""
            meta = kinds.get(cid, {})
            kind = meta.get("kind") or cid.split("-")[0]
            if kind not in VALUE_KINDS or meta.get("decoy"):
                continue
            if case_glob and not fnmatch.fnmatch(cid, case_glob):
                continue
            if skill and meta.get("_skill", "").split(":")[-1] != skill:
                continue  # in a plugin, a case counts for the one skill it names
            arms = c.get("arms") or {}
            if not arms.get("with") or not arms.get("without"):
                continue
            stamp = d.get("startedAt") or f.parent.name
            if cid not in latest or stamp > latest[cid][0]:
                latest[cid] = (stamp, c)
    if not latest:
        return None
    rows, n_with, n_wo, p_with, p_wo = [], 0, 0, 0, 0
    cost = {"with": 0.0, "without": 0.0}
    turns = {"with": 0.0, "without": 0.0}
    secs = {"with": 0.0, "without": 0.0}
    for cid, (_, c) in sorted(latest.items()):
        pw = [bool(r.get("passed")) for r in c["arms"]["with"] if not r.get("error")]
        po = [bool(r.get("passed")) for r in c["arms"]["without"] if not r.get("error")]
        if not pw or not po:
            continue
        n_with += len(pw); n_wo += len(po); p_with += sum(pw); p_wo += sum(po)
        for arm in ("with", "without"):
            runs = [r for r in c["arms"][arm] if not r.get("error")]
            cost[arm] += sum(float(r.get("costUsd") or 0) for r in runs) / len(runs)
            turns[arm] += sum(float(r.get("turns") or 0) for r in runs) / len(runs)
            secs[arm] += sum(float(r.get("durationSeconds") or 0) for r in runs) / len(runs)
        rows.append({"case": cid, "with": f"{sum(pw)}/{len(pw)}", "without": f"{sum(po)}/{len(po)}",
                     "delta": round(sum(pw) / len(pw) - sum(po) / len(po), 2)})
    if not rows:
        return None
    a, b = p_with / n_with, p_wo / n_wo
    se = math.sqrt(a * (1 - a) / n_with + b * (1 - b) / n_wo)
    margin = max(2 * se, 1.0 / min(n_with, n_wo))  # about a 95% two-sided test, floored at one run's worth
    ratio = lambda k: round(k["with"] / k["without"], 2) if k["without"] else None  # noqa: E731
    return {"cases": rows, "runs_with": n_with, "runs_without": n_wo, "pass_with": round(a, 2), "pass_without": round(b, 2),
            "delta": round(a - b, 2), "margin": round(margin, 2), "cost_ratio": ratio(cost), "turns_ratio": ratio(turns),
            "time_ratio": ratio(secs), "cost_with_usd": round(cost["with"], 4), "cost_without_usd": round(cost["without"], 4)}


def verdict(static: dict, ab: dict | None) -> tuple[str, str]:
    if ab:
        d, m, cr = ab["delta"], ab["margin"], ab["cost_ratio"] or 1.0
        pts = f"{d * 100:+.0f} points (noise margin {m * 100:.0f})"
        if ab["pass_with"] == 0 and ab["pass_without"] == 0:
            return "UNPROVEN", "every value case failed in both arms: the cases are broken or too hard to judge anything"
        if d <= -m:
            return "CUT", f"worse with the skill: {pts}; the baseline wins, retire it rather than tune it"
        if d < m:
            if ab["pass_without"] >= AB_CEILING:
                return "CUT", f"the model already passes {int(ab['pass_without'] * 100)}% without the skill ({pts}); " \
                              f"write a harder case the skill exists for, or retire it"
            if cr <= AB_CHEAPER:
                return "KEEP", f"same result ({pts}) at {cr}x the cost: the skill saves work"
            if cr >= AB_COST_CUT:
                return "CUT", f"no gain beyond noise ({pts}) at {cr}x the cost"
            return "UNPROVEN", f"no gain beyond noise ({pts}) at about the same cost; add runs or sharper cases before deciding"
        if cr >= AB_COST_TRIM or static["static"] == "SUSPECT":
            return "TRIM", f"a real gain ({pts}) at {cr}x the cost; cut the general advice and re-run to keep the gain for less"
        return "KEEP", f"a real gain: {pts} at {cr}x the cost"
    if static["static"] == "SUSPECT":
        return "SUSPECT", "static signals say the skill is mostly cost; run the A/B (with and without) before investing more"
    return "UNPROVEN", "nothing suspect on reading; only the A/B shows whether it helps"


# ---------- targets, output, recording ----------

def find_skill_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if (target / "SKILL.md").exists():
        return [target / "SKILL.md"]
    found = sorted(target.glob("skills/*/SKILL.md")) or sorted(target.glob("*/SKILL.md"))
    return found


def unit_for(skill_md: Path, target: Path) -> Path | None:
    for d in (skill_md.parent, target if target.is_dir() else target.parent, skill_md.parent.parent.parent):
        if (d / "evergreen.json").exists():
            return d
    return None


def recorded(unit: Path | None, skill: str) -> dict | None:
    """The skill's entry in its unit's evergreen.json `worth` block, if any."""
    if unit is None:
        return None
    st = _read_json(unit / "evergreen.json", {}) or {}
    block = st.get("worth") if isinstance(st.get("worth"), dict) else {}
    v = (block.get("skills") or {}).get(skill)
    return v if isinstance(v, dict) else None


def assess(target: Path, against: str | None = None, results: list[str] | None = None, peers: bool = True,
           case_glob: str | None = None, uses: bool = True) -> list[dict]:
    out = []
    files = find_skill_files(target)
    for f in files:
        st = static_report(f, against=against, peers=peers, uses=uses)
        unit = unit_for(f, target)
        ab, ev = None, None
        # a skill that is its own unit owns every case; a skill inside a plugin owns only the cases that name it
        own = unit is not None and unit.resolve() == f.parent.resolve()
        if unit is not None or results:
            ab = ab_report(unit or f.parent, results, skill=None if own else st["skill"], case_glob=case_glob)
        evals_home = unit if unit is not None and (unit / "evals" / "evals.json").exists() else (
            f.parent if (f.parent / "evals" / "evals.json").exists() else None)
        if evals_home is not None:
            ev = evidence_report(evals_home, skill=None if evals_home.resolve() == f.parent.resolve() else st["skill"])
        v, why = verdict(st, ab)
        if ab and ev and ev["process_only"] and ab["delta"] >= ab["margin"]:
            gain = [c["case"] for c in ab["cases"] if c["delta"] > 0]
            if gain and set(gain) <= set(ev["process_only"]):
                why += "; the gain is only on cases graded by the skill's own script, so check the result is better too"
        manual = recorded(unit, st["skill"])
        if manual and manual.get("manual"):
            v, why = manual["verdict"], f"{manual.get('why') or 'set by hand'} (set by hand {manual.get('checked')})"
        st.update({"ab": ab, "evidence": ev, "verdict": v, "why": why, "unit": str(unit) if unit else None})
        st["modes"] = failure_modes(st, ev, ab, manual)
        st["gaps"] = evidence_gaps(ev, ab)
        u = st.get("usage") or {}
        st["triage"] = round((st["listing_tokens"] + st["body_tokens"]) / (u.get("interactive", 0) + u.get("subagent", 0) + 1))
        out.append(st)
    return out


def plugin_ab(target: Path, results: list[str] | None, case_glob: str | None) -> dict | None:
    """The whole plugin's A/B (every value case, whatever skill it names), for a plugin root with several skills."""
    if not (target.is_dir() and (target / "evergreen.json").exists() and len(find_skill_files(target)) > 1):
        return None
    ab = ab_report(target, results, case_glob=case_glob)
    if not ab:
        return None
    v, why = verdict({"static": "LEAN"}, ab)
    return {**ab, "verdict": v, "why": why}


def render(r: dict) -> str:
    L = [f"worth  {r['skill']}  ({r['path']})"]
    L.append(f"  cost     listing ~{r['listing_tokens']:,} tokens in every session · body ~{r['body_tokens']:,} tokens "
             f"({r['body_lines']} lines) on every use")
    share = f"{int(100 * r['specific_share'])}% specific" if r["specific_share"] is not None else "too short to judge"
    L.append(f"  content  {r['prose_units']} sentences, {share} · {r['platitudes']} general-advice · "
             f"{r['code_lines']} code lines · {r['must_count']} hard imperatives · repeats {int(100 * r['repeat_share'])}%")
    if r.get("nearest_peer"):
        p = r["nearest_peer"]
        L.append(f"  overlap  nearest of {p['peers']} skills: {p['skill']} (cosine {p['cosine']:.2f}"
                 + (", the descriptions name each other)" if p.get("names_each_other") else ")")
                 + (f" · repo docs {int(100 * r['doc_overlap'])}%" if r.get("doc_overlap") else ""))
    if r.get("change"):
        c = r["change"]
        L.append(f"  change   vs {c['against']}: {c['added_tokens']:+,} tokens, {c['new_specific']} of {c['new_sentences']} "
                 f"new sentences specific")
    u = r.get("usage")
    if u is not None:
        L.append(f"  uses     {u['interactive']} interactive ({u['sessions']} sessions), {u['subagent']} subagent, "
                 f"{u['headless']} headless in {u['days']} days (transcripts)"
                 + (f" · last {u['last']}" if u.get("last") else "")
                 + f" · {'loaded as ' + r['installed'] if r.get('installed') else 'not installed here'}"
                 + (f" · {r['uses_30d']} in 30 days (use log)" if r.get("uses_30d") is not None else ""))
    ev = r.get("evidence")
    if ev is not None:
        b = ev["baseline"]
        L.append(f"  evidence {len(ev['value_cases'])} value case(s): baseline passed {len(b['passed'])}, failed "
                 f"{len(b['failed'])}, never run {len(b['not-run'])}, unclear {len(b['described'])} · "
                 f"{len(ev['process_only'])} graded only on the skill's own script")
    ab = r.get("ab")
    if ab:
        L.append(f"  A/B      {len(ab['cases'])} value case(s), {ab['runs_with']}/{ab['runs_without']} runs: pass "
                 f"{int(ab['pass_with'] * 100)}% with, {int(ab['pass_without'] * 100)}% without · cost x{ab['cost_ratio']} · "
                 f"turns x{ab['turns_ratio']} · time x{ab['time_ratio']}")
    else:
        L.append("  A/B      none yet (claude plugin eval, with-without, on the action and outcome cases)")
    if r.get("probe"):
        p = r["probe"]
        L.append(f"  probe    without the skill the answer named {p['covered']} of {p['anchors']} key anchors "
                 f"({int(100 * (p['coverage'] or 0))}%); answer in {p['out']}")
    L.append(f"  verdict  {r['verdict']}  {r['why']}")
    for m in r.get("modes") or []:
        L.append(f"  mode {m['mode']}   {m['name']}: {m['evidence']}")
    for g in r.get("gaps") or []:
        L.append(f"  gap      {g}")
    for w in r["warnings"]:
        L.append(f"    - {w}")
    return "\n".join(L)


def render_triage(results: list[dict]) -> str:
    """One row per skill, costliest per use first: (listing + body tokens) / (interactive + subagent uses + 1)."""
    rows = sorted(results, key=lambda r: -r.get("triage", 0))
    L = [f"{'triage':>7} {'skill':28} {'loaded':8} {'uses i/s/h':>11} {'listing':>7} {'body':>6} {'spec':>5} "
         f"{'value':>5} {'base P/F/N':>10}  {'verdict':10} modes / gaps"]
    for r in rows:
        u = r.get("usage") or {}
        ev = r.get("evidence")
        b = ev["baseline"] if ev else None
        sp = f"{int(100 * r['specific_share'])}%" if r["specific_share"] is not None else "-"
        flags = [f"{m['mode']}:{m['name']}" for m in r.get("modes") or []]
        flags += ["no value case" if "no value case" in g else "never baselined" if "baseline" in g else
                  "process-only" if "route" in g else "no evals" for g in r.get("gaps") or []]
        flags += ["static " + r["static"]] if r["static"] != "LEAN" else []
        bs = "%d/%d/%d" % (len(b["passed"]), len(b["failed"]), len(b["not-run"]) + len(b["described"])) if b else "-"
        L.append(f"{r.get('triage', 0):>7,} {r['skill'][:28]:28} {('yes' if r.get('installed') else 'no'):8} "
                 f"{u.get('interactive', 0):>3}/{u.get('subagent', 0)}/{u.get('headless', 0):<3} "
                 f"{r['listing_tokens']:>7,} {r['body_tokens']:>6,} {sp:>5} "
                 f"{(len(ev['value_cases']) if ev else 0):>5} "
                 f"{bs:>10}  "
                 f"{r['verdict']:10} {'; '.join(flags)}")
    tl = sum(r["listing_tokens"] for r in results if r.get("installed"))
    L.append(f"-- {len(results)} skills; listing ~{tl:,} tokens in every session for the {sum(1 for r in results if r.get('installed'))} "
             f"loaded here; uses are Skill calls in transcripts (i interactive, s subagent, h headless tests); "
             f"base P/F/N = value-case baselines passed / failed / not run or unclear")
    return "\n".join(L)


def record(results: list[dict]) -> list[str]:
    """Write each skill's verdict into its unit's evergreen.json `worth` block; returns the units written."""
    written = []
    by_unit: dict[str, list[dict]] = {}
    for r in results:
        if r.get("unit"):
            by_unit.setdefault(r["unit"], []).append(r)
    for u, rs in by_unit.items():
        d, st = eg.load_state(u)
        block = st.get("worth") if isinstance(st.get("worth"), dict) else {}
        skills = block.get("skills") if isinstance(block.get("skills"), dict) else {}
        for r in rs:
            ab = r.get("ab") or {}
            old = skills.get(r["skill"]) if isinstance(skills.get(r["skill"]), dict) else {}
            entry = {"verdict": r["verdict"], "why": r["why"], "body_tokens": r["body_tokens"],
                     "listing_tokens": r["listing_tokens"], "specific_share": r["specific_share"],
                     "delta": ab.get("delta"), "cost_ratio": ab.get("cost_ratio"),
                     "modes": [m["mode"] for m in r.get("modes") or []], "gaps": len(r.get("gaps") or []),
                     "checked": date.today().isoformat()}
            if r.get("usage"):
                entry["uses"] = {k: r["usage"][k] for k in ("days", "interactive", "subagent", "headless")}
            if r.get("probe"):
                entry["probe_coverage"] = r["probe"].get("coverage")
            if old.get("manual"):  # a person's ruling stands until they change it; the measurements still refresh
                entry.update({k: old[k] for k in ("verdict", "why", "manual", "replaced_by", "ruled") if k in old})
            skills[r["skill"]] = entry
        st["worth"] = {"checked": date.today().isoformat(), "skills": skills}
        eg.save_state(d, st)
        written.append(str(d))
    return written


def set_manual(unit: Path, skill: str, verdict_: str, why: str, replaced_by: str | None = None) -> None:
    """Record a person's ruling (KEEP, TRIM, FIX, CUT, SUPERSEDED) in the unit's worth block; later `--record` runs keep it."""
    d, st = eg.load_state(unit)
    block = st.get("worth") if isinstance(st.get("worth"), dict) else {}
    skills = block.get("skills") if isinstance(block.get("skills"), dict) else {}
    entry = skills.get(skill) if isinstance(skills.get(skill), dict) else {}
    entry.update({"verdict": verdict_, "why": why, "manual": True, "ruled": date.today().isoformat(),
                  "checked": entry.get("checked") or date.today().isoformat()})
    if replaced_by:
        entry["replaced_by"] = replaced_by
    skills[skill] = entry
    st["worth"] = {"checked": block.get("checked") or date.today().isoformat(), "skills": skills}
    eg.save_state(d, st)


def worth_flags(st: dict) -> list[str]:
    """Audit flags from a recorded worth block: only verdicts and failure modes that ask for a decision."""
    skills = ((st.get("worth") or {}).get("skills") or {}) if isinstance(st.get("worth"), dict) else {}
    out = []
    for name, v in sorted(skills.items()):
        if not isinstance(v, dict):
            continue
        tag = f":{name}" if len(skills) > 1 else ""
        if v.get("verdict") in ("CUT", "TRIM", "SUSPECT", "FIX", "SUPERSEDED"):
            out.append(f"worth:{v['verdict']}{tag}")
        elif 1 in (v.get("modes") or []):
            out.append(f"worth:UNUSED{tag}")
    return out


def wrap(skill_dir: Path, out: Path) -> tuple[Path, list[str]]:
    """A throwaway plugin around one standalone skill, so `claude plugin eval` can run it with and without:
    <out>/.claude-plugin/plugin.json, <out>/skills/<name>/ (a copy) and <out>/evals/cases/ from the skill's evals.json."""
    import shutil
    fm, _ = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    name = fm.get("name") or skill_dir.name
    dest = out / "skills" / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "evals"))
    (out / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    eg.write_lf(out / ".claude-plugin" / "plugin.json",
                json.dumps({"name": f"{name}-worth", "version": "0.0.0", "description": f"A/B wrapper for {name}"}, indent=2) + "\n")
    notes = []
    if (skill_dir / "evals" / "evals.json").exists():
        written, kept, n = eg.eval_export(skill_dir, out=out / "evals" / "cases", force=True)
        notes += n + [f"cases: {', '.join(written + kept) or 'none'}"]
    else:
        notes.append("no evals/evals.json: write action and outcome cases first (evergreen-test), then wrap again")
    return out, notes


def cmd_worth(a):
    targets = [Path(t).expanduser() for t in a.target]
    missing = [t for t in targets if not t.exists()]
    if missing:
        print(f"[worth] no such path: {', '.join(map(str, missing))}")
        return
    global USAGE_DAYS
    USAGE_DAYS = a.days
    if len(targets) > 1 or a.triage:
        results = []
        for t in targets:
            results += assess(t, against=a.against, results=None, peers=not a.no_peers, case_glob=a.case)
        if not results:
            print("[worth] no SKILL.md under the given paths")
            return
        print(json.dumps(results, indent=2) if a.json else render_triage(results))
        if a.record:
            for u in record(results):
                print(f"[worth] recorded in {u}/evergreen.json")
        return
    target = targets[0]
    if a.set:
        files = find_skill_files(target)
        unit = unit_for(files[0], target) if len(files) == 1 else None
        if unit is None:
            print("[worth] --set takes one skill whose unit has an evergreen.json")
            return
        fm, _ = parse_frontmatter(files[0].read_text(encoding="utf-8", errors="replace"))
        name = fm.get("name") or files[0].parent.name
        set_manual(unit, name, a.set, a.why or "", a.replaced_by)
        print(f"[worth] {name}: {a.set} set by hand in {unit / 'evergreen.json'}")
        return
    probe_rep = None
    if a.ab or a.probe:
        import evergreen_ab as eab
        files = find_skill_files(target)
        if len(files) != 1:
            print("[worth] --ab and --probe take one skill folder")
            return
        if a.probe:
            probe_rep = eab.probe(files[0].parent, unit_for(files[0], target), prompt=a.prompt, out=a.out,
                                  model=a.model, blind=a.blind)
            print(eab.render_probe(probe_rep) + "\n")
        if a.ab:
            out = eab.run_ab(files[0].parent, unit_for(files[0], target), runs=a.runs, case_glob=a.case, out=a.out,
                             model=a.model, variables=dict(v.split("=", 1) for v in a.var or [] if "=" in v),
                             blind=a.blind, concurrency=a.concurrency)
            if out is None:
                return
            a.results = [str(out)]
    if a.wrap:
        files = find_skill_files(target)
        if len(files) != 1:
            print("[worth] --wrap takes one skill folder")
            return
        out, notes = wrap(files[0].parent, Path(a.wrap).expanduser())
        for n in notes:
            print(f"  {n}")
        print(f"wrapped in {out}; run the value cases with and without, then read the result:\n"
              f"  claude plugin eval \"{out}\" --trust-plugin --no-publish --case \"action-*\"   (again for \"outcome-*\")\n"
              f"  python evergreen.py worth \"{files[0].parent}\" --results \"{out / 'evals' / 'results'}\" --record")
        return
    results = assess(target, against=a.against, results=a.results, peers=not a.no_peers, case_glob=a.case)
    if not results:
        print(f"[worth] no SKILL.md at {target} (nor under skills/*/ or */)")
        return
    if probe_rep and len(results) == 1:
        r0 = results[0]
        r0["probe"] = {k: probe_rep[k] for k in ("task", "anchors", "covered", "coverage", "out", "date")}
        r0["modes"] = failure_modes(r0, r0.get("evidence"), r0.get("ab"),
                                    recorded(Path(r0["unit"]) if r0.get("unit") else None, r0["skill"]))
    if a.json:
        print(json.dumps(results, indent=2))
    elif len(results) > 1 and not a.verbose:
        print(f"{'verdict':9} {'skill':34} {'listing':>8} {'body':>7} {'specific':>8}  A/B")
        for r in results:
            ab = r.get("ab")
            abs_ = f"{ab['delta'] * 100:+.0f} pts, cost x{ab['cost_ratio']}" if ab else "-"
            sp = f"{int(100 * r['specific_share'])}%" if r["specific_share"] is not None else "-"
            print(f"{r['verdict']:9} {r['skill'][:34]:34} {r['listing_tokens']:>8,} {r['body_tokens']:>7,} {sp:>8}  {abs_}")
            for w in r["warnings"]:
                print(f"{'':10}- {w}")
        counts = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        print("-- " + ", ".join(f"{v} {n}" for v, n in sorted(counts.items())) + " (tokens are estimates)")
        pab = plugin_ab(target, a.results, a.case)
        if pab:
            print(f"-- whole plugin A/B, {len(pab['cases'])} value case(s): pass {int(pab['pass_with'] * 100)}% with, "
                  f"{int(pab['pass_without'] * 100)}% without, cost x{pab['cost_ratio']}: {pab['verdict']}, {pab['why']}")
    else:
        print("\n\n".join(render(r) for r in results))
    if a.record:
        for u in record(results):
            print(f"[worth] recorded in {u}/evergreen.json")
    if a.strict and any(r["verdict"] in ("CUT", "SUSPECT") for r in results):
        sys.exit(1)


def cmd_worth_hook(a):
    """PostToolUse on Write|Edit|MultiEdit: when the edited file is a SKILL.md and the static check turns up a warning
    this session has not seen yet, tell the model in one short block (additionalContext). Silent otherwise."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    fp = ((payload.get("tool_input") or {}).get("file_path") or "")
    if not fp.replace("\\", "/").endswith("/SKILL.md") and fp != "SKILL.md":
        return
    p = Path(fp)
    if not p.exists():
        return
    tracked = eg.git(["ls-files", "--error-unmatch", p.name], p.parent) is not None
    r = static_report(p, against="HEAD" if tracked else None, uses=False)
    if r["static"] == "LEAN":
        return
    msg = (f"[evergreen-worth] {r['skill']}: {r['static']} on a static read (listing ~{r['listing_tokens']} tokens every "
           f"session, body ~{r['body_tokens']:,} per use). " + " ".join(f"- {w}." for w in r["warnings"][:4])
           + " Tell the user in one or two lines; before adding more, cut what the model already knows, and prove the "
             "skill with the evergreen-worth A/B.")
    state = eg.evergreen_home() / "worth-hook.json"
    key = str(p.resolve()).lower()
    digest = hashlib.sha1((r["static"] + "|".join(w.split(":")[0] for w in r["warnings"])).encode()).hexdigest()[:12]
    try:
        seen = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    except Exception:
        seen = {}
    sid = str(payload.get("session_id") or "")
    if seen.get(key) == f"{sid}:{digest}":
        return  # the same warning already went to this session
    seen[key] = f"{sid}:{digest}"
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        eg.write_lf(state, json.dumps(seen, indent=1))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))


def add_parsers(sp, common):
    s = sp.add_parser("worth", parents=[common], help="is a skill worth its tokens? static signals plus the with-versus-without A/B")
    s.add_argument("target", nargs="+", help="a SKILL.md, a skill folder, a plugin root, or a folder of skill folders; "
                                             "several targets print the triage table")
    s.add_argument("--triage", action="store_true", help="one row per skill, costliest per use first, with failure modes and evidence gaps")
    s.add_argument("--days", type=int, default=USAGE_DAYS, help=f"usage window in days (default {USAGE_DAYS})")
    s.add_argument("--probe", action="store_true", help="knowledge probe: ask a fresh headless session without the skill how it would do the job")
    s.add_argument("--prompt", help="the task for --probe (default: the skill's first value case, else its first trigger prompt)")
    s.add_argument("--ab", action="store_true", help="run the value cases headless with and without the skill (claude -p; works on native Windows)")
    s.add_argument("--runs", type=int, default=3, help="runs per arm for --ab (default 3; use 5 inside the noise margin)")
    s.add_argument("--out", metavar="DIR", help="where --ab and --probe write transcripts and aggregate-result.json")
    s.add_argument("--model", help="model for --ab and --probe runs")
    s.add_argument("--var", action="append", metavar="NAME=VALUE", help="value for an evidence placeholder such as <vault> (repeatable)")
    s.add_argument("--blind", action="store_true", help="--bare runs: no user CLAUDE.md in either arm (needs ANTHROPIC_API_KEY)")
    s.add_argument("--concurrency", type=int, default=3, help="parallel runs for --ab (default 3)")
    s.add_argument("--set", choices=MANUAL_VERDICTS, help="record a person's ruling for one skill (with --why, and --replaced-by for SUPERSEDED)")
    s.add_argument("--why", help="the reason for --set")
    s.add_argument("--replaced-by", help="what does the job now, with a dated source, for --set SUPERSEDED")
    s.add_argument("--against", metavar="REV", help="judge the edit since this git revision (e.g. HEAD, HEAD~1, master)")
    s.add_argument("--results", nargs="*", metavar="PATH", help="aggregate-result.json files or folders (default: <unit>/evals/results)")
    s.add_argument("--case", metavar="GLOB", help="only these value cases, e.g. 'action-*'")
    s.add_argument("--wrap", metavar="DIR", help="build a throwaway plugin around one standalone skill for `claude plugin eval`")
    s.add_argument("--no-peers", action="store_true", help="skip the description overlap check against other installed skills")
    s.add_argument("--record", action="store_true", help="write the verdict into the unit's evergreen.json (worth block)")
    s.add_argument("--json", action="store_true"); s.add_argument("--verbose", "-v", action="store_true", help="full report per skill in a multi-skill run")
    s.set_defaults(fn=cmd_worth)
    s = sp.add_parser("worth-hook", parents=[common], help="PostToolUse hook body: warn once when an edited SKILL.md reads as mostly cost")
    s.set_defaults(fn=cmd_worth_hook)
