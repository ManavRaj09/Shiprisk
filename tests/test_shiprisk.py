import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta

from shiprisk.backtest import auc, backtest
from shiprisk.gitlog import load_history, rev_list
from shiprisk.hotspots import find_hotspots
from shiprisk.model import score_history
from shiprisk.report import render


def make_commit(repo, files, msg, when, who="Dev One", email="dev1@example.com"):
    for path, content in files.items():
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    env = dict(os.environ, GIT_AUTHOR_NAME=who, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=who,
               GIT_COMMITTER_EMAIL=email, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", msg], check=True, capture_output=True, env=env)


class ShipRiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = cls.tmp.name
        subprocess.run(["git", "init", "-q", cls.repo], check=True)
        start = datetime(2026, 1, 5, 10)  # a Monday
        for i in range(40):
            msg = f"fix: handle edge case {i}" if i % 4 == 3 else f"feat: tweak core {i}"
            make_commit(cls.repo, {"src/core.py": "\n".join(f"line {j} v{i}" for j in range(10 + i))},
                        msg, start + timedelta(days=i))
        # risky: new author, Friday 23:00, big, sensitive paths, urgent subject, no tests
        cls.risky_when = datetime(2026, 2, 20, 23)
        make_commit(cls.repo, {
            "auth/login.py": "\n".join(f"x{j}" for j in range(500)),
            "migrations/001.sql": "\n".join(f"y{j}" for j in range(40)),
        }, "hotfix: rewrite login", cls.risky_when, who="New Dev", email="new@example.com")
        make_commit(cls.repo, {"README.md": "hello\n"}, "docs: readme", datetime(2026, 2, 21, 11))
        cls.commits = load_history(cls.repo)
        cls.assessed = score_history(cls.commits)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_history_is_loaded_oldest_first(self):
        self.assertEqual(len(self.commits), 42)
        self.assertEqual(self.commits[0].subject, "feat: tweak core 0")
        self.assertEqual(self.commits[-2].subject, "hotfix: rewrite login")
        self.assertEqual(self.commits[-2].weekday, 4)
        self.assertEqual(self.commits[-2].hour, 23)

    def test_risky_commit_is_high(self):
        risky = self.assessed[-2]
        self.assertGreaterEqual(risky.score, 55, risky.reasons)
        self.assertEqual(risky.band, "HIGH")
        self.assertTrue(any("sensitive" in r for r in risky.reasons))

    def test_docs_only_commit_is_low(self):
        self.assertLess(self.assessed[-1].score, 30)

    def test_risky_outranks_normal_commits(self):
        normal = max(a.score for a in self.assessed[10:40])
        self.assertGreater(self.assessed[-2].score, normal)

    def test_scores_do_not_peek_at_future(self):
        # Re-scoring only the first 20 commits must give identical scores.
        head = score_history(self.commits[:20])
        self.assertEqual([a.score for a in head], [a.score for a in self.assessed[:20]])

    def test_hotspots_flag_single_owner(self):
        rows = find_hotspots(self.commits)
        self.assertEqual(rows[0]["path"], "src/core.py")
        self.assertTrue(rows[0]["bus_factor_1"])

    def test_backtest_runs(self):
        bt = backtest(self.commits, self.assessed, 14)
        self.assertGreater(bt["n"], 0)
        self.assertTrue(bt["auc"] is None or 0 <= bt["auc"] <= 1)

    def test_auc_known_values(self):
        self.assertEqual(auc([1, 2, 3, 4], [False, False, True, True]), 1.0)
        self.assertEqual(auc([4, 3, 2, 1], [False, False, True, True]), 0.0)
        self.assertEqual(auc([1, 1, 1, 1], [False, True, False, True]), 0.5)
        self.assertIsNone(auc([1, 2], [True, True]))

    def test_rev_list_range(self):
        shas = rev_list(self.repo, "HEAD~2..HEAD")
        self.assertEqual(len(shas), 2)

    def test_report_escapes_untrusted_text(self):
        evil = self.assessed[-2]  # the riskiest commit, so it is shown in the report
        original = evil.commit.subject
        evil.commit.subject = "<script>alert(1)</script>"
        try:
            html = render("demo", self.assessed, find_hotspots(self.commits), backtest(self.commits, self.assessed))
        finally:
            evil.commit.subject = original
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
