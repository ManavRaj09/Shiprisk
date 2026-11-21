from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from statistics import median
from typing import List, Optional

from . import __version__
from .backtest import backtest
from .gitlog import GitError, load_history, repo_name, rev_list
from .hotspots import find_hotspots
from .model import Assessment, score_history
from .report import render

COMMANDS = ("scan", "check", "hotspots", "backtest")
COLORS = {"LOW": "\033[90m", "MEDIUM": "\033[33m", "HIGH": "\033[31;1m"}


def _paint(text: str, band: str) -> str:
    return f"{COLORS[band]}{text}\033[0m" if sys.stdout.isatty() else text


def _line(a: Assessment) -> str:
    tag = _paint(f"{a.score:>3} {a.band:<6}", a.band)
    return f"{tag}  {a.commit.short}  {a.commit.author[:18]:<18}  {a.commit.subject[:70]}"


def _as_dict(a: Assessment) -> dict:
    return {
        "sha": a.commit.sha, "author": a.commit.author, "subject": a.commit.subject,
        "score": a.score, "band": a.band, "reasons": a.reasons,
        "factors": {f.key: round(f.value, 2) for f in a.factors},
    }


def cmd_scan(args) -> int:
    commits = load_history(args.path, max_commits=args.history)
    assessed = score_history(commits)
    recent = assessed[-args.last:] if args.last else assessed
    if not recent:
        print("No commits found.")
        return 0
    bands = Counter(a.band for a in recent)
    print(f"Scored {len(recent)} commits | median {int(median(a.score for a in recent))} | "
          f"HIGH {bands['HIGH']}  MEDIUM {bands['MEDIUM']}  LOW {bands['LOW']}\n")
    print(f"Top {args.top} riskiest:")
    for a in sorted(recent, key=lambda a: a.score, reverse=True)[:args.top]:
        print(_line(a))
        print(f"{'':14}{'; '.join(a.reasons)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([_as_dict(a) for a in recent], fh, indent=2)
        print(f"\nWrote {args.json}")
    if args.html:
        bt = backtest(commits, assessed, args.horizon)
        page = render(repo_name(args.path), recent, find_hotspots(commits, 15), bt, args.top)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(page)
        print(f"\nWrote {args.html}")
    return 0


def cmd_check(args) -> int:
    shas = rev_list(args.path, args.range)
    if not shas:
        print("No commits in range, nothing to check.")
        return 0
    mine = [a for a in score_history(load_history(args.path, max_commits=args.history)) if a.commit.sha in shas]
    mine.sort(key=lambda a: a.score, reverse=True)
    worst = mine[0].score if mine else 0
    failed = worst >= args.fail_above
    if args.markdown:
        print(f"### ShipRisk: {'review carefully' if failed else 'looks fine'}\n")
        print(f"Highest score **{worst}** across {len(mine)} commits (fails at {args.fail_above}).\n")
        print("| Score | Commit | Why |\n|---|---|---|")
        for a in mine[:10]:
            why = "; ".join(a.reasons).replace("|", "/")
            print(f"| {a.score} {a.band} | `{a.commit.short}` {a.commit.subject[:60].replace('|', '/')} | {why} |")
    else:
        for a in mine:
            print(_line(a))
        print(f"\nHighest score {worst}; threshold {args.fail_above}: {'FAIL' if failed else 'ok'}")
    return 1 if failed else 0


def cmd_hotspots(args) -> int:
    rows = find_hotspots(load_history(args.path, max_commits=args.history), args.top)
    if not rows:
        print("Not enough history for hotspots (files need 3+ commits).")
        return 0
    print(f"{'risk':>4}  {'commits':>7}  {'90d':>4}  {'fixes':>5}  file / main author")
    for r in rows:
        flag = "  [single point of knowledge]" if r["bus_factor_1"] else ""
        print(f"{r['risk']:>4}  {r['commits']:>7}  {r['recent']:>4}  {round(r['fix_ratio'] * 100):>4}%  "
              f"{r['path']}  ({r['owner']} {round(r['owner_share'] * 100)}%){flag}")
    return 0


def cmd_backtest(args) -> int:
    commits = load_history(args.path, max_commits=args.history)
    bt = backtest(commits, score_history(commits), args.horizon)
    if not bt["n"]:
        print("Not enough history: needs commits older than the follow-up window.")
        return 0
    pct = lambda x: "n/a" if x is None else f"{x * 100:.0f}%"
    print(f"{bt['n']} commits with a full {bt['horizon_days']}-day follow-up; "
          f"{pct(bt['base_rate'])} were followed by a fix to the same files.")
    for band in ("HIGH", "MEDIUM", "LOW"):
        b = bt["by_band"][band]
        print(f"  {band:<6} {pct(b['rate']):>4}  (n={b['n']})")
    print("AUC:", "n/a" if bt["auc"] is None else f"{bt['auc']:.2f}", "(0.50 = coin flip, 1.00 = perfect)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shiprisk", description="Score commits for release risk using git history.")
    p.add_argument("--version", action="version", version=f"shiprisk {__version__}")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("path", nargs="?", default=".", help="path to a git repository (default: .)")
        sp.add_argument("--history", type=int, default=5000, help="max commits of history to read")

    s = sub.add_parser("scan", help="score recent commits")
    common(s)
    s.add_argument("--last", type=int, default=200, help="score only the latest N commits (0 = all)")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--html", metavar="FILE", help="write a self-contained HTML report")
    s.add_argument("--json", metavar="FILE", help="write scores as JSON")
    s.add_argument("--horizon", type=int, default=14, help="backtest follow-up window in days")
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("check", help="score a range (for CI); exit 1 if too risky")
    common(c)
    c.add_argument("--range", required=True, help="e.g. origin/main..HEAD")
    c.add_argument("--fail-above", type=int, default=75, help="fail when any commit scores at least this")
    c.add_argument("--markdown", action="store_true", help="print a PR-comment friendly table")
    c.set_defaults(func=cmd_check)

    h = sub.add_parser("hotspots", help="list risky files")
    common(h)
    h.add_argument("--top", type=int, default=15)
    h.set_defaults(func=cmd_hotspots)

    b = sub.add_parser("backtest", help="measure how well scores predict follow-up fixes")
    common(b)
    b.add_argument("--horizon", type=int, default=14)
    b.set_defaults(func=cmd_backtest)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv = ["scan"] + argv
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GitError as e:
        print(f"shiprisk: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
