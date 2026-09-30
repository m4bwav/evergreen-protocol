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

Verdicts: KEEP (a measured gain, or the same result for less), TRIM (a measured gain at a high price, or a lean
test with a suspect body), CUT (no gain beyond noise at a higher cost, a loss, or a model that already passes
without the skill), UNPROVEN (no A/B yet and nothing suspect), SUSPECT (no A/B yet and the static signals say
mostly general advice, bloat or duplication; run the A/B before investing more).

Pure standard library; fails soft like the rest of evergreen.py.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import date
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
        return {w: c * math.log((1 + n) / (1 + df[w])) + 0.0 for w, c in tf.items()}

    tv = vec(toks["\0target"])
    tn = math.sqrt(sum(x * x for x in tv.values())) or 1.0
    out = []
    for k in peers:
        pv = vec(toks[k])
        pn = math.sqrt(sum(x * x for x in pv.values())) or 1.0
        out.append((sum(tv.get(w, 0.0) * x for w, x in pv.items()) / (tn * pn), k))
    return sorted(out, reverse=True)


def peer_skill_files(target: Path, extra: list[Path] | None = None) -> list[Path]:
    """SKILL.md files the model would see beside the target: its siblings, the user's skill folders, installed plugins."""
    home = Path.home()
    pats = [(target.parent.parent, "*/SKILL.md"), (home / ".claude" / "skills", "*/SKILL.md"),
            (Path.cwd() / ".claude" / "skills", "*/SKILL.md"), (Path.cwd() / ".agents" / "skills", "*/SKILL.md"),
            (home / ".claude" / "plugins" / "cache", "*/*/*/skills/*/SKILL.md")]
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
    r["uses_30d"] = None
    if uses and eg.uses_path().exists():
        r["uses_30d"] = len(eg.read_uses(name, days=30))
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


def assess(target: Path, against: str | None = None, results: list[str] | None = None, peers: bool = True,
           case_glob: str | None = None) -> list[dict]:
    out = []
    files = find_skill_files(target)
    for f in files:
        st = static_report(f, against=against, peers=peers)
        unit = unit_for(f, target)
        ab = None
        if unit is not None or results:
            # a skill that is its own unit owns every case; a skill inside a plugin owns only the cases that name it
            own = unit is not None and unit.resolve() == f.parent.resolve()
            ab = ab_report(unit or f.parent, results, skill=None if own else st["skill"], case_glob=case_glob)
        v, why = verdict(st, ab)
        st.update({"ab": ab, "verdict": v, "why": why, "unit": str(unit) if unit else None})
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
    if r.get("uses_30d") is not None:
        L.append(f"  uses     {r['uses_30d']} in 30 days (use log)")
    ab = r.get("ab")
    if ab:
        L.append(f"  A/B      {len(ab['cases'])} value case(s), {ab['runs_with']}/{ab['runs_without']} runs: pass "
                 f"{int(ab['pass_with'] * 100)}% with, {int(ab['pass_without'] * 100)}% without · cost x{ab['cost_ratio']} · "
                 f"turns x{ab['turns_ratio']} · time x{ab['time_ratio']}")
    else:
        L.append("  A/B      none yet (claude plugin eval, with-without, on the action and outcome cases)")
    L.append(f"  verdict  {r['verdict']}  {r['why']}")
    for w in r["warnings"]:
        L.append(f"    - {w}")
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
            skills[r["skill"]] = {"verdict": r["verdict"], "why": r["why"], "body_tokens": r["body_tokens"],
                                  "listing_tokens": r["listing_tokens"], "specific_share": r["specific_share"],
                                  "delta": ab.get("delta"), "cost_ratio": ab.get("cost_ratio"),
                                  "checked": date.today().isoformat()}
        st["worth"] = {"checked": date.today().isoformat(), "skills": skills}
        eg.save_state(d, st)
        written.append(str(d))
    return written


def worth_flags(st: dict) -> list[str]:
    """Audit flags from a recorded worth block: only verdicts that ask for a decision."""
    skills = ((st.get("worth") or {}).get("skills") or {}) if isinstance(st.get("worth"), dict) else {}
    out = []
    for name, v in sorted(skills.items()):
        if isinstance(v, dict) and v.get("verdict") in ("CUT", "TRIM", "SUSPECT"):
            out.append(f"worth:{v['verdict']}" + (f":{name}" if len(skills) > 1 else ""))
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
    target = Path(a.target).expanduser()
    if not target.exists():
        print(f"[worth] no such path: {target}")
        return
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
    s.add_argument("target", help="a SKILL.md, a skill folder, a plugin root, or a folder of skill folders")
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
