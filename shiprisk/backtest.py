"""Does the model actually fit *this* repository?

A commit counts as "followed by trouble" if a later commit whose subject looks like a fix
touches one of the same source files within the horizon. We then check whether higher scores
line up with that outcome. AUC 0.5 is a coin flip, 1.0 is perfect.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from typing import Dict, List, Optional

from .gitlog import Commit
from .model import FIX_RE, Assessment, is_code


def auc(scores: List[float], labels: List[bool]) -> Optional[float]:
    pairs = sorted(zip(scores, labels))
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1  # average rank for ties
        i = j + 1
    pos = sum(1 for _, y in pairs if y)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return None
    rank_sum = sum(r for r, (_, y) in zip(ranks, pairs) if y)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def backtest(commits: List[Commit], assessments: List[Assessment], horizon_days: int = 14) -> Dict:
    fixes = defaultdict(list)  # path -> indexes of fix commits, ascending
    for i, c in enumerate(commits):
        if FIX_RE.search(c.subject):
            for p, _, _ in c.files:
                fixes[p].append(i)
    horizon = horizon_days * 86400
    last_ts = commits[-1].ts if commits else 0
    rows = []
    for i, (c, a) in enumerate(zip(commits, assessments)):
        if c.ts + horizon > last_ts:
            continue  # follow-up window not finished yet
        paths = [p for p, _, _ in c.files if is_code(p)]
        if not paths:
            continue
        hit = False
        for p in paths:
            lst = fixes.get(p)
            if not lst:
                continue
            k = bisect_right(lst, i)
            if k < len(lst) and commits[lst[k]].ts <= c.ts + horizon:
                hit = True
                break
        rows.append((a.score, a.band, hit))
    n = len(rows)
    pos = sum(1 for r in rows if r[2])
    by_band = {}
    for band in ("LOW", "MEDIUM", "HIGH"):
        sel = [r for r in rows if r[1] == band]
        by_band[band] = {"n": len(sel), "rate": (sum(1 for r in sel if r[2]) / len(sel)) if sel else None}
    return {
        "horizon_days": horizon_days, "n": n, "followed_by_fix": pos,
        "base_rate": (pos / n) if n else None, "by_band": by_band,
        "auc": auc([r[0] for r in rows], [r[2] for r in rows]),
    }
