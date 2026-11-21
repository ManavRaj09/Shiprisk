"""Files that are risky to touch: changing often, breaking often, understood by one person."""
from __future__ import annotations

from typing import Dict, List

from .gitlog import Commit
from .model import History, is_code


def find_hotspots(commits: List[Commit], top: int = 15) -> List[Dict]:
    if not commits:
        return []
    h = History()
    for c in commits:
        h.update(c)
    now = commits[-1].ts
    names = {c.email: c.author for c in commits}
    rows = []
    for path, n in h.file_commits.items():
        if n < 3 or not is_code(path):
            continue
        recent = h.churn(path, now)
        fix_ratio = h.file_fixes[path] / n
        owner, owner_n = h.file_authors[path].most_common(1)[0]
        share = owner_n / n
        bus1 = n >= 5 and share >= 0.8
        risk = (0.4 * min(1, recent / 10) + 0.3 * min(1, fix_ratio / 0.5)
                + 0.3 * (max(0, share - 0.5) / 0.5 if n >= 5 else 0))
        rows.append({
            "path": path, "commits": n, "recent": recent, "fix_ratio": round(fix_ratio, 2),
            "owner": names.get(owner, owner), "owner_share": round(share, 2), "bus_factor_1": bus1,
            "risk": round(risk * 100),
        })
    rows.sort(key=lambda r: (r["risk"], r["commits"]), reverse=True)
    return rows[:top]
