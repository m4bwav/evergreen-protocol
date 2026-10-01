#!/usr/bin/env python3
"""evergreen_ab.py - the knowledge probe and the headless with-versus-without A/B behind `evergreen.py worth`.

  probe  ask a fresh headless session, with no skills loaded, how it would do the skill's job, and count how many of
         the skill's key anchors (the commands, files, flags and names in its inline code) the answer already names.
         Named anchors are trim candidates; missed ones are what the skill is for. A heuristic for a person to read.
  A/B    run every value case (action, outcome) of the skill's evals.json through `claude -p` in a fresh folder, N
         times with the skill and N times without, grade each run on the case's evidence (a tool call in the trace, a
         file, a command, a regex on the answer; never the reply's claim), and write aggregate-result.json in the shape
         `claude plugin eval` writes, so `worth --results` reads either. It runs on native Windows, where `claude plugin
         eval` refuses cases that grant Bash (LEARNINGS L-019).

Both arms run with `--setting-sources project` and `--no-session-persistence`: no user skills, plugins or auto
memory, and no transcript left behind to count as use. The with arm adds the skill (`--plugin-dir` for a skill inside
a plugin, else a copy under the run folder's .claude/skills). The user's own CLAUDE.md still loads in both arms;
`--blind` uses `--bare` instead, which needs ANTHROPIC_API_KEY. Pure standard library.
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import evergreen_worth as ew

_SHELL = ["python *", "python3 *", "py *", "node *", "npm view*", "npm pack*", "npm test*", "ls*", "cat *", "mkdir *",
          "git status*", "git log*", "git diff*", "git show*", "gh api *", "gh repo view*", "curl *", "bash *", "sh *"]
# The same commands for both shells: on Windows the model often reaches for PowerShell, and a grader that names
# `Bash|PowerShell` must not fail a run only because the shell it picked was not granted. Nothing grants a push.
TOOLS = {
    "action": ["Skill", "Read", "Glob", "Grep", "Write", "Edit"] + [f"Bash({c})" for c in _SHELL]
              + [f"PowerShell({c})" for c in _SHELL + ["Get-Content *", "Get-ChildItem*"]],
    "outcome": ["Skill", "Read", "Glob", "Grep", "Write"],
}
MAX_TURNS = {"action": 40, "outcome": 12}
UNRESOLVED = re.compile(r"<[A-Za-z][\w -]*>")
SHELL_TOOLS = "Bash|PowerShell|run_in_terminal"


def tool_regex(tool: str) -> str:
    """A case's `tool` as a regex over tool names. Suites write it as a regex (`Bash|PowerShell`) or as prose ('a shell
    tool (Bash, PowerShell, run_in_terminal)'); prose keeps only the names in it, and 'shell' means every shell."""
    tool = (tool or "").strip()
    if not tool:
        return ".*"
    if re.fullmatch(r"[\w|.*()?:-]+", tool):
        return tool
    names = [n for n in re.findall(r"[A-Za-z_]+", tool) if re.search(r"[A-Z_]", n) and n not in ("A", "The")]
    if re.search(r"\bshell\b", tool, re.I):
        names += SHELL_TOOLS.split("|")
    return "|".join(dict.fromkeys(names)) or ".*"


CHECK_EXIT = re.compile(r"^\s*`?(.+?)`?\s+exits\s+0\s*$", re.I)


def run_check(check: str, run: Path, home: Path | None) -> bool | None:
    """A file evidence `check` written as '<command> exits 0': run it in the run folder, with a script path that only
    the suite's home has (scripts/tells.py) pointed there. Any other wording needs a judge: None."""
    m = CHECK_EXIT.match(check or "")
    if not m:
        return None
    try:
        return subprocess.run(localize(m.group(1).split(), run, home), cwd=str(run), capture_output=True,
                              timeout=300).returncode == 0
    except Exception:
        return False


def localize(parts: list[str], run: Path, home: Path | None) -> list[str]:
    """Point a script path the run folder lacks at the suite's home (the skill or plugin root), and `python` at an
    interpreter that exists here."""
    parts = list(parts)
    for i, p in enumerate(parts):
        if re.search(r"\.(py|mjs|cjs|js|sh|ps1)$", p) and not (run / p).exists() and home is not None:
            for base in (home, home.parent, home.parent.parent):
                if (base / p).exists():
                    parts[i] = str(base / p)
                    break
    if parts and parts[0] in ("python", "python3"):
        parts[0] = shutil.which("python") or shutil.which("python3") or parts[0]
    return parts


# ---------- running claude ----------

def claude_binary() -> str:
    """The CLI, spawned without a shell. On Windows `claude` on PATH is a .cmd shim around claude.exe."""
    if os.environ.get("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    if os.name == "nt":
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if d and ((Path(d) / "claude.cmd").exists() or (Path(d) / "claude").exists()):
                exe = Path(d) / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
                if exe.exists():
                    return str(exe)
    return shutil.which("claude") or "claude"


def run_claude(prompt: str, cwd: Path, extra: list[str], timeout: int = 1800) -> tuple[str, float, int]:
    """(stream-json stdout, seconds, exit code)."""
    args = [claude_binary(), "-p", prompt, "--output-format", "stream-json", "--verbose", "--no-session-persistence", *extra]
    t0 = time.time()
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace"), time.time() - t0, r.returncode
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b"").decode("utf-8", "replace"), time.time() - t0, -1
    except OSError as e:
        return json.dumps({"type": "result", "is_error": True, "result": f"could not start claude: {e}"}), 0.0, -2


def parse_stream(out: str) -> dict:
    """Tool calls in order, the final answer, and the result event's cost, turns and error flag."""
    uses, result = [], {}
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    uses.append({"name": c.get("name"), "input": c.get("input") or {}})
        elif ev.get("type") == "result":
            result = ev
    return {"uses": uses, "answer": str(result.get("result") or ""), "cost": float(result.get("total_cost_usd") or 0),
            "turns": int(result.get("num_turns") or 0), "error": bool(result.get("is_error")) or not result}


def isolation_args(blind: bool) -> list[str]:
    return ["--bare"] if blind else ["--setting-sources", "project"]


# ---------- the knowledge probe ----------

PROBE_ASK = ("{task}\n\nDo not do the task and do not use any tools. Write the exact steps you would take, naming every "
             "command, file, tool, flag, setting and value you would use, and the checks you would run before saying it "
             "is done. Be concrete.")
SKIP_ANCHOR = re.compile(r"^(?:\$\{|<|references/|scripts?/|\.\./|EG\b)|plugin root|CLAUDE_SKILL_DIR", re.I)
STOP = {"the", "and", "for", "with", "from", "this", "that", "use", "run", "file", "files", "skill", "true", "false",
        "none", "null", "name", "path", "dir", "md", "json", "txt", "yes", "not", "any", "all", "new", "old",
        "python", "python3", "node", "npm", "npx", "bash", "git", "line", "title"}


UPKEEP_HEADING = re.compile(r"^#{1,4} .*(?:maintenance|freshness|capture learnings|learnings|while working)", re.I | re.M)
SPECIFIC_SHAPE = re.compile(r"[._/@:\d-]|[a-z][A-Z]|^[A-Z][A-Z0-9_]{2,}$")


def task_text(body: str) -> str:
    """The body without its upkeep sections (Maintenance, Step 0 freshness, learnings capture): those name the
    protocol's own files, which say nothing about whether the model can do the skill's job."""
    out, skip = [], False
    for line in body.splitlines():
        if line.startswith("#"):
            skip = bool(UPKEEP_HEADING.match(line))
        if not skip:
            out.append(line)
    return "\n".join(out)


def key_anchors(body: str, skill: str) -> list[str]:
    """Distinctive terms from the body's inline code: the command that starts a span, and any token shaped like a
    file, flag, path, version or identifier. Plain words are dropped, and so are the skill's own helper paths (a
    fresh session cannot know them, and that is the skill's job by definition)."""
    spans = re.findall(r"`([^`\n]+)`", ew.FENCE_RE.sub("", task_text(body)))
    terms, seen = [], set()
    for s in spans:
        s = re.sub(r"<[^>]*>", " ", s).strip()
        if not s or SKIP_ANCHOR.search(s):
            continue
        toks = re.findall(r"--?[a-z][\w-]+|[A-Za-z_][\w.@/:-]*\w", s)
        for i, t in enumerate(toks):
            k = t.lower().strip("./")
            if len(k) < 3 or k in STOP or k.isdigit() or k == skill.lower() or k in seen:
                continue
            if not (SPECIFIC_SHAPE.search(t) or (i == 0 and len(toks) > 1)):
                continue
            seen.add(k)
            terms.append(t)
    return terms[:60]


def first_prompt(unit: Path | None, skill_dir: Path, skill: str) -> str | None:
    for home in [h for h in (unit, skill_dir) if h is not None]:
        kinds = ew.case_kinds(home)
        own = [c for c in kinds.values() if home.resolve() == skill_dir.resolve() or c.get("_skill", "").split(":")[-1] == skill]
        for want in ("action", "outcome", "trigger"):
            for c in own:
                if c.get("kind") == want and not c.get("decoy") and c.get("prompt"):
                    return str(c["prompt"])
    return None


def probe(skill_dir: Path, unit: Path | None, prompt: str | None = None, out: str | None = None,
          model: str | None = None, blind: bool = False) -> dict:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    fm, body = ew.parse_frontmatter(text)
    name = fm.get("name") or skill_dir.name
    task = prompt or first_prompt(unit, skill_dir, name) or (fm.get("description") or "").split(". Use")[0]
    anchors = key_anchors(body, name)
    work = Path(tempfile.mkdtemp(prefix=f"probe-{name}-"))
    extra = isolation_args(blind) + ["--disable-slash-commands", "--max-turns", "2", "--tools", ""]
    if model:
        extra += ["--model", model]
    raw, secs, _ = run_claude(PROBE_ASK.format(task=task), work, extra, timeout=600)
    res = parse_stream(raw)
    low = res["answer"].lower()
    covered = [a for a in anchors if a.lower() in low]
    missed = [a for a in anchors if a.lower() not in low]
    dest = Path(out).expanduser() if out else work
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"probe-{name}.md").write_text(f"# Probe: {name}\n\nTask: {task}\n\n## Answer without the skill\n\n{res['answer']}\n",
                                           encoding="utf-8")
    rep = {"skill": name, "task": task, "anchors": len(anchors), "covered": len(covered),
           "coverage": round(len(covered) / len(anchors), 2) if anchors else None, "named": covered, "missed": missed,
           "seconds": round(secs), "cost_usd": res["cost"], "error": res["error"], "out": str(dest / f"probe-{name}.md"),
           "date": date.today().isoformat()}
    (dest / f"probe-{name}.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return rep


def render_probe(p: dict) -> str:
    if p["error"]:
        return f"[probe] {p['skill']}: the run failed; see {p['out']}"
    cov = f"{int(100 * p['coverage'])}%" if p["coverage"] is not None else "n/a (the body has no inline code)"
    return "\n".join([
        f"probe  {p['skill']}: without the skill the answer named {p['covered']} of {p['anchors']} key anchors ({cov})",
        f"  task     {p['task'][:160]}",
        f"  named    {', '.join(p['named'][:25]) or '-'}   (already known: trim candidates)",
        f"  missed   {', '.join(p['missed'][:25]) or '-'}   (what the skill is for, if they matter)",
        f"  answer   {p['out']}",
        "  Read the answer against the skill's three to five key instructions before judging; anchors are a heuristic."])


# ---------- grading ----------

def resolve(path: str, run: Path, variables: dict[str, str]) -> str | None:
    s = path
    for k, v in variables.items():
        if not k.startswith("__"):
            s = s.replace(f"<{k}>", v)
    for k in ("repo", "fixture", "temp folder", "cwd", "run"):
        s = s.replace(f"<{k}>", str(run))
    s = s.replace("<date>", "*")
    if UNRESOLVED.search(s):
        return None
    return s if os.path.isabs(s) else str(run / s)


def tri_or(vals):
    return True if any(v is True for v in vals) else (None if any(v is None for v in vals) else False)


def tri_and(vals):
    return False if any(v is False for v in vals) else (None if any(v is None for v in vals) else True)


def grade(ev, run: Path, res: dict, variables: dict[str, str], base_commit: str | None):
    """True, False, or None when the evidence cannot be checked here (an unresolved placeholder, a pseudo-code check)."""
    if not isinstance(ev, dict):
        return None
    t = ev.get("type")
    if t == "trace":
        tool, pat, must = re.compile(f"^(?:{tool_regex(ev.get('tool'))})$"), ev.get("input_match"), ev.get("must_contain")
        own = any(tool.match(str(u["name"])) and (not pat or re.search(pat, json.dumps(u["input"]), re.I)) and
                  (not must or must in json.dumps(u["input"])) for u in res["uses"])
    elif t == "sequence":
        i, own = 0, True
        for step in ev.get("steps") or []:
            tool = re.compile(f"^(?:{tool_regex(step.get('tool'))})$")
            while i < len(res["uses"]) and not (tool.match(str(res["uses"][i]["name"])) and (
                    not step.get("input_match") or re.search(step["input_match"], json.dumps(res["uses"][i]["input"]), re.I))):
                i += 1
            if i >= len(res["uses"]):
                own = False
                break
            i += 1
    elif t in ("file", "file_contains"):
        p = resolve(str(ev.get("path") or ""), run, variables)
        home = variables.get("__home__")
        if p is None or ev.get("must_not_exist_in"):
            own = None
        elif ev.get("check"):
            own = run_check(str(ev["check"]), run, Path(home) if home else None) if any(
                os.path.isfile(h) for h in glob.glob(p, recursive=True)) else False
        else:
            hits = [h for h in glob.glob(p, recursive=True) if os.path.isfile(h)]
            if ev.get("absent"):
                own = not hits
            else:
                rx = ev.get("match") or ev.get("regex")
                must = ev.get("must_contain")

                def ok(h):
                    try:
                        s = Path(h).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        return False
                    return (not rx or re.search(rx, s, re.I | re.M)) and (not must or must in s)
                own = any(ok(h) for h in hits)
    elif t == "command":
        cmd = str(ev.get("run") or ev.get("command") or "")
        for k, v in variables.items():
            if not k.startswith("__"):
                cmd = cmd.replace(f"<{k}>", v)
        if not cmd or ev.get("check") or ev.get("must_change") or UNRESOLVED.search(cmd):
            own = None
        else:
            home = variables.get("__home__")
            if home and not re.search(r"[|&;<>]", cmd):
                cmd = " ".join(localize(cmd.split(), run, Path(home)))
            try:
                r = subprocess.run(cmd, shell=True, cwd=str(run), capture_output=True, timeout=300)
                outp = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
                own = (ev["expect"] in outp) if ev.get("expect") else r.returncode == 0
            except Exception:
                own = False
    elif t in ("file_changed", "file_unchanged"):
        if not base_commit:
            own = None
        else:
            r = subprocess.run(["git", "diff", "--quiet", base_commit, "--", *ev.get("paths", [])], cwd=str(run))
            changed = r.returncode == 1
            own = changed if t == "file_changed" else not changed
    elif t is None and not any(k in ev for k in ("all", "any", "or", "and")):
        own = None
    else:
        own = True if t is None else None
    parts = [own]
    if isinstance(ev.get("and"), dict):
        parts = [tri_and([own, grade(ev["and"], run, res, variables, base_commit)])]
    if ev.get("all"):
        parts = [tri_and(parts + [grade(x, run, res, variables, base_commit) for x in ev["all"]])]
    if ev.get("any"):
        parts = [tri_and(parts + [tri_or([grade(x, run, res, variables, base_commit) for x in ev["any"]])])]
    v = parts[0]
    if isinstance(ev.get("or"), dict):
        v = tri_or([v, grade(ev["or"], run, res, variables, base_commit)])
    return v


def answer_regexes(case: dict) -> list[str]:
    out = []
    for e in case.get("expectations") or []:
        m = re.match(r"\s*regex on the answer:\s*(.+)$", str(e), re.I)
        if m:
            out.append(m.group(1).strip())
    return out


def grade_case(case: dict, run: Path, res: dict, variables: dict[str, str], base_commit: str | None):
    if case.get("evidence"):
        return grade(case["evidence"], run, res, variables, base_commit)
    rx = answer_regexes(case)
    if rx:
        return all(re.search(r, res["answer"], re.I | re.S) for r in rx)
    return None  # judged only by prose expectations: needs a judge, not this grader


# ---------- the A/B ----------

def plugin_root_of(skill_dir: Path) -> Path | None:
    for d in (skill_dir.parent.parent, skill_dir):
        if (d / ".claude-plugin" / "plugin.json").exists():
            return d
    return None


def prepare(case: dict, evals_home: Path, run: Path) -> str | None:
    """Lay the case's files and fixture into the run folder; commit a fixture so file_changed has a base."""
    fx = case.get("fixture")
    if fx:
        src = evals_home / "evals" / "fixtures" / fx
        if src.is_dir():
            shutil.copytree(src, run, dirs_exist_ok=True)
        for dest, source in (case.get("fixture_replace") or {}).items():
            shutil.copy2(evals_home / "evals" / source, run / dest)
    for f in case.get("files") or []:
        src = evals_home / f
        dst = run / f
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if not fx:
        return None
    g = ["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", "-c", "core.autocrlf=false"]
    subprocess.run(g + ["init", "-q"], cwd=str(run))
    subprocess.run(g + ["add", "-A"], cwd=str(run))
    subprocess.run(g + ["commit", "-q", "-m", "fixture"], cwd=str(run))
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(run), capture_output=True)
    return r.stdout.decode().strip() or None


def one_run(case: dict, arm: str, n: int, skill_dir: Path, name: str, evals_home: Path, out: Path,
            variables: dict[str, str], model: str | None, blind: bool) -> dict:
    run = Path(tempfile.mkdtemp(prefix=f"ab-{name}-{case['id']}-{arm}-{n}-"))
    base = prepare(case, evals_home, run)
    extra = isolation_args(blind) + ["--max-turns", str(case.get("max_turns") or MAX_TURNS.get(case["kind"], 20)),
                                     "--allowedTools", *(case.get("allowed_tools") or TOOLS.get(case["kind"], TOOLS["action"]) + list(case.get("tools") or []))]
    if model:
        extra += ["--model", model]
    if arm == "with":
        root = plugin_root_of(skill_dir)
        if root is not None:
            extra += ["--plugin-dir", str(root)]
        else:
            shutil.copytree(skill_dir, run / ".claude" / "skills" / name,
                            ignore=shutil.ignore_patterns(".git", "evals", "__pycache__"))
    raw, secs, code = run_claude(str(case["prompt"]), run, extra)
    (out / f"{case['id']}-{arm}-{n}.jsonl").write_text(raw, encoding="utf-8")
    res = parse_stream(raw)
    fired = any(u["name"] == "Skill" and str((u["input"] or {}).get("skill", "")).split(":")[-1] == name for u in res["uses"])
    passed = None if res["error"] and not res["uses"] else grade_case(case, run, res, variables, base)
    return {"passed": bool(passed), "error": passed is None or (res["error"] and not res["uses"]),
            "ungradable": passed is None, "skill_fired": fired, "turns": res["turns"], "durationSeconds": round(secs),
            "costUsd": res["cost"], "exit": code, "workdir": str(run)}


def run_ab(skill_dir: Path, unit: Path | None, runs: int = 3, case_glob: str | None = None, out: str | None = None,
           model: str | None = None, variables: dict[str, str] | None = None, blind: bool = False,
           concurrency: int = 3) -> Path | None:
    import fnmatch
    if blind and not os.environ.get("ANTHROPIC_API_KEY"):
        print("[worth --ab] --blind needs ANTHROPIC_API_KEY (`claude --bare` skips OAuth); run without it, or set the key")
        return None
    fm, _ = ew.parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    name = fm.get("name") or skill_dir.name
    homes = [h for h in (skill_dir, unit) if h is not None and (h / "evals" / "evals.json").exists()]
    if not homes:
        print(f"[worth --ab] {name} has no evals/evals.json; write value cases first (evergreen-test Step 2)")
        return None
    home = homes[0]
    kinds = ew.case_kinds(home)
    cases = [c for cid, c in sorted(kinds.items()) if c.get("kind") in ew.VALUE_KINDS and not c.get("decoy")
             and (home.resolve() == skill_dir.resolve() or c.get("_skill", "").split(":")[-1] == name)
             and (not case_glob or fnmatch.fnmatch(cid, case_glob)) and (case_glob or not c.get("redundant"))]
    if not cases:
        print(f"[worth --ab] {name}: no value case to run (action or outcome, not redundant)")
        return None
    dest = Path(out).expanduser() if out else Path(tempfile.mkdtemp(prefix=f"worth-ab-{name}-"))
    dest.mkdir(parents=True, exist_ok=True)
    jobs = [(c, arm, n) for c in cases for arm in ("with", "without") for n in range(1, runs + 1)]
    print(f"[worth --ab] {name}: {len(cases)} value case(s) x 2 arms x {runs} runs = {len(jobs)} headless runs -> {dest}")
    started = datetime.now().isoformat(timespec="seconds")
    results: dict[tuple[str, str], list[dict]] = {}
    with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        var = {**(variables or {}), "__home__": str(home)}
        futs = {pool.submit(one_run, c, arm, n, skill_dir, name, home, dest, var, model, blind): (c["id"], arm)
                for c, arm, n in jobs}
        for f in cf.as_completed(futs):
            cid, arm = futs[f]
            try:
                r = f.result()
            except Exception as e:  # one broken run must not lose the others
                r = {"passed": False, "error": True, "ungradable": False, "skill_fired": False, "turns": 0,
                     "durationSeconds": 0, "costUsd": 0.0, "note": str(e)[:200]}
            results.setdefault((cid, arm), []).append(r)
            print(f"  {cid:24} {arm:7} {'ungradable' if r.get('ungradable') else 'pass' if r['passed'] else 'fail'}"
                  f"{' (skill fired)' if r.get('skill_fired') else ''}  {r['durationSeconds']}s ${r['costUsd']:.2f}")
    agg = {"suite": {"ablation": "with-without", "harness": "evergreen.py worth --ab (claude -p, stream-json)",
                     "isolation": "--bare (blind)" if blind else "--setting-sources project (the user's CLAUDE.md loads in both arms)",
                     "skill": name, "runs": runs},
           "startedAt": started, "cases": []}
    notes = []
    for c in cases:
        w, wo = results.get((c["id"], "with"), []), results.get((c["id"], "without"), [])
        agg["cases"].append({"name": c["id"], "arms": {"with": w, "without": wo}})
        if all(r.get("ungradable") for r in w + wo):
            notes.append(f"{c['id']}: ungradable here (placeholders or a judge-only expectation); pass --var or grade by hand")
        if w and not any(r.get("skill_fired") for r in w):
            notes.append(f"{c['id']}: the skill never fired in the with arm, so this case measures nothing; tune triggering first (evergreen-tune, undertrigger)")
        if any(r.get("skill_fired") for r in wo):
            notes.append(f"{c['id']}: the skill fired in the without arm; the baseline is contaminated")
    (dest / "aggregate-result.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
    for n_ in notes:
        print(f"  ! {n_}")
    return dest
