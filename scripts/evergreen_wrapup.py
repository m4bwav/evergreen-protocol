#!/usr/bin/env python3
"""evergreen_wrapup.py - harvest a finished work session for the wrap-up. The `wrapup` command of evergreen.py.

The agent's memory of a long session is the weakest record of it: early turns are summarised away by compaction, and
what the model remembers is what it said, not what failed. The transcript remembers everything. This reads one
session's transcript (Claude Code's JSONL, an internal format: unknown lines are skipped) and prints the signals a
wrap-up turns into durable improvements, each with an ID the agent cites while it gates and routes them
(skills/evergreen-wrapup):

  C  corrections   user turns after the first that read as a correction, a restated rule, or a preference
  D  denials       tool calls the user or a permission rule refused (a preference, or a route to avoid)
  E  errors        failed tool calls grouped by tool and first line, with how often and whether a retry followed
  R  repeats       shell command shapes run three or more times (script or alias candidates), exact repeats twice
  T  token sinks   the largest tool results (a filter, a narrower read or a script would have cost less)
  S  slow calls    tool calls that took a minute or more (a background run, a cache, a faster route)
  plus the skills used, files changed per repository (with the stores found there: ai-docs/, AGENTS.md, evergreen
  units), web research done, subagents, compactions, and the session's token totals.

The output is candidates, not conclusions: most lines are noise, and the skill's gate drops them. Nothing here writes
anywhere. Pure standard library.

  wrapup [--session ID|PATH] [--json] [--top N]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SHELL_TOOLS = ("Bash", "PowerShell")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
CORRECTION_RE = re.compile(
    r"(^\s*(no|nope|wait|stop)\b|\bactually\b|\bi (told|asked|said)\b|\bi meant\b|\bnot what i\b|\bthat'?s (wrong|not)\b|"
    r"\bwrong\b|\binstead\b|\bdon'?t\b|\bdo not\b|\bnever\b|\balways\b|\bremember\b|\bagain\b|\bwhy did you\b|"
    r"\byou (forgot|missed|should|need to|didn'?t)\b|\bplease (don'?t|stop)\b|\bfrom now on\b|\bnext time\b)", re.I)
DENIAL_RE = re.compile(r"(Permission for this action was denied|doesn'?t want to proceed|user rejected|was blocked by|denied by)", re.I)
META_PREFIXES = ("<command-", "<local-command", "Caveat:", "<system-reminder>", "[Request interrupted")
ERROR_WORD_RE = re.compile(r"(Error|Exception|error:|fatal:|denied|not found|not recognized|No such file|failed)", re.I)
CMD_RE = re.compile(r"<command-name>/?([A-Za-z0-9:_-]+)</command-name>")
SLOW_SECONDS = 60
# shell syntax and the read-only plumbing every session runs; a repeat of these is not a script candidate
SHELL_WORDS = {"do", "done", "then", "else", "elif", "fi", "if", "while", "until", "for", "in", "{", "}", "(", ")", "!", "&"}
PLUMBING = {"cd", "echo", "printf", "set", "export", "Set-Location", "true", "false", "sleep", "cat", "head", "tail",
            "grep", "rg", "sed", "awk", "wc", "sort", "uniq", "cut", "ls", "dir", "find", "date", "pwd", "test", "tee",
            "xargs", "tr", "Write-Output", "Get-Content", "Select-Object", "Select-String"}
INTERPRETERS = {"python", "python3", "py", "node", "bash", "sh", "pwsh", "powershell", "npx", "uv", "uvx", "dotnet"}


def claude_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def find_session(arg: str | None) -> Path | None:
    """A path, a session id, or (none given) the most recently written top-level transcript, which during a session
    is the session itself."""
    if arg and Path(arg).is_file():
        return Path(arg)
    root = claude_dir() / "projects"
    if not root.exists():
        return None
    if arg:
        hits = list(root.glob(f"*/{arg}.jsonl"))
        return hits[0] if hits else None
    files = [p for p in root.glob("*/*.jsonl")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) and c.get("type") == "text" else
                         (c if isinstance(c, str) else "") for c in content)
    return ""


def _result_text(c: dict) -> str:
    v = c.get("content")
    return v if isinstance(v, str) else _text(v)


def _ts(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _norm_line(s: str, n: int = 120) -> str:
    """The line that names the failure (a traceback's last error line, not its header), with paths, hashes and numbers
    masked so the same failure groups across calls."""
    lines = [x.strip() for x in s.splitlines() if x.strip()]
    named = [x for x in lines if ERROR_WORD_RE.search(x) and not x.startswith("Traceback")]
    line = named[-1] if named else (lines[0] if lines else "")
    line = re.sub(r"[A-Za-z]:[\\/][^\s'\"]*|/[^\s'\"]*/[^\s'\"]*", "<path>", line)
    line = re.sub(r"\b[0-9a-f]{7,40}\b", "<hex>", line)
    line = re.sub(r"\d+", "N", line)
    return line[:n]


def command_shapes(cmd: str) -> list[str]:
    """The shape of each segment of a shell command: the program and up to two words after it, paths cut to their
    base name, flags, quoted text and numbers dropped. `cd X &&` and variable assignments are skipped."""
    out = []
    cmd = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?^\s*\1\s*$", "", cmd, flags=re.S | re.M)  # heredoc bodies
    cmd = re.sub(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'", "\"\"", cmd, flags=re.S)  # quoted text, inline code included
    for seg in re.split(r"&&|\|\||;|\||\n", cmd):
        toks = [t for t in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", seg.strip()) if t]
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in ("sudo", "time", "&", "env")):
            toks = toks[1:]
        if toks and toks[0] in ("for", "foreach"):
            continue
        while toks and toks[0] in SHELL_WORDS:
            toks = toks[1:]
        if not toks or toks[0] in PLUMBING or toks[0].startswith(("#", "[", "$(", "`")):
            continue
        shape = []
        for t in toks:
            if len(shape) == 3 or t.startswith(("-", "\"", "'", "$", "<", ">", "2>")) or re.fullmatch(r"[\d.]+", t):
                break
            shape.append(re.split(r"[\\/]", t.rstrip("\\/"))[-1] or t)
        if shape and not (len(shape) == 1 and shape[0] in INTERPRETERS):
            out.append(" ".join(shape))
    return out


def git_root(p: Path) -> Path | None:
    for d in [p] + list(p.parents):
        if (d / ".git").exists():
            return d
    return None


def unit_of(p: Path, stop: Path | None) -> Path | None:
    for d in list(p.parents):
        if (d / "evergreen.json").exists():
            return d
        if stop is not None and d == stop:
            break
    return None


def harvest(path: Path, top: int = 8) -> dict:
    uses: dict[str, dict] = {}            # tool_use id -> {name, input, ts}
    usage_seen, tok = set(), Counter()
    user_turns, corrections, interrupts, denials = 0, [], 0, []
    errors: dict[tuple, dict] = {}
    results = []                          # (chars, tool, summary)
    slow = []
    order = []                            # tool names in call order, with error flags, for retry detection
    skills, slash, web, agents = Counter(), Counter(), [], []
    files = set()
    compactions, first_ts, last_ts, cwd = 0, None, None, None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("isSidechain"):
                continue
            ts = _ts(o.get("timestamp")) if o.get("timestamp") else None
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            cwd = cwd or o.get("cwd")
            if o.get("isCompactSummary"):
                compactions += 1
                continue
            msg = o.get("message") if isinstance(o.get("message"), dict) else {}
            content = msg.get("content")
            if o.get("type") == "assistant":
                u = msg.get("usage") or {}
                key = o.get("requestId") or msg.get("id")
                if u and key not in usage_seen:
                    usage_seen.add(key)
                    tok["context"] += sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                    tok["output"] += int(u.get("output_tokens") or 0)
                    tok["turns"] += 1
                for c in content if isinstance(content, list) else []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    name, inp = str(c.get("name")), c.get("input") or {}
                    uses[str(c.get("id"))] = {"name": name, "input": inp, "ts": ts}
                    if name == "Skill" and inp.get("skill"):
                        skills[str(inp["skill"])] += 1
                    elif name in EDIT_TOOLS and (inp.get("file_path") or inp.get("notebook_path")):
                        files.add(str(inp.get("file_path") or inp.get("notebook_path")))
                    elif name == "WebSearch":
                        web.append("search: " + str(inp.get("query", ""))[:100])
                    elif name == "WebFetch":
                        web.append("fetch: " + str(inp.get("url", ""))[:100])
                    elif name in ("Agent", "Task"):
                        agents.append(str(inp.get("description") or inp.get("subagent_type") or "")[:80])
            elif o.get("type") == "user":
                if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                    for c in content:
                        if not isinstance(c, dict) or c.get("type") != "tool_result":
                            continue
                        u = uses.get(str(c.get("tool_use_id")), {"name": "?", "input": {}, "ts": None})
                        text = _result_text(c)
                        summary = summarize_input(u["name"], u["input"])
                        results.append((len(text), u["name"], summary))
                        if u["ts"] and ts and (ts - u["ts"]).total_seconds() >= SLOW_SECONDS:
                            slow.append((int((ts - u["ts"]).total_seconds()), u["name"], summary))
                        is_err = bool(c.get("is_error"))
                        order.append((u["name"], is_err))
                        if is_err and DENIAL_RE.search(text):
                            denials.append(f"{u['name']}: {summary} -> {_norm_line(text, 160)}")
                        elif is_err:
                            k = (u["name"], _norm_line(text))
                            e = errors.setdefault(k, {"tool": u["name"], "line": k[1], "count": 0, "example": summary, "retried": False})
                            e["count"] += 1
                    continue
                if o.get("isMeta"):
                    continue
                text = _text(content).strip()
                for m in CMD_RE.finditer(text):
                    slash[m.group(1)] += 1
                if text.startswith("[Request interrupted"):
                    interrupts += 1
                    continue
                if not text or text.startswith(META_PREFIXES):
                    continue
                user_turns += 1
                if user_turns > 1 and CORRECTION_RE.search(text):
                    corrections.append(re.sub(r"\s+", " ", text)[:220])
    # a retry: the same tool called again right after its error
    for i, (name, err) in enumerate(order[:-1]):
        if err and order[i + 1][0] == name:
            for e in errors.values():
                if e["tool"] == name:
                    e["retried"] = True
    shapes, exact = Counter(), Counter()
    for u in uses.values():
        if u["name"] in SHELL_TOOLS and u["input"].get("command"):
            cmd = str(u["input"]["command"])
            exact[re.sub(r"\s+", " ", cmd.strip())[:200]] += 1
            for s in set(command_shapes(cmd)):
                shapes[s] += 1
    repos: dict[str, dict] = {}
    for f in sorted(files):
        p = Path(f)
        root = git_root(p.parent) if p.parent.exists() else None
        key = str(root or p.parent)
        r = repos.setdefault(key, {"files": 0, "ai_docs": False, "agents_md": False, "units": set(), "kinds": Counter()})
        r["files"] += 1
        if root:
            r["ai_docs"] = (root / "ai-docs").is_dir()
            r["agents_md"] = (root / "AGENTS.md").is_file()
        unit = unit_of(p, root)
        if unit:
            r["units"].add(str(unit))
        n = p.name.lower()
        r["kinds"]["skill" if n == "skill.md" else "script" if p.suffix in (".py", ".ps1", ".sh", ".js", ".mjs", ".ts")
                   else "doc" if p.suffix in (".md", ".txt") else "other"] += 1
    sub_dir = path.with_suffix("") / "subagents"
    return {
        "session": path.stem, "file": str(path), "cwd": cwd,
        "start": first_ts.isoformat(timespec="minutes") if first_ts else None,
        "minutes": int((last_ts - first_ts).total_seconds() // 60) if first_ts and last_ts else None,
        "tokens": dict(tok), "user_turns": user_turns, "interrupts": interrupts, "compactions": compactions,
        "corrections": corrections[:top * 2],
        "denials": denials[:top],
        "errors": sorted(errors.values(), key=lambda e: -e["count"])[:top],
        "repeats": [{"shape": s, "count": n} for s, n in shapes.most_common() if n >= 3][:top],
        "exact_repeats": [{"command": c, "count": n} for c, n in exact.most_common() if n >= 2][:top],
        "token_sinks": [{"tokens": ch // 4, "tool": t, "call": s} for ch, t, s in sorted(results, reverse=True)[:top] if ch >= 8000],
        "slow": group_slow(slow)[:top],
        "skills": dict(skills), "slash_commands": dict(slash),
        "repos": {k: {**v, "units": sorted(v["units"]), "kinds": dict(v["kinds"])} for k, v in repos.items()},
        "web": web[:top * 2], "web_count": len(web), "agents": agents[:top],
        "subagent_transcripts": len(list(sub_dir.glob("*.jsonl"))) if sub_dir.is_dir() else 0,
    }


def group_slow(slow: list) -> list[dict]:
    """Slow calls grouped by what was called, costliest in total first: nine four-minute builds are one row worth
    36 minutes, which is the saving estimate the wrap-up needs."""
    g: dict[tuple, dict] = {}
    for sec_, tool, call in slow:
        r = g.setdefault((tool, call), {"tool": tool, "call": call, "count": 0, "total": 0, "seconds": 0})
        r["count"] += 1
        r["total"] += sec_
        r["seconds"] = max(r["seconds"], sec_)
    return sorted(g.values(), key=lambda r: -r["total"])


def summarize_input(name: str, inp: dict) -> str:
    for k in ("command", "file_path", "pattern", "url", "query", "skill", "description", "prompt"):
        if inp.get(k):
            return re.sub(r"\s+", " ", str(inp[k]))[:110]
    return name


def render(h: dict) -> str:
    t = h["tokens"]
    out = [f"# Wrap-up harvest: session {h['session']}",
           f"started {h['start']}, {h['minutes']} min, {h['user_turns']} user turns, {t.get('turns', 0)} model turns, "
           f"{t.get('context', 0):,} context tokens read, {t.get('output', 0):,} output tokens, "
           f"{h['interrupts']} interrupts, {h['compactions']} compactions",
           f"transcript: {h['file']}"]
    if h["compactions"]:
        out.append("note: the session was compacted; what came before the summary is only in this harvest and the summary")

    def sec(title, rows):
        out.append(f"\n## {title}")
        out.extend(rows if rows else ["(none)"])
    sec("Corrections and stated preferences (C)", [f"- C{i}: {c}" for i, c in enumerate(h["corrections"], 1)])
    sec("Refused tool calls (D)", [f"- D{i}: {d}" for i, d in enumerate(h["denials"], 1)])
    sec("Errors (E)", [f"- E{i}: {e['tool']} x{e['count']}{' (retried)' if e['retried'] else ''}: {e['line']} | e.g. {e['example']}"
                       for i, e in enumerate(h["errors"], 1)])
    sec("Repeated command shapes (R)", [f"- R{i}: `{r['shape']}` x{r['count']}" for i, r in enumerate(h["repeats"], 1)] +
        [f"- R{len(h['repeats']) + i}: exact repeat x{r['count']}: `{r['command'][:140]}`" for i, r in enumerate(h["exact_repeats"], 1)])
    sec("Token sinks, results over ~2k tokens (T)", [f"- T{i}: ~{s['tokens']:,} tokens from {s['tool']}: {s['call']}" for i, s in enumerate(h["token_sinks"], 1)])
    sec(f"Slow calls, {SLOW_SECONDS} s or more, by total time (S)",
        [f"- S{i}: {s['total']} s total ({s['count']}x, longest {s['seconds']} s) {s['tool']}: {s['call']}" for i, s in enumerate(h["slow"], 1)])
    sec("Skills and commands used", [f"- {k} x{v}" for k, v in sorted({**h["skills"], **{'/' + k: v for k, v in h["slash_commands"].items()}}.items())])
    rows = []
    for repo, r in h["repos"].items():
        stores = [s for s, ok in (("ai-docs/", r["ai_docs"]), ("AGENTS.md", r["agents_md"])) if ok]
        rows.append(f"- {repo}: {r['files']} files ({', '.join(f'{k} {v}' for k, v in r['kinds'].items())}); stores: "
                    f"{', '.join(stores) or 'none'}" + (f"; evergreen units: {', '.join(r['units'])}" if r["units"] else ""))
    sec("Files changed, by repository", rows)
    sec(f"Web research ({h['web_count']} calls)", [f"- {w}" for w in h["web"]])
    if h["agents"] or h["subagent_transcripts"]:
        sec("Subagents", [f"- {a}" for a in h["agents"]] + [f"- {h['subagent_transcripts']} subagent transcripts beside the session (not harvested)"])
    out.append("\nNext: gate each candidate (skills/evergreen-wrapup Step 2); most lines are noise.")
    return "\n".join(out)


def cmd_wrapup(a):
    path = find_session(a.session)
    if not path:
        print("[evergreen] wrapup: no session transcript found (Claude Code keeps them under ~/.claude/projects); "
              "harvest from the conversation instead", file=sys.stderr)
        raise SystemExit(1)
    h = harvest(path, a.top)
    print(json.dumps(h, indent=1, default=str) if a.json else render(h))


def add_parsers(sp, common):
    s = sp.add_parser("wrapup", parents=[common], help="harvest a session transcript for the wrap-up: corrections, refusals, errors, repeats, token sinks, slow calls, files and stores touched")
    s.add_argument("--session", help="a session id or a transcript path (default: the most recently written transcript, the current session)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--top", type=int, default=8, help="rows per section (default 8)")
    s.set_defaults(fn=cmd_wrapup)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")
    add_parsers(sub, argparse.ArgumentParser(add_help=False))
    args = p.parse_args(["wrapup"] + sys.argv[1:])
    args.fn(args)
