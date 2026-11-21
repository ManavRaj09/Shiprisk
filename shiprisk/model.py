"""The risk model.

Every commit is scored 0-100 from eight signals. Signals only use history that
existed *before* the commit, so scoring a commit never peeks at its future.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from statistics import mean
from typing import Deque, Dict, List

from .gitlog import Commit

FIX_RE = re.compile(r"\b(fix(e[sd])?|bug(fix)?|hotfix|revert(ed)?|patch|regression|crash|broken)\b", re.I)
URGENT_RE = re.compile(r"\b(hotfix|urgent|emergency|asap|wip|hack|temp(orary)?)\b", re.I)
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|e2e)(/|$)|(^|/)test_[^/]*$|[_.-](test|spec)\.[^/]+$", re.I)
DOC_RE = re.compile(r"\.(md|rst|txt|adoc)$|(^|/)(docs?|documentation)/|(^|/)(LICENSE|CHANGELOG|README)[^/]*$", re.I)
NOISE_RE = re.compile(
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|Pipfile\.lock|go\.sum"
    r"|\.min\.(js|css)|\.snap|\.svg|\.png|\.jpe?g|\.gif|\.map)$", re.I)
SENSITIVE_RE = re.compile(
    r"(^|/)(migrations?|auth\w*|security|payments?|billing|secrets?|terraform|k8s|helm|infra)(/|$)"
    r"|(^|/)(Dockerfile[^/]*|docker-compose[^/]*|\.env[^/]*|requirements[^/]*\.txt|package\.json"
    r"|pyproject\.toml|pom\.xml|build\.gradle|go\.mod|Cargo\.toml)$"
    r"|(^|/)\.github/workflows/|\.tf$", re.I)

WEIGHTS: Dict[str, int] = {
    "size": 20, "spread": 10, "hotspot": 15, "bug_history": 15,
    "unfamiliar": 15, "timing": 5, "no_tests": 10, "sensitive": 10,
}
LOW_MAX, MEDIUM_MAX = 30, 55  # score < 30 LOW, < 55 MEDIUM, else HIGH


def band_of(score: int) -> str:
    return "LOW" if score < LOW_MAX else "MEDIUM" if score < MEDIUM_MAX else "HIGH"


def is_code(path: str) -> bool:
    return not (NOISE_RE.search(path) or DOC_RE.search(path) or TEST_RE.search(path))


@dataclass
class Factor:
    key: str
    weight: int
    value: float  # 0..1
    detail: str

    @property
    def points(self) -> float:
        return self.weight * self.value


@dataclass
class Assessment:
    commit: Commit
    score: int
    band: str
    factors: List[Factor] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


class History:
    """Rolling knowledge about files and authors, updated one commit at a time."""

    def __init__(self, window_days: int = 90):
        self.window = window_days * 86400
        self.file_commits: Dict[str, int] = defaultdict(int)
        self.file_fixes: Dict[str, int] = defaultdict(int)
        self.file_authors: Dict[str, Counter] = defaultdict(Counter)
        self.file_recent: Dict[str, Deque[int]] = defaultdict(deque)
        self.author_commits: Counter = Counter()

    def churn(self, path: str, now: int) -> int:
        dq = self.file_recent[path]
        while dq and dq[0] < now - self.window:
            dq.popleft()
        return len(dq)

    def update(self, c: Commit) -> None:
        fix = bool(FIX_RE.search(c.subject))
        for path, _, _ in c.files:
            self.file_commits[path] += 1
            if fix:
                self.file_fixes[path] += 1
            self.file_authors[path][c.email] += 1
            self.file_recent[path].append(c.ts)
        self.author_commits[c.email] += 1


def assess(h: History, c: Commit) -> Assessment:
    real = [(p, a, d) for p, a, d in c.files if not NOISE_RE.search(p)]
    code = [(p, a, d) for p, a, d in real if is_code(p)]
    code_paths = [p for p, _, _ in code]
    tests_touched = any(TEST_RE.search(p) for p, _, _ in real)
    lines = sum(a + d for _, a, d in real)
    code_lines = sum(a + d for _, a, d in code)
    f: Dict[str, Factor] = {}

    def put(key: str, value: float, detail: str = "") -> None:
        f[key] = Factor(key, WEIGHTS[key], max(0.0, min(1.0, value)), detail)

    put("size", math.log1p(lines) / math.log1p(800), f"{lines} lines changed across {len(real)} file{'s' if len(real) != 1 else ''}")

    dirs = {os.path.dirname(p) for p, _, _ in real}
    put("spread", (len(dirs) - 1) / 5 if dirs else 0, f"spans {len(dirs)} director{'ies' if len(dirs) != 1 else 'y'}")

    if code_paths:
        churns = {p: h.churn(p, c.ts) for p in code_paths}
        worst = max(churns, key=churns.get)
        put("hotspot", mean(min(1, n / 10) for n in churns.values()),
            f"{worst} was already changed {churns[worst]}x in the last 90 days")
    else:
        put("hotspot", 0)

    eligible = {p: h.file_fixes[p] / h.file_commits[p] for p in code_paths if h.file_commits[p] >= 3}
    if eligible:
        worst = max(eligible, key=eligible.get)
        put("bug_history", mean(min(1, r / 0.5) for r in eligible.values()),
            f"{int(eligible[worst] * 100)}% of past changes to {worst} were fixes")
    else:
        put("bug_history", 0)

    if code_paths:
        vals, never, rare = [], [], []
        for p in code_paths:
            n = h.file_commits[p]
            mine = h.file_authors[p][c.email]
            if n == 0:
                vals.append(0.15)  # brand-new file: nobody knows it yet, but nothing to break
            elif mine == 0:
                vals.append(1.0)
                never.append(p)
            elif mine == 1:
                vals.append(0.6)
                rare.append(p)
            else:
                vals.append(0.1 if mine / n >= 0.15 else 0.3)
        value = mean(vals)
        if never:
            detail = (f"{c.author} has never changed {len(never)} of {len(code_paths)} source files "
                      f"before (e.g. {never[0]})")
        elif rare:
            detail = f"{c.author} has changed {rare[0]} only once before"
        else:
            detail = ""
        n_prev = h.author_commits[c.email]
        if n_prev < 5:
            value = max(value, 0.6)
            detail = (f"{c.author} is new to this repo (first commit)" if n_prev == 0
                      else f"{c.author} has only {n_prev} earlier commit{'s' if n_prev != 1 else ''} in this repo")
        put("unfamiliar", value, detail)
    else:
        put("unfamiliar", 0)

    timing, why = 0.0, ""
    if c.weekday >= 5 and 0.6 > timing:
        timing, why = 0.6, "committed on a weekend"
    if (c.hour >= 22 or c.hour < 6) and 0.8 > timing:
        timing, why = 0.8, f"committed late at night ({c.hour:02d}:00 local)"
    if c.weekday == 4 and c.hour >= 16 and 0.7 > timing:
        timing, why = 0.7, "committed on Friday evening"
    put("timing", timing, why)

    if code and not tests_touched and code_lines >= 20:
        put("no_tests", min(1, code_lines / 150), f"{code_lines} source lines changed and no test file touched")
    else:
        put("no_tests", 0)

    sens = [p for p, _, _ in real if SENSITIVE_RE.search(p)]
    put("sensitive", min(1, 0.7 + 0.15 * (len(sens) - 1)) if sens else 0,
        "touches sensitive paths: " + ", ".join(sens[:3]))

    raw = sum(x.points for x in f.values())
    mult = 1.0
    if real and not code:
        mult = 0.5 if tests_touched else 0.2  # test-only or docs-only changes
    bonus = 8 if URGENT_RE.search(c.subject) else 0
    score = int(round(min(100, raw * mult + bonus)))
    if not c.files:
        score = 0

    factors = sorted(f.values(), key=lambda x: x.points, reverse=True)
    reasons = [x.detail for x in factors if x.value >= 0.5 and x.detail][:4]
    if bonus:
        reasons.append("subject signals urgency (hotfix/wip/hack)")
    if not reasons:
        reasons = ["no strong risk signals"]
    return Assessment(c, score, band_of(score), factors, reasons)


def score_history(commits: List[Commit]) -> List[Assessment]:
    h, out = History(), []
    for c in commits:
        out.append(assess(h, c))
        h.update(c)  # learn from the commit only after scoring it
    return out
