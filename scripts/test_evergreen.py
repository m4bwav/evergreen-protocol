#!/usr/bin/env python3
"""Self-test for evergreen.py. Run: python scripts/test_evergreen.py"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evergreen as eg  # noqa: E402

NOW = datetime(2026, 9, 1, 12, 0)


def state(tier="moderate", interval=None, **kw):
    st = eg.new_state("t", "topic", "skill", tier, "SKILL.md", "MAINTENANCE.md", None, NOW.date())
    if interval is not None:
        st["interval_days"] = interval
    st.update(kw)
    return st


def capture(argv) -> str:
    """Run a CLI command and return what it printed."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        eg.main(argv)
    return buf.getvalue()


def run(st, ms, now=NOW):
    """Apply a sequence of magnitudes, returning the final state and intervals seen."""
    seen = []
    for m in ms:
        st = eg.compute_next(st, m, now, jitter=False)
        seen.append(st["interval_days"])
        now = now + timedelta(days=st["interval_days"] or 1)
    return st, seen


class IntervalRule(unittest.TestCase):
    def test_quiet_walks_to_cap_and_settles(self):
        st, seen = run(state("moderate", 30), [0, 0, 0, 0, 0])
        self.assertEqual(seen, [45, 67.5, 90, 90, 90])

    def test_shakeup_halves_or_quarters(self):
        st = state("moderate", 90)
        st = eg.compute_next(st, 0.7, NOW, jitter=False)
        self.assertEqual(st["interval_days"], 22.5)
        st = eg.compute_next(st, 0.4, NOW, jitter=False)
        self.assertEqual(st["interval_days"], 14)  # clamped at min

    def test_minor_churn_holds(self):
        st = eg.compute_next(state("fast", 14), 0.2, NOW, jitter=False)
        self.assertEqual(st["interval_days"], 14)

    def test_contradiction_resets_to_min(self):
        st = state("slow", 200)
        st["contradiction"] = {"date": "2026-08-30", "note": "x"}
        st = eg.compute_next(st, 0.0, NOW, jitter=False)
        self.assertEqual(st["interval_days"], 60)
        self.assertIsNone(st["contradiction"])

    def test_failed_refresh_keeps_schedule(self):
        st = state("fast", 14)
        st["next_due"] = "2026-09-10"
        new = eg.compute_next(st, None, NOW, jitter=False)
        self.assertEqual(new["next_due"], "2026-09-10")
        self.assertIsNone(new["history"][-1]["m"])

    def test_next_due_and_history(self):
        st = eg.compute_next(state("fast", 14), 0.0, NOW, jitter=False)
        self.assertEqual(st["last_checked"], "2026-09-01")
        self.assertEqual(st["next_due"], "2026-09-22")
        self.assertEqual(st["history"][-1]["interval_after"], 21)

    def test_event_caps_next_due(self):
        st = state("slow", 120)
        st["events"] = [{"date": "2026-09-20", "label": "release", "settle_days": 2}]
        st = eg.compute_next(st, 0.0, NOW, jitter=False)
        self.assertEqual(st["next_due"], "2026-09-22")
        self.assertEqual(len(st["events"]), 1)
        # past events are dropped
        st["events"] = [{"date": "2026-01-01", "label": "old", "settle_days": 2}]
        st = eg.compute_next(st, 0.0, NOW, jitter=False)
        self.assertEqual(st["events"], [])

    def test_promotion_after_two_pinned_min(self):
        st = state("moderate", 14)
        st = eg.compute_next(st, 0.5, NOW, jitter=False)  # pinned 1
        self.assertEqual(st["tier"], "moderate")
        st = eg.compute_next(st, 0.5, NOW, jitter=False)  # pinned 2 -> promote to fast at fast's min
        self.assertEqual(st["tier"], "fast")
        self.assertEqual(st["interval_days"], 3)
        self.assertEqual(st["streak"]["pinned_min"], 0)

    def test_major_change_promotes_immediately_out_of_slow(self):
        st = eg.compute_next(state("slow", 120), 0.9, NOW, jitter=False)
        self.assertEqual(st["tier"], "moderate")
        self.assertEqual(st["interval_days"], 30)  # 120/4, inside moderate's bounds
        st = eg.compute_next(state("glacial", 365), 0.9, NOW, jitter=False)
        self.assertEqual(st["tier"], "slow")
        self.assertEqual(st["interval_days"], 91.25)
        st = eg.compute_next(state("moderate", 30), 0.9, NOW, jitter=False)
        self.assertEqual(st["tier"], "fast")
        self.assertEqual(st["interval_days"], 7.5)

    def test_custom_bounds_respected_and_dropped_on_migration(self):
        st = state("moderate", 30, bounds_days={"min": 20, "max": 60})
        st = eg.compute_next(st, 0.4, NOW, jitter=False)
        self.assertEqual(st["interval_days"], 20)
        st = eg.compute_next(st, 0.4, NOW, jitter=False)  # pinned 2 -> promote, bounds dropped
        self.assertEqual(st["tier"], "fast")
        self.assertNotIn("bounds_days", st)

    def test_fast_pinned_three_times_becomes_verify_at_use(self):
        st = state("fast", 3)
        for _ in range(3):
            st = eg.compute_next(st, 0.6, NOW, jitter=False)
        self.assertTrue(st["verify_at_use"])
        self.assertEqual(st["tier"], "fast")
        self.assertIsNone(st["next_due"])
        fr = eg.freshness(st, NOW + timedelta(days=400))
        self.assertEqual(fr["status"], "n/a")
        self.assertIn("verify-at-use", fr["flags"])

    def test_verify_at_use_turns_off_after_two_quiet_use_checks(self):
        st = state("fast", 3, verify_at_use=True)
        st = eg.compute_next(st, 0.0, NOW, use_time=True, jitter=False)
        self.assertTrue(st["verify_at_use"])
        st = eg.compute_next(st, 0.0, NOW, use_time=True, jitter=False)
        self.assertFalse(st["verify_at_use"])
        self.assertEqual(st["interval_days"], 14)

    def test_demotion_after_three_pinned_max(self):
        st = state("fast", 21)
        for _ in range(3):
            st = eg.compute_next(st, 0.0, NOW, jitter=False)
        self.assertEqual(st["tier"], "moderate")
        self.assertEqual(st["interval_days"], 21)

    def test_glacial_never_demotes(self):
        st = state("glacial", 900)
        for _ in range(4):
            st = eg.compute_next(st, 0.0, NOW, jitter=False)
        self.assertEqual(st["tier"], "glacial")

    def test_none_tier_has_no_schedule(self):
        st = eg.compute_next(state("none"), 0.0, NOW, jitter=False)
        self.assertIsNone(st["next_due"])

    def test_live_uses_hours(self):
        st = eg.compute_next(state("live", 0.25), 0.0, NOW, jitter=False)
        self.assertEqual(st["interval_days"], 0.38)
        self.assertIn("T", st["next_due"])

    def test_jitter_stays_within_band(self):
        for _ in range(50):
            st = eg.compute_next(state("moderate", 30), 0.0, NOW, jitter=True)
            due = eg.parse_when(st["next_due"])
            days = (due - NOW).total_seconds() / 86400
            self.assertTrue(45 * 0.85 - 1 <= days <= 45 * 1.15 + 1)
            self.assertEqual(st["interval_days"], 45)  # stored interval unjittered


class Freshness(unittest.TestCase):
    def test_stale_and_fresh(self):
        st = state("fast", 14)
        st["next_due"] = "2026-08-20"
        self.assertEqual(eg.freshness(st, NOW)["status"], "STALE")
        st["next_due"] = "2026-09-20"
        self.assertEqual(eg.freshness(st, NOW)["status"], "fresh")
        st["contradiction"] = {"date": "x", "note": "y"}
        self.assertEqual(eg.freshness(st, NOW)["status"], "STALE")

    def test_none_tier_na(self):
        self.assertEqual(eg.freshness(state("none"), NOW)["status"], "n/a")

    def test_test_flags_never_change_status(self):
        st = state("moderate", 30)
        st["next_due"] = "2026-09-20"
        self.assertEqual(eg.test_flags(st, NOW), ["untested"])
        st["tests"]["last_run"] = "2026-08-30T10:00"
        self.assertEqual(eg.test_flags(st, NOW), [])
        st["tests"]["last_run"] = "2026-06-01"  # 92 days > 2 x 30
        st["tests"]["failing"] = ["action-1", "decoy-2"]
        self.assertEqual(eg.test_flags(st, NOW), ["failing-tests:2", "tests-overdue"])
        self.assertEqual(eg.freshness(st, NOW)["status"], "fresh")
        st["tier"] = "none"
        self.assertEqual(eg.test_flags(st, NOW), ["failing-tests:2"])
        self.assertEqual(eg.test_flags({"kind": "doc"}, NOW), [])  # no tests block: nothing to say

    def test_research_after_default_is_half_the_interval_clamped(self):
        self.assertEqual(eg.research_after(state("moderate", 30)), 15)
        self.assertEqual(eg.research_after(state("fast", 4)), 3)
        self.assertEqual(eg.research_after(state("slow", 120)), 30)
        st = state("moderate", 30)
        st["tests"]["research_after_days"] = 7
        self.assertEqual(eg.research_after(st), 7)
        self.assertEqual(eg.research_after({"kind": "doc", "interval_days": 30}), 15)


class Home(unittest.TestCase):
    def test_windows_path_ignored_on_posix(self):
        if os.name == "nt":
            self.skipTest("posix only")
        old = os.environ.pop("EVERGREEN_HOME", None)
        try:
            os.environ["EVERGREEN_HOME"] = "D:\\somewhere\\Evergreen"
            self.assertEqual(eg.evergreen_home(), Path.home() / ".evergreen")
        finally:
            os.environ.pop("EVERGREEN_HOME", None)
            if old:
                os.environ["EVERGREEN_HOME"] = old

    def test_config_dict_keyed_by_os(self):
        cfg = eg.plugin_root() / "evergreen.config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertIsInstance(data["home"], dict)
        self.assertIn("nt", data["home"])
        self.assertIn("posix", data["home"])


class Scaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        os.environ["EVERGREEN_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.pop("EVERGREEN_HOME", None)
        self.tmp.cleanup()

    def test_init_standalone_links_and_lint(self):
        d = Path(self.tmp.name) / "myskill"
        rc = eg.main(["init", str(d), "--name", "myskill", "--topic", "t", "--tier", "fast", "--standalone", "--last-checked", "2026-09-01"])
        self.assertEqual(rc, 0)
        for f in ("SKILL.md", "RESEARCH.md", "CHANGELOG.md", "LEARNINGS.md", "MAINTENANCE.md", "evergreen.json"):
            self.assertTrue((d / f).exists(), f)
        _, st = eg.load_state(d)
        self.assertEqual(st["protocol"], "MAINTENANCE.md")
        self.assertEqual(st["next_due"], "2026-09-15")
        self.assertEqual(eg.check_links(d, st), [])
        self.assertEqual([n for n in eg.lint(d, st) if "missing" in n], [])
        reg = eg.load_registry()
        self.assertEqual(len(reg["units"]), 1)
        # IDs in templates use compact dates
        self.assertIn("R-20260901-1", (d / "RESEARCH.md").read_text(encoding="utf-8"))

    def test_init_existing_main_appends_maintenance(self):
        d = Path(self.tmp.name) / "old"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: old\ndescription: x\n---\n# Old\n\nbody\n", encoding="utf-8")
        eg.main(["init", str(d), "--name", "old", "--topic", "t", "--tier", "moderate", "--append-maintenance", "--standalone"])
        txt = (d / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("# Old", txt)
        self.assertIn("## Maintenance", txt)
        self.assertIn("## Step 0", txt)
        _, st = eg.load_state(d)
        self.assertEqual(eg.check_links(d, st), [])

    def test_links_detect_missing_backlink_and_undefined_id(self):
        d = Path(self.tmp.name) / "bad"
        eg.main(["init", str(d), "--name", "bad", "--topic", "t", "--standalone"])
        (d / "CHANGELOG.md").write_text("# Changelog\n\nno links here; see R-20260101-9\n", encoding="utf-8")
        _, st = eg.load_state(d)
        probs = eg.check_links(d, st)
        self.assertTrue(any("CHANGELOG.md does not link to" in p for p in probs))
        self.assertTrue(any("R-20260101-9" in p for p in probs))

    def test_lint_flags_missing_fields(self):
        d = Path(self.tmp.name) / "lint"
        eg.main(["init", str(d), "--name", "lint", "--topic", "t", "--standalone"])
        (d / "LEARNINGS.md").write_text("# Learnings: lint\n\nSKILL.md RESEARCH.md CHANGELOG.md\n\n### L-001 · 2026-09-01 · x\n- Rule: y\n- Status: active\n", encoding="utf-8")
        _, st = eg.load_state(d)
        notes = eg.lint(d, st)
        self.assertTrue(any("L-001: missing Trigger" in n for n in notes))

    def test_checked_command_updates_file_and_registry(self):
        d = Path(self.tmp.name) / "chk"
        eg.main(["init", str(d), "--name", "chk", "--topic", "t", "--tier", "fast", "--standalone"])
        eg.main(["checked", str(d), "--m", "0.7", "--note", "big change", "--no-jitter"])
        _, st = eg.load_state(d)
        self.assertEqual(st["interval_days"], 3.5)
        self.assertEqual(st["history"][-1]["note"], "big change")
        self.assertEqual(st["counts"]["research"], 1)

    def test_map_init_creates_codemap_unit(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        eg.main(["map-init", str(repo), "--name", "repo"])
        slug = eg.map_slug(repo)
        d = self.home / "maps" / slug
        self.assertTrue((d / "CODEMAP.md").exists())
        _, st = eg.load_state(d)
        self.assertEqual(st["tier"], "code")
        self.assertEqual(st["repo"]["root"], str(repo.resolve()))
        self.assertIn("may be out of date", (d / "CODEMAP.md").read_text(encoding="utf-8").lower())
        self.assertEqual(eg.check_links(d, st), [])

    def test_backdated_init_passes_links(self):
        d = Path(self.tmp.name) / "old-research"
        eg.main(["init", str(d), "--name", "oldr", "--topic", "t", "--standalone", "--last-checked", "2026-05-01"])
        _, st = eg.load_state(d)
        self.assertEqual(st["next_due"], "2026-05-31")
        self.assertEqual(eg.check_links(d, st), [])
        self.assertEqual(eg.freshness(st, NOW)["status"], "STALE")

    def test_flag_event_parsing(self):
        d = Path(self.tmp.name) / "ev"
        eg.main(["init", str(d), "--name", "ev", "--topic", "t", "--tier", "slow", "--standalone"])
        eg.main(["flag", str(d), "--event", '2026-09-20:"Big release":3', "--event", "2026-10-01T09:30:conf"])
        _, st = eg.load_state(d)
        self.assertEqual(st["events"][0]["label"], "Big release")
        self.assertEqual(st["events"][0]["settle_days"], 3)
        self.assertEqual(st["events"][1]["date"], "2026-10-01T09:30")
        self.assertEqual(st["next_due"], "2026-09-23")

    def test_pack_and_export(self):
        out = Path(self.tmp.name) / "dist"
        paths = eg.pack(out, git_tag=False)  # never tag the real trunk from a test
        import zipfile
        with zipfile.ZipFile(paths[0]) as z:
            names = z.namelist()
            self.assertIn("INSTALL.txt", names)
            self.assertIn("INSTALL-PROMPT.txt", names)
            prompt = z.read("INSTALL-PROMPT.txt").decode("utf-8")
            self.assertIn("PASTE THE FOLDER PATH HERE", prompt)
            self.assertIn(f"evergreen-{eg.plugin_version()}-mail.zip", prompt)
            self.assertNotIn("{version}", prompt)
            self.assertIn("EASIEST INSTALL", z.read("INSTALL.txt").decode("utf-8"))
            self.assertIn("evergreen/README.md", names)
            self.assertIn("evergreen/MANIFEST.json", names)
            self.assertIn("evergreen/skills/evergreen-refresh/SKILL.md", names)
            self.assertFalse(any("__pycache__" in n or n.endswith(".pyc") for n in names))
            man = json.loads(z.read("evergreen/MANIFEST.json"))
            self.assertIn("README.md", man["files"])
            self.assertRegex(man["pack_id"], r"^\d{8}-[0-9a-f]{8}$")
        with zipfile.ZipFile(paths[1]) as z:
            self.assertIn(".claude-plugin/plugin.json", z.namelist())
            self.assertIn("MANIFEST.json", z.namelist())
        # packing baselines the shipped state in the (temp) store and keeps the archive
        self.assertTrue(any((d / "baseline.json").exists() for d in (self.home / "baselines").iterdir()))
        self.assertTrue(any(p.name.startswith("evergreen-") for p in (self.home / "packs").iterdir()))
        # email-safe form: blocked script types stored as .txt, no .plugin, and unmail restores them
        self.assertTrue(paths[2].name.endswith("-INSTALL-PROMPT.txt") and paths[2].exists())
        mail = eg.pack(out, mail=True, git_tag=False)
        self.assertTrue(mail[0].name.endswith("-mail.zip"))
        self.assertEqual([p.suffix for p in mail], [".zip", ".txt"])  # no pieces unless asked
        # split form: pieces beside the whole zip, joining them in order gives the zip back
        pieces = [p for p in eg.pack(out, mail=True, git_tag=False, split_kb=40) if ".part" in p.suffix]
        self.assertGreater(len(pieces), 1)
        self.assertEqual(b"".join(p.read_bytes() for p in pieces), mail[0].read_bytes())
        self.assertTrue(all(p.stat().st_size <= 40 * 1024 for p in pieces))
        with zipfile.ZipFile(mail[0]) as z:
            names = z.namelist()
            self.assertIn("evergreen/scripts/pack.ps1.txt", names)
            self.assertFalse(any(n.endswith(".ps1") for n in names))
            z.extractall(out / "unz")
        restored = eg.unmail(out / "unz")
        self.assertTrue((out / "unz" / "evergreen" / "scripts" / "pack.ps1").exists())
        self.assertEqual(len(restored), 2)
        repo = Path(self.tmp.name) / "somerepo"
        repo.mkdir()
        dest = eg.export(repo)
        self.assertTrue((dest / "skills" / "evergreen-refresh" / "SKILL.md").exists())
        self.assertTrue((dest / "protocol" / "PROTOCOL.md").exists())
        self.assertFalse((dest / "hooks").exists())

    def test_share_pack_drops_profile_and_the_owner_address(self):
        import zipfile
        out = Path(self.tmp.name) / "sharedist"
        before = sorted(p.name for p in (self.home / "baselines").iterdir()) if (self.home / "baselines").exists() else []
        paths = eg.pack(out, share=True)  # git_tag/after are forced off for a share pack
        zpath, ppath, prompt_path = paths
        self.assertTrue(zpath.name.endswith("-share.zip") and ppath.name == "evergreen-share.plugin")
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            self.assertFalse(any(n.startswith("evergreen/profile/") for n in names), "share pack must not carry profile/")
            self.assertIn("evergreen/protocol/PROTOCOL.md", names)
            self.assertIn("evergreen/skills/evergreen-refresh/SKILL.md", names)
            cfg = json.loads(z.read("evergreen/evergreen.config.json"))
            self.assertEqual(cfg["notify"]["to"], "")
            self.assertFalse(cfg["notify"]["auto"])
            self.assertNotIn("outbox_copy_to", cfg["notify"])
            # the manifest hashes what is shipped, not what is on disk
            man = json.loads(z.read("evergreen/MANIFEST.json"))
            self.assertNotIn("profile/AI-PREFERENCES.md", man["files"])
            self.assertEqual(man["files"]["evergreen.config.json"],
                             hashlib.sha256(z.read("evergreen/evergreen.config.json")).hexdigest())
            prompt = z.read("INSTALL-PROMPT.txt").decode("utf-8")
            self.assertIn(f"evergreen-{eg.plugin_version()}-share-mail.zip", prompt)
            self.assertIn("my-local", prompt)
            self.assertNotIn("mark-local", prompt)
            self.assertIn("SHARE COPY", z.read("INSTALL.txt").decode("utf-8"))
        self.assertTrue(prompt_path.name.endswith("-share-INSTALL-PROMPT.txt"))
        # a baseline read from an archive sees plugin files only, never the archive's own convenience files
        seen, _ = es.files_from_zip(zpath)
        self.assertNotIn("INSTALL-PROMPT.txt", seen)
        self.assertNotIn("INSTALL.txt", seen)
        self.assertIn("templates/INSTALL-PROMPT.txt", seen)
        self.assertNotIn("profile/AI-PREFERENCES.md", seen)
        # a gift is not a report: no new baseline, and the owner's own config on disk is untouched
        after = sorted(p.name for p in (self.home / "baselines").iterdir()) if (self.home / "baselines").exists() else []
        self.assertEqual(before, after)
        self.assertEqual(json.loads((eg.plugin_root() / "evergreen.config.json").read_text(encoding="utf-8"))["notify"]["to"],
                         "owner@example.com")

    def test_lint_wants_all_four_search_tracks(self):
        d = Path(self.tmp.name) / "tracks"
        eg.main(["init", str(d), "--name", "tracks", "--topic", "t", "--tier", "moderate", "--standalone",
                 "--last-checked", "2026-09-01"])
        _, st = eg.load_state(d)
        self.assertEqual([n for n in eg.lint(d, st) if "Search plan" in n], [],
                         "the template's plan already carries the four tracks")
        r = d / "RESEARCH.md"
        r.write_text(r.read_text(encoding="utf-8").replace("Tooling (", "Other (").replace("Practice (", "More ("),
                     encoding="utf-8")
        notes = [n for n in eg.lint(d, st) if "Search plan" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("tooling, practice", notes[0])
        st["tier"] = "none"  # a unit with no web research is not asked for tracks
        self.assertEqual([n for n in eg.lint(d, st) if "Search plan" in n], [])

    def test_lint_testing_track_is_required(self):
        d = Path(self.tmp.name) / "tracks4"
        eg.main(["init", str(d), "--name", "tracks4", "--topic", "t", "--tier", "moderate", "--standalone"])
        _, st = eg.load_state(d)
        three = "# R\n\n## Search plan\n\nSubject (x):\n- q\n\nTooling (y):\n- q\n\nPractice (z):\n- q\n\n## Findings log\n"
        (d / "RESEARCH.md").write_text(three, encoding="utf-8")
        notes = [n for n in eg.lint(d, st) if "Search plan" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("missing the testing track (PROTOCOL", notes[0])
        (d / "RESEARCH.md").write_text(three.replace("## Findings log", "Testing (harness and eval practice):\n- q\n\n## Findings log"), encoding="utf-8")
        self.assertEqual([n for n in eg.lint(d, st) if "Search plan" in n], [])

    def test_new_state_tests_block_by_kind(self):
        st = eg.new_state("s", "t", "skill", "moderate", "SKILL.md", "plugin", None)
        self.assertEqual(st["files"]["tests"], "TESTS.md")
        self.assertEqual(st["tests"], {"last_run": None, "harness": None, "env": None, "cases": 0, "passed": 0, "failed": 0,
                                       "failing": [], "last_failure": None, "research_after_days": None})
        self.assertEqual(st["counts"]["tests"], 0)
        self.assertIn("tests", eg.new_state("p", "t", "plugin", "fast", "README.md", "protocol/PROTOCOL.md", None))
        for kind in ("doc", "profile", "map"):
            st = eg.new_state("d", "t", kind, "slow", "DOC.md", "MAINTENANCE.md", None)
            self.assertNotIn("tests", st, kind)
            self.assertNotIn("tests", st["files"], kind)

    def test_init_skill_writes_tests_and_evals(self):
        d = Path(self.tmp.name) / "tested-skill"
        out = capture(["init", str(d), "--name", "tested-skill", "--topic", "t", "--tier", "moderate", "--standalone",
                       "--last-checked", "2026-09-01"])
        self.assertIn("wrote TESTS.md", out)
        self.assertIn("wrote evals/evals.json", out)
        self.assertTrue((d / "TESTS.md").exists() and (d / "evals" / "evals.json").exists())
        tests = (d / "TESTS.md").read_text(encoding="utf-8")
        self.assertIn("### T-20260901-1", tests)
        for sib in ("SKILL.md", "RESEARCH.md", "CHANGELOG.md", "LEARNINGS.md"):
            self.assertIn(sib, tests)
        ev = json.loads((d / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(ev["skill"], "tested-skill")
        _, st = eg.load_state(d)
        self.assertEqual(eg.check_links(d, st), [])
        notes = eg.lint(d, st)
        self.assertTrue(any("TODO prompts" in n for n in notes), notes)
        self.assertFalse(any('"kind": "action"' in n for n in notes), notes)  # the template ships an action case
        self.assertFalse(any("no decoy case" in n for n in notes), notes)  # and two decoys
        self.assertFalse(any("led to" in n for n in notes), notes)
        # a run without a `led to:` line, an evals file without action or decoy cases, and an oversized log are all noted
        (d / "TESTS.md").write_text(tests + "\n### T-20260902-1 · 2026-09-02 · manual · here · 3/4\n- action-1 · action · no-op · no tool call\n", encoding="utf-8")
        (d / "evals" / "evals.json").write_text(json.dumps({"skill": "x", "evals": [{"id": "t1", "kind": "trigger", "prompt": "real"}]}), encoding="utf-8")
        notes = eg.lint(d, st)
        self.assertTrue(any(n.startswith("T-20260902-1: no 'led to:'") for n in notes), notes)
        self.assertTrue(any('no case with "kind": "action"' in n for n in notes), notes)
        self.assertTrue(any("no decoy case" in n for n in notes), notes)
        self.assertFalse(any("TODO prompts" in n for n in notes), notes)
        (d / "TESTS.md").write_text(tests + "\n" * 160, encoding="utf-8")
        self.assertTrue(any("archive older runs to TESTS-ARCHIVE.md" in n for n in eg.lint(d, st)))
        # a doc gets neither the files nor the evals note
        dd = Path(self.tmp.name) / "adoc"
        eg.main(["init", str(dd), "--name", "adoc", "--kind", "doc", "--main", "DOC.md", "--topic", "t", "--standalone"])
        self.assertFalse((dd / "TESTS.md").exists() or (dd / "evals").exists())
        _, dst = eg.load_state(dd)
        self.assertFalse(any("evals" in n for n in eg.lint(dd, dst)))

    def test_test_init_adds_the_layer_idempotently(self):
        d = Path(self.tmp.name) / "older"
        eg.main(["init", str(d), "--name", "older", "--topic", "t", "--tier", "fast", "--standalone", "--last-checked", "2026-08-01"])
        _, st = eg.load_state(d)
        del st["tests"]
        del st["files"]["tests"]
        eg.save_state(d, st)
        (d / "TESTS.md").unlink()
        (d / "evals" / "evals.json").unlink()
        self.assertEqual(eg.test_flags(st), [])  # an older unit without the block is simply silent
        out = capture(["test-init", str(d)])
        self.assertIn("added files.tests", out)
        self.assertIn("added tests block", out)
        self.assertIn("wrote TESTS.md", out)
        self.assertIn("wrote evals/evals.json", out)
        _, st = eg.load_state(d)
        self.assertEqual(st["files"]["tests"], "TESTS.md")
        self.assertIsNone(st["tests"]["last_run"])
        self.assertIn("### T-20260801-1", (d / "TESTS.md").read_text(encoding="utf-8"))
        before = (d / "evergreen.json").read_text(encoding="utf-8")
        out2 = capture(["test-init", str(d)])
        self.assertIn("kept existing TESTS.md", out2)
        self.assertNotIn("added", out2)
        self.assertEqual((d / "evergreen.json").read_text(encoding="utf-8"), before)
        dd = Path(self.tmp.name) / "adoc2"
        eg.main(["init", str(dd), "--name", "adoc2", "--kind", "doc", "--main", "DOC.md", "--topic", "t", "--standalone"])
        self.assertIn("no test suite", capture(["test-init", str(dd)]))
        self.assertNotIn("tests", eg.load_state(dd)[1])

    def test_tested_records_the_run_and_names_the_next_entry(self):
        d = Path(self.tmp.name) / "run"
        eg.main(["init", str(d), "--name", "run", "--topic", "t", "--tier", "moderate", "--standalone", "--last-checked", "2026-09-01"])
        today = eg.today().strftime("%Y%m%d")
        out = capture(["tested", str(d), "--passed", "5", "--failed", "1", "--failing", "action-1", "--harness", "manual", "--env", "lab", "--note", "no tool call"])
        self.assertIn(f"run: tests 5/6 passed, failing [action-1]; next entry T-{today}-1", out)
        _, st = eg.load_state(d)
        t = st["tests"]
        self.assertEqual((t["cases"], t["passed"], t["failed"], t["failing"], t["harness"], t["env"]), (6, 5, 1, ["action-1"], "manual", "lab"))
        self.assertTrue(t["last_run"].startswith(eg.today().isoformat()))
        self.assertEqual(t["last_failure"]["note"], "no tool call")
        self.assertEqual(st["counts"]["tests"], 1)
        self.assertIn("[failing-tests:1]", capture(["status", str(d)]))
        # a clean run clears the failing list, keeps the last failure, and the id stays -1 until a head is written
        out = capture(["tested", str(d), "--passed", "6", "--failed", "0", "--failing", "action-1"])
        self.assertIn(f"failing []; next entry T-{today}-1", out)
        _, st = eg.load_state(d)
        self.assertEqual(st["tests"]["failing"], [])
        self.assertEqual(st["tests"]["harness"], "manual")  # kept when not given again
        self.assertEqual(st["tests"]["last_failure"]["note"], "no tool call")
        self.assertEqual(st["counts"]["tests"], 2)
        tp = d / "TESTS.md"
        tp.write_text(tp.read_text(encoding="utf-8").replace("## Runs\n", f"## Runs\n\n### T-{today}-1 · today · manual · lab · 6/6\n- led to: none\n", 1), encoding="utf-8")
        self.assertIn(f"next entry T-{today}-2", capture(["tested", str(d), "--passed", "6"]))
        self.assertEqual(eg.next_entry_id(d, st, "R"), f"R-{today}-1")
        out = capture(["bump", str(d), "--tests"])
        self.assertIn("'tests': 4", out)

    def test_failed_says_research_first_or_tune(self):
        d = Path(self.tmp.name) / "fail"
        eg.main(["init", str(d), "--name", "fail", "--topic", "t", "--tier", "moderate", "--standalone"])  # checked today
        today = eg.today().strftime("%Y%m%d")
        out = capture(["failed", str(d), "--case", "trigger-2", "--class", "no-op", "--note", "did nothing"])
        self.assertIn("research due", out)
        self.assertIn("class no-op", out)
        self.assertIn(f"next entry T-{today}-2", out)  # the scaffold's own T-<today>-1 already sits in TESTS.md
        _, st = eg.load_state(d)
        self.assertEqual(st["tests"]["failing"], ["trigger-2"])
        self.assertEqual(st["tests"]["last_failure"]["class"], "no-op")
        out = capture(["failed", str(d), "--case", "outcome-1", "--class", "wrong-outcome"])
        self.assertIn("research not due (checked 0 days ago, threshold 15d); tune directly", out)
        _, st = eg.load_state(d)
        self.assertEqual(st["tests"]["failing"], ["trigger-2", "outcome-1"])
        st["last_checked"] = (eg.today() - timedelta(days=40)).isoformat()
        eg.save_state(d, st)
        out = capture(["failed", str(d), "--case", "outcome-1", "--class", "wrong-outcome"])
        self.assertIn("research due: last checked 40 days ago (threshold 15d)", out)
        self.assertEqual(eg.load_state(d)[1]["tests"]["failing"], ["trigger-2", "outcome-1"])  # no duplicate
        self.assertIn("failing now [outcome-1]", capture(["flag", str(d), "--clear-failing", "trigger-2"]))
        capture(["flag", str(d), "--clear-failing"])
        self.assertEqual(eg.load_state(d)[1]["tests"]["failing"], [])
        st = eg.load_state(d)[1]
        st["tier"] = "none"
        self.assertIn("tune directly", eg.research_verdict(st, "no-op"))

    def test_t_ids_are_checked_like_the_other_ids(self):
        self.assertEqual(eg.ID_RE.findall("fixed by T-20260904-1, see C-20260904-2 and other:T-20260904-3"), ["T-20260904-1", "C-20260904-2"])
        d = Path(self.tmp.name) / "tid"
        eg.main(["init", str(d), "--name", "tid", "--topic", "t", "--standalone", "--last-checked", "2026-09-01"])
        cl = d / "CHANGELOG.md"
        cl.write_text(cl.read_text(encoding="utf-8") + "\n### C-20260904-1 · 2026-09-04 · Tightened trigger\n- because: T-20260904-1\n", encoding="utf-8")
        _, st = eg.load_state(d)
        self.assertIn("referenced but never defined: T-20260904-1", eg.check_links(d, st))
        tp = d / "TESTS.md"
        tp.write_text(tp.read_text(encoding="utf-8") + "\n### T-20260904-1 · 2026-09-04 · manual · here · 5/6\n- action-1 · action · no-op · x\n- led to: C-20260904-1\n", encoding="utf-8")
        self.assertEqual([p for p in eg.check_links(d, st) if "T-2026" in p], [])
        # an archived run still counts as a definition
        tp.write_text(tp.read_text(encoding="utf-8").replace("### T-20260904-1", "### T-20260904-9"), encoding="utf-8")
        self.assertIn("referenced but never defined: T-20260904-1", eg.check_links(d, st))
        (d / "TESTS-ARCHIVE.md").write_text("# Archive\n\n### T-20260904-1 · old\n- led to: none\n", encoding="utf-8")
        self.assertEqual([p for p in eg.check_links(d, st) if "T-2026" in p], [])

    def test_use_log_and_uses(self):
        payload = {"session_id": "1234abcd-ef", "transcript_path": "/x/t.jsonl", "cwd": "/work", "hook_event_name": "PostToolUse",
                   "tool_name": "Skill", "tool_input": {"skill": "evergreen-audit"}, "tool_response": {"ok": True}}
        pf = Path(self.tmp.name) / "payload.json"
        pf.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(capture(["use-log", "--file", str(pf)]), "")  # silent by contract
        pf.write_text(json.dumps(dict(payload, tool_name="Bash", tool_input={"command": "ls"})), encoding="utf-8")
        self.assertEqual(capture(["use-log", "--file", str(pf)]), "")
        pf.write_text(json.dumps(dict(payload, tool_input={"command": "/anthropic-skills:docx a memo"})), encoding="utf-8")
        capture(["use-log", "--file", str(pf)])
        pf.write_text("not json", encoding="utf-8")
        self.assertEqual(capture(["use-log", "--file", str(pf)]), "")
        lines = (self.home / "uses.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(ln)["skill"] for ln in lines], ["evergreen-audit", "anthropic-skills:docx"])
        rec = json.loads(lines[0])
        self.assertEqual((rec["session_id"], rec["transcript_path"], rec["cwd"]), ("1234abcd-ef", "/x/t.jsonl", "/work"))
        self.assertTrue(rec["ts"].startswith(eg.today().isoformat()) and rec["env"])
        out = json.loads(capture(["uses", "--json", "--skill", "evergreen-audit"]))
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["uses"][0]["skill"], "evergreen-audit")
        text = capture(["uses"])
        self.assertIn("evergreen-audit", text)
        self.assertIn("session 1234abcd  transcript /x/t.jsonl  cwd /work", text)
        self.assertIn("-- 2 use(s)", text)
        self.assertEqual(json.loads(capture(["uses", "--json", "--days", "0", "--limit", "1"]))["uses"][0]["skill"], "anthropic-skills:docx")  # newest first
        self.assertEqual(es.where()["uses"]["lines"], 2)
        self.assertIn("uses    ", capture(["where"]))

    def test_audit_shows_test_flags_and_counts_failing_units(self):
        d = Path(self.tmp.name) / "aud"
        eg.main(["init", str(d), "--name", "aud", "--topic", "t", "--tier", "moderate", "--standalone", "--last-checked", "2026-09-01"])
        out = capture(["audit", "--roots", str(Path(self.tmp.name))])
        self.assertIn("[untested]", out)
        self.assertNotIn("failing tests", out)
        self.assertEqual(capture(["audit", "--brief", "--roots", str(Path(self.tmp.name))]), "")  # untested is not session-start news
        capture(["tested", str(d), "--passed", "4", "--failed", "2", "--failing", "action-1,decoy-2"])
        out = capture(["audit", "--roots", str(Path(self.tmp.name))])
        self.assertIn("[failing-tests:2]", out)
        self.assertIn("1 with failing tests", out)
        self.assertIn("[failing-tests:2]", capture(["audit", "--brief", "--roots", str(Path(self.tmp.name))]))
        js = json.loads(capture(["audit", "--json", "--roots", str(Path(self.tmp.name))]))
        unit = next(u for u in js["units"] if u["name"] == "aud")
        self.assertEqual(unit["tests"]["failing"], ["action-1", "decoy-2"])

    def test_frontmatter_angle_brackets_flagged(self):
        d = Path(self.tmp.name) / "fm"
        d.mkdir()
        (d / "SKILL.md").write_text('---\nname: fm\ndescription: "builds evergreen-<version>.zip"\n---\n# fm\n', encoding="utf-8")
        probs = eg.frontmatter_problems(d / "SKILL.md")
        self.assertEqual(len(probs), 1)
        (d / "SKILL.md").write_text('---\nname: fm\ndescription: "builds a versioned zip"\n---\n# fm <ok in body>\n', encoding="utf-8")
        self.assertEqual(eg.frontmatter_problems(d / "SKILL.md"), [])

    def test_plugin_own_unit_is_clean(self):
        root = eg.plugin_root()
        _, st = eg.load_state(root)
        self.assertEqual(eg.check_links(root, st), [])
        self.assertEqual([n for n in eg.lint(root, st) if "angle-bracket" in n], [])
        _, pst = eg.load_state(root / "profile")
        self.assertEqual(eg.check_links(root / "profile", pst), [])

    def test_pointer_mode_resolves_through_registry(self):
        eg.register(eg.plugin_root(), {"name": "evergreen", "kind": "plugin", "tier": "fast"})
        d = Path(self.tmp.name) / "ptr"
        eg.main(["init", str(d), "--name", "ptr", "--topic", "t", "--tier", "moderate", "--pointer"])
        _, st = eg.load_state(d)
        self.assertEqual(st["protocol"], "plugin")
        self.assertIsNotNone(eg.resolve_protocol(d, st))
        self.assertTrue((d / "MAINTENANCE.md").exists())
        self.assertIn("Finding the plugin", (d / "MAINTENANCE.md").read_text(encoding="utf-8"))
        self.assertEqual([p for p in eg.check_links(d, st) if "protocol" in p], [])
        self.assertEqual(eg.load_registry().get("plugin_root"), str(eg.plugin_root().resolve()))

    def test_qualified_cross_unit_ids_are_not_checked(self):
        self.assertEqual(eg.ID_RE.findall("see other-unit:L-003 and R-20260901-1"), ["R-20260901-1"])


import evergreen_sync as es  # noqa: E402


class Sync(unittest.TestCase):
    """Bundle, patch parsing and applying, entry union, state merge. Runs against a throwaway copy of the plugin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        os.environ["EVERGREEN_HOME"] = str(self.home)
        self.copy = Path(self.tmp.name) / "evergreen"
        src = eg.plugin_root()
        import shutil
        shutil.copytree(src, self.copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.zip", "*.plugin"))
        self._root = eg.plugin_root
        eg.plugin_root = lambda: self.copy  # point both modules at the copy

    def tearDown(self):
        eg.plugin_root = self._root
        os.environ.pop("EVERGREEN_HOME", None)
        self.tmp.cleanup()

    def test_unified_round_trip_and_blob_ids(self):
        base = b"a\nb\nc\n"
        new = b"a\nB\nc\nd\n"
        patch = es.unified("x/y.md", base, new)
        self.assertIn("diff --git a/x/y.md b/x/y.md", patch)
        self.assertIn(f"index {es.git_blob(base)[:12]}..{es.git_blob(new)[:12]}", patch)
        fp = es.parse_patch(patch)[0]
        merged, failed, _ = es.apply_hunks(base.decode().splitlines(), fp.hunks, fuzz=0)
        self.assertEqual(failed, [])
        self.assertEqual(merged, ["a", "B", "c", "d"])
        # git blob id matches git's own hashing convention
        self.assertEqual(es.git_blob(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_bundle_then_merge_into_diverged_trunk(self):
        es.take_baseline(note="test")
        self.assertIsNone(es.build_bundle())
        # remote edits: a new changelog entry, a learning, a skill edit, state, a new file
        cl = self.copy / "CHANGELOG.md"
        cl.write_text(cl.read_text(encoding="utf-8").replace("### C-20260902-2", "### C-20260909-1 · 2026-09-09 · Remote change\n- because: test\n- files: x\n- body\n\n### C-20260902-2", 1), encoding="utf-8")
        ln = self.copy / "LEARNINGS.md"
        ln.write_text(ln.read_text(encoding="utf-8").replace("## Active\n\n", "## Active\n\n### L-900 · 2026-09-09 · Remote lesson\n- Trigger: t\n- Hypothesis: h\n- Rule: r\n- Evidence: C-20260909-1\n- Scope: skill\n- Status: active · helpful 0 · harmful 0 · last_confirmed 2026-09-09\n\n", 1), encoding="utf-8")
        sk = self.copy / "skills" / "evergreen-audit" / "SKILL.md"
        sk.write_text(sk.read_text(encoding="utf-8").replace("One table, then action.", "One table, then action. (remote)"), encoding="utf-8")
        st = json.loads((self.copy / "evergreen.json").read_text(encoding="utf-8"))
        st["history"].append({"date": "2026-09-09", "m": 0.0, "interval_after": 21, "note": "remote check"})
        st["last_checked"] = "2026-09-12"
        (self.copy / "evergreen.json").write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
        (self.copy / "templates" / "NEW.template").write_text("new\n", encoding="utf-8")
        b = es.build_bundle()
        self.assertEqual(b["n"], 5)
        update = b["update"].read_text(encoding="utf-8")
        self.assertIn("C-20260909-1", update)
        self.assertIn("L-900", update)
        self.assertIn("last_checked: ", update)
        # a diverged trunk: same C- id with another title, and its own edit elsewhere in the same skill
        trunk = Path(self.tmp.name) / "trunk"
        import shutil
        shutil.copytree(self._root(), trunk, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.zip", "*.plugin"))
        tcl = trunk / "CHANGELOG.md"
        tcl.write_text(tcl.read_text(encoding="utf-8").replace("### C-20260902-2", "### C-20260909-1 · 2026-09-09 · Trunk change\n- because: t\n- files: y\n- other\n\n### C-20260902-2", 1), encoding="utf-8")
        tsk = trunk / "skills" / "evergreen-audit" / "SKILL.md"
        tsk.write_text(tsk.read_text(encoding="utf-8").replace("## Step 4: report", "## Step 4: report (trunk)"), encoding="utf-8")
        rep = es.merge(b["dir"], trunk=trunk, use_git=False)
        self.assertEqual(rep["conflicts"], [])
        self.assertEqual(rep["renamed"], {"C-20260909-1": "C-20260909-2"})
        self.assertTrue(any("added C-20260909-2" in u for u in rep["union"]))
        merged_cl = tcl.read_text(encoding="utf-8")
        self.assertIn("### C-20260909-2 · 2026-09-09 · Remote change", merged_cl)
        self.assertIn("### C-20260909-1 · 2026-09-09 · Trunk change", merged_cl)
        self.assertIn("Evidence: C-20260909-2", (trunk / "LEARNINGS.md").read_text(encoding="utf-8"))  # reference rewritten
        skt = tsk.read_text(encoding="utf-8")
        self.assertIn("(remote)", skt)
        self.assertIn("(trunk)", skt)
        tst = json.loads((trunk / "evergreen.json").read_text(encoding="utf-8"))
        self.assertEqual(tst["last_checked"], "2026-09-12")
        self.assertTrue(any(h.get("note") == "remote check" for h in tst["history"]))
        self.assertTrue((trunk / "templates" / "NEW.template").exists())
        # second merge is a no-op
        rep2 = es.merge(b["dir"], trunk=trunk, use_git=False)
        self.assertEqual(rep2["applied"] + rep2["union"] + rep2["conflicts"], [])

    def test_merge_from_saved_email_body(self):
        es.take_baseline(note="test")
        rd = self.copy / "README.md"
        rd.write_text(rd.read_text(encoding="utf-8").replace("# Evergreen\n", "# Evergreen\n\nRemote line.\n", 1), encoding="utf-8")
        b = es.build_bundle()
        cfg = es.notify_config()
        subject, body, atts = es.compose(b, cfg)
        self.assertIn(es.PATCH_BEGIN, body)
        self.assertEqual([a.name for a in atts], [f"evergreen-{eg.plugin_version()}-mail.zip", "changes.patch", "manifest.json", "UPDATE.md"])
        # the synced mirror carries the archive too, not just the digest and patch: it is what an agent attaches from
        mdir = Path(self.tmp.name) / "mirror"
        mdir.mkdir()
        cfg = dict(cfg, outbox_copy_to=str(mdir / "outbox"))
        dest = es.copy_to_outbox_mirror(b, cfg, extra=atts)
        self.assertIsNotNone(dest)
        mirrored = sorted(p.name for p in Path(dest).iterdir())
        self.assertEqual(mirrored, sorted([f"evergreen-{eg.plugin_version()}-mail.zip", "changes.patch", "manifest.json", "UPDATE.md"]))
        mail = Path(self.tmp.name) / "mail.txt"
        mail.write_text("Subject: " + subject + "\n\n" + body + "\n-- \nfooter\n", encoding="utf-8")
        trunk = Path(self.tmp.name) / "trunk2"
        import shutil
        shutil.copytree(self._root(), trunk, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.zip", "*.plugin"))
        rep = es.merge(mail, trunk=trunk, use_git=False)
        self.assertEqual(rep["conflicts"], [])
        self.assertIn("Remote line.", (trunk / "README.md").read_text(encoding="utf-8"))

    def test_notify_without_transport_leaves_unsent_bundle_and_dedupes(self):
        os.environ["EVERGREEN_UPDATE_TRANSPORT"] = "email"  # protocol 1.4 routes notify to git unless told otherwise
        self.addCleanup(os.environ.pop, "EVERGREEN_UPDATE_TRANSPORT", None)
        es.take_baseline(note="test")
        self.assertEqual(es.notify(if_changed=True), "")
        (self.copy / "README.md").write_text((self.copy / "README.md").read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        for k in ("EVERGREEN_SMTP_USER", "EVERGREEN_SMTP_PASS"):
            os.environ.pop(k, None)
        cfg = es.notify_config()
        cfg["transports"] = ["smtp"]
        orig = es.notify_config
        es.notify_config = lambda: cfg
        try:
            msg = es.notify()
            self.assertTrue(msg.startswith("unsent"))
            dirs = list((self.home / "outbox").iterdir())
            self.assertEqual(len(dirs), 1)
            self.assertTrue((dirs[0] / "STATUS").read_text(encoding="utf-8").startswith("unsent"))
            # the email carries the whole plugin (mail-safe zip built into the bundle) and opens with the install prompt
            self.assertTrue(any(p.name.endswith("-mail.zip") for p in dirs[0].iterdir()))
            subject, body, atts = es.compose(es.load_bundle(dirs[0]), cfg)
            self.assertIn("+ full plugin", subject)
            self.assertTrue(body.startswith("TO INSTALL OR UPGRADE"))
            self.assertIn("PASTE THE FOLDER PATH HERE", body)
            self.assertLess(body.index("PASTE THE FOLDER PATH HERE"), body.index("# Evergreen update"))
            self.assertTrue(atts[0].name.endswith("-mail.zip") and atts[-1].name == "UPDATE.md")
            cfg["attach_pack"] = False
            _, body2, atts2 = es.compose(es.load_bundle(dirs[0]), cfg)
            self.assertEqual([a.name for a in atts2], ["changes.patch", "manifest.json", "UPDATE.md"])
            self.assertIn("PASTE THE FOLDER PATH HERE", body2)
            cfg["attach_pack"] = True
            # same content again: the unsent bundle is reused, not duplicated
            es.notify()
            self.assertEqual(len(list((self.home / "outbox").iterdir())), 1)
            # an agent sends it and marks it; the baseline advances so the next diff is empty
            out = es.notify(mark_sent=dirs[0], via="gmail-mcp")
            self.assertIn("marked", out)
            self.assertIsNone(es.build_bundle())
            self.assertEqual(es.load_notify_state()["last"]["transport"], "gmail-mcp")
        finally:
            es.notify_config = orig

    def test_union_entries_and_state_merge(self):
        text = "# Log\n\n## Active\n\n### L-002 · d · two\n- Trigger: x\n\n### L-001 · d · one\n- Trigger: x\n"
        new, added, renamed = es.union_entries(text, [("L-002", ["### L-002 · d · different", "- Trigger: y", "- Evidence: L-002"]), ("L-001", ["### L-001 · d · one", "- Trigger: x"])], es.section_map(text))
        self.assertEqual(added, ["L-003"])
        self.assertEqual(renamed, {"L-002": "L-003"})
        self.assertIn("### L-003 · d · different\n- Trigger: y\n- Evidence: L-003", new)
        self.assertLess(new.index("### L-003"), new.index("### L-002"))  # newest first, inside the section
        s = es.merge_state({"last_checked": "2026-09-01", "next_due": "2026-09-15", "history": [{"date": "2026-09-01", "note": "a", "m": None}], "counts": {"changes": 6}},
                           {"last_checked": "2026-09-03", "next_due": "2026-09-17", "history": [{"date": "2026-09-01", "note": "a", "m": None}, {"date": "2026-09-03", "note": "b", "m": 0.1}], "counts": {"changes": 7, "learnings": 9}})
        self.assertEqual(s["next_due"], "2026-09-17")
        self.assertEqual(len(s["history"]), 2)
        self.assertEqual(s["counts"], {"changes": 7, "learnings": 9})

    def test_test_runs_travel_in_the_digest_and_union(self):
        # union: a clashing T- id is renumbered on the dated scheme, references inside the entry follow
        text = "# Tests\n\n## Runs\n\n### T-20260904-1 · 2026-09-04 · manual · trunk · 6/6\n- led to: none\n"
        new, added, renamed = es.union_entries(text, [("T-20260904-1", ["### T-20260904-1 · 2026-09-04 · manual · laptop · 5/6", "- action-1 · action · no-op · x", "- led to: C-20260904-1 (from T-20260904-1)"])], es.section_map(text))
        self.assertEqual((added, renamed), (["T-20260904-2"], {"T-20260904-1": "T-20260904-2"}))
        self.assertIn("### T-20260904-2 · 2026-09-04 · manual · laptop · 5/6\n- action-1 · action · no-op · x\n- led to: C-20260904-1 (from T-20260904-2)", new)
        self.assertLess(new.index("### T-20260904-2"), new.index("### T-20260904-1"))
        self.assertEqual(es.section_map(text), {"T": "## Runs"})
        # digest: a TESTS.md added at an install shows its runs under "New test runs"
        es.take_baseline(note="test")
        (self.copy / "TESTS.md").write_text("# Tests: evergreen\n\nREADME.md RESEARCH.md CHANGELOG.md LEARNINGS.md\n\n## Runs\n\n### T-20260815-1 · 2026-09-04 · manual · laptop · 5/6\n- action-1 · action · no-op · x\n- led to: none\n", encoding="utf-8")
        b = es.build_bundle()
        update = b["update"].read_text(encoding="utf-8")
        self.assertIn("## New test runs", update)
        self.assertIn("- T-20260815-1 · 2026-09-04 · manual · laptop · 5/6", update)
        # and survives a merge into a trunk that already has a different T-20260815-1
        trunk = self._trunk("trunk-tests")
        (trunk / "TESTS.md").write_text("# Tests: evergreen\n\nREADME.md RESEARCH.md CHANGELOG.md LEARNINGS.md\n\n## Runs\n\n### T-20260815-1 · 2026-09-04 · manual · trunk · 6/6\n- led to: none\n", encoding="utf-8")
        rep = es.merge(b["dir"], trunk=trunk, use_git=False)
        self.assertEqual(rep["conflicts"], [])
        merged = (trunk / "TESTS.md").read_text(encoding="utf-8")
        self.assertIn("### T-20260815-1 · 2026-09-04 · manual · trunk · 6/6", merged)
        self.assertIn("### T-20260815-2 · 2026-09-04 · manual · laptop · 5/6", merged)
        # state: the later suite run's block wins whole; files.tests added elsewhere reaches the trunk
        s = es.merge_state({"last_checked": "2026-09-01", "files": {"changelog": "CHANGELOG.md"}, "tests": {"last_run": "2026-09-01T10:00", "failing": ["a"]}},
                           {"last_checked": "2026-09-01", "files": {"changelog": "CHANGELOG.md", "tests": "TESTS.md"}, "tests": {"last_run": "2026-09-03T10:00", "failing": []}})
        self.assertEqual(s["tests"]["failing"], [])
        self.assertEqual(s["files"]["tests"], "TESTS.md")
        s = es.merge_state({"last_checked": "2026-09-01", "tests": {"last_run": "2026-09-05T10:00", "failing": ["a"]}}, {"last_checked": "2026-09-01", "tests": {"last_run": "2026-09-03T10:00", "failing": []}})
        self.assertEqual(s["tests"]["failing"], ["a"])
        self.assertEqual(es.state_delta(b"{}", b'{"tests": {"last_run": "2026-09-04T10:00", "passed": 5, "cases": 6, "failing": ["action-1"]}}'),
                         ["tests: last_run 2026-09-04T10:00 5/6 passed, failing ['action-1']"])

    def _trunk(self, name="trunk3"):
        trunk = Path(self.tmp.name) / name
        import shutil
        shutil.copytree(self._root(), trunk, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.zip", "*.plugin"))
        return trunk

    def test_hostile_patch_cannot_escape_or_change_config_or_code(self):
        trunk = self._trunk()
        hostile = (
            "diff --git a/../pwned.txt b/../pwned.txt\nnew file mode 100644\nindex 000000000000..aaaaaaaaaaaa\n--- /dev/null\n+++ b/../pwned.txt\n@@ -0,0 +1 @@\n+x\n"
            "diff --git a/.git/hooks/post-checkout b/.git/hooks/post-checkout\nnew file mode 100644\nindex 000000000000..aaaaaaaaaaaa\n--- /dev/null\n+++ b/.git/hooks/post-checkout\n@@ -0,0 +1 @@\n+x\n"
            "diff --git a//tmp/abs.txt b//tmp/abs.txt\nnew file mode 100644\nindex 000000000000..aaaaaaaaaaaa\n--- /dev/null\n+++ b//tmp/abs.txt\n@@ -0,0 +1 @@\n+x\n"
            "diff --git a/evergreen.config.json b/evergreen.config.json\nindex 111111111111..222222222222 100644\n--- a/evergreen.config.json\n+++ b/evergreen.config.json\n@@ -7,3 +7,3 @@\n   \"notify\": {\n     \"auto\": true,\n-    \"to\": \"owner@example.com\",\n+    \"to\": \"attacker@example.com\",\n"
            "diff --git a/scripts/evil.py b/scripts/evil.py\nnew file mode 100644\nindex 000000000000..aaaaaaaaaaaa\n--- /dev/null\n+++ b/scripts/evil.py\n@@ -0,0 +1 @@\n+import os\n"
        )
        pf = Path(self.tmp.name) / "hostile.patch"
        pf.write_text(hostile, encoding="utf-8")
        rep = es.merge(pf, trunk=trunk, use_git=False)
        self.assertFalse((Path(self.tmp.name) / "pwned.txt").exists())
        self.assertFalse((trunk / ".git" / "hooks" / "post-checkout").exists())
        self.assertFalse(Path("/tmp/abs.txt").exists() and "abs" in rep["applied"])
        self.assertEqual(len([s for s in rep["skipped"] if "unsafe path" in s]), 3)
        self.assertIn("owner@example.com", (trunk / "evergreen.config.json").read_text(encoding="utf-8"))
        self.assertTrue(any("protected" in c for c in rep["conflicts"]))
        self.assertFalse((trunk / "scripts" / "evil.py").exists())
        self.assertTrue(any("CODE CHANGED" in c for c in rep["conflicts"]))
        self.assertEqual(rep["applied"], [])

    def test_edge_insertion_is_idempotent_on_diverged_file(self):
        es.take_baseline(note="test")
        snip = self.copy / "templates" / "AGENTS.md.snippet"
        snip.write_text(snip.read_text(encoding="utf-8") + "Appended by remote.\n", encoding="utf-8")
        b = es.build_bundle()
        trunk = self._trunk("trunk4")
        ts = trunk / "templates" / "AGENTS.md.snippet"
        ts.write_text("Trunk line first.\n" + ts.read_text(encoding="utf-8"), encoding="utf-8")
        es.merge(b["dir"], trunk=trunk, use_git=False)
        es.merge(b["dir"], trunk=trunk, use_git=False)
        self.assertEqual(ts.read_text(encoding="utf-8").count("Appended by remote."), 1)

    def test_renumbering_is_per_unit(self):
        es.take_baseline(note="test")
        for rel in ("CHANGELOG.md", "profile/CHANGELOG.md"):
            f = self.copy / rel
            t = f.read_text(encoding="utf-8")
            i = t.index("\n### C-2026") + 1
            f.write_text(t[:i] + f"### C-20260810-1 · 2026-08-10 · Remote {rel}\n- because: t\n- files: x\n- body\n\n" + t[i:], encoding="utf-8")
        b = es.build_bundle()
        trunk = self._trunk("trunk5")
        tcl = trunk / "CHANGELOG.md"  # only the plugin unit clashes
        t = tcl.read_text(encoding="utf-8")
        i = t.index("\n### C-2026") + 1
        tcl.write_text(t[:i] + "### C-20260810-1 · 2026-08-10 · Trunk change\n- because: t\n- files: y\n- z\n\n" + t[i:], encoding="utf-8")
        rep = es.merge(b["dir"], trunk=trunk, use_git=False)
        self.assertEqual(rep["renamed"], {"C-20260810-1": "C-20260810-2"})
        self.assertIn("### C-20260810-2 · 2026-08-10 · Remote CHANGELOG.md", tcl.read_text(encoding="utf-8"))
        self.assertIn("### C-20260810-1 · 2026-08-10 · Remote profile/CHANGELOG.md", (trunk / "profile" / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_mark_sent_advances_baseline_to_the_bundle_not_the_tree(self):
        es.take_baseline(note="test")
        rd = self.copy / "README.md"
        rd.write_text(rd.read_text(encoding="utf-8") + "\nfirst\n", encoding="utf-8")
        b = es.build_bundle()
        rd.write_text(rd.read_text(encoding="utf-8") + "second\n", encoding="utf-8")  # edited after the bundle
        es.notify(mark_sent=b["dir"], via="test")
        b2 = es.build_bundle()
        self.assertIsNotNone(b2)
        patch = b2["patch"].read_text(encoding="utf-8")
        self.assertIn("+second", patch)
        self.assertNotIn("+first", patch)

    def test_hook_path_is_quiet_on_the_trunk_and_when_auto_is_off(self):
        es.take_baseline(note="test")
        (self.copy / "README.md").write_text((self.copy / "README.md").read_text(encoding="utf-8") + "\nchange\n", encoding="utf-8")
        st = json.loads((self.copy / "evergreen.json").read_text(encoding="utf-8"))
        st["source"] = str(self.copy.resolve())
        (self.copy / "evergreen.json").write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(es.is_trunk())
        self.assertEqual(es.notify(if_changed=True, from_hook=True), "")
        cfg = es.notify_config()
        cfg["auto"] = False
        orig = es.notify_config
        es.notify_config = lambda: cfg
        try:
            self.assertEqual(es.notify(if_changed=True), "")
        finally:
            es.notify_config = orig
        self.assertTrue(es.safe_rel("skills/x/SKILL.md"))
        for bad in ("../x", "/etc/x", "C:/x", ".git/config", "a/../b", "a//b", ".gitattributes/../x"):
            self.assertFalse(es.safe_rel(bad), bad)

    def test_parse_patch_survives_stripped_blank_context(self):
        patch = "diff --git a/f.md b/f.md\nindex 1..2 100644\n--- a/f.md\n+++ b/f.md\n@@ -1,3 +1,4 @@\n a\n\n+new\n b\n"
        fp = es.parse_patch(patch)[0]
        self.assertEqual(fp.hunks[0].lines, [(" ", "a"), (" ", ""), ("+", "new"), (" ", "b")])
        merged, failed, _ = es.apply_hunks(["a", "", "b"], fp.hunks)
        self.assertEqual((merged, failed), (["a", "", "new", "b"], []))



class GitTransport(unittest.TestCase):
    """publish and pull against a bare repository standing in for the host (protocol 1.4)."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home = t / "home"
        os.environ["EVERGREEN_HOME"] = str(self.home)
        os.environ["EVERGREEN_ENV"] = "test-env"
        self.bare = t / "trunk.git"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=master", str(self.bare)], check=True)
        seed = t / "seed"
        shutil.copytree(eg.plugin_root(), seed, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "*.zip", "*.plugin"))
        self._g(seed, "init", "-q", "--initial-branch=master")
        self._g(seed, "add", "-A"); self._g(seed, "commit", "-q", "-m", "seed")
        self._g(seed, "remote", "add", "origin", str(self.bare)); self._g(seed, "push", "-q", "origin", "master")
        self.clone = t / "evergreen"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.clone)], check=True)
        self._g(self.clone, "config", "user.name", "Test"); self._g(self.clone, "config", "user.email", "t@example.com")
        self._root = eg.plugin_root
        eg.plugin_root = lambda: self.clone
        self._cfg = es.git_config
        self.cfg = dict(es.GIT_DEFAULTS, role="auto", pr=False)
        es.git_config = lambda: self.cfg

    def tearDown(self):
        eg.plugin_root = self._root
        es.git_config = self._cfg
        for k in ("EVERGREEN_HOME", "EVERGREEN_ENV"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    @staticmethod
    def _g(cwd, *args):
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True)
        return r.stdout.strip()

    def _edit(self):
        p = self.clone / "LEARNINGS.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n### L-901 · 2026-09-13 · Git transport lesson\n- Trigger: test\n- Hypothesis: test\n", encoding="utf-8")

    def test_publish_nothing_then_push_as_maintainer(self):
        self.assertEqual(es.publish(if_changed=True), "")
        self.assertIn("nothing to publish", es.publish())
        self._edit()
        msg = es.publish(dry_run=True)
        self.assertIn("as maintainer", msg)
        self.assertIn("L-901", msg)
        msg = es.publish()
        self.assertTrue(msg.startswith("pushed"), msg)
        self.assertIn("origin/master as maintainer", msg)
        self.assertIn("L-901", self._g(self.bare, "log", "-1", "--format=%s", "master"))
        self.assertEqual(self._g(self.clone, "status", "--porcelain"), "")
        self.assertTrue((self.home / "publish.json").exists())
        self.assertIn("already up to date", es.pull())

    def test_publish_as_contributor_uses_update_branch(self):
        self.cfg["role"] = "contributor"
        self._edit()
        msg = es.publish()
        self.assertTrue(msg.startswith("pushed"), msg)
        branch = self._g(self.clone, "rev-parse", "--abbrev-ref", "HEAD")
        self.assertTrue(branch.startswith("update/test-env-"), branch)
        self.assertIn(branch, self._g(self.bare, "branch", "--list", "update/*"))
        self.assertNotIn("L-901", self._g(self.bare, "log", "-1", "--format=%s", "master"))
        # a second change while the PR is open lands on the same branch
        self._edit()
        msg2 = es.publish()
        self.assertIn(branch, msg2)
        # pull refuses until the branch is merged, then switches back
        self.assertIn("not yet merged", es.pull())
        self._g(self.bare, "update-ref", "refs/heads/master", self._g(self.bare, "rev-parse", branch))
        self.assertIn("back on master", es.pull())
        self.assertEqual(self._g(self.clone, "rev-parse", "--abbrev-ref", "HEAD"), "master")

    def test_maintainer_behind_the_trunk_rebases_first(self):
        other = Path(self.tmp.name) / "other"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(other)], check=True)
        self._g(other, "config", "user.name", "O"); self._g(other, "config", "user.email", "o@example.com")
        (other / "README.md").write_text((other / "README.md").read_text(encoding="utf-8") + "\nremote line\n", encoding="utf-8")
        self._g(other, "commit", "-q", "-am", "remote change"); self._g(other, "push", "-q", "origin", "master")
        self._edit()
        msg = es.publish()
        self.assertTrue(msg.startswith("pushed"), msg)
        self.assertIn("origin/master", msg)
        log = self._g(self.bare, "log", "--format=%s", "master")
        self.assertIn("remote change", log); self.assertIn("L-901", log)


if __name__ == "__main__":
    unittest.main(verbosity=1)
