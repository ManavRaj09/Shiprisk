"""Read commit history from a local git repository (standard library only)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set, Tuple

RS, FS = "\x1e", "\x1f"


class GitError(RuntimeError):
    """Raised when git is missing, the path is not a repo, or a command fails."""


@dataclass
class Commit:
    sha: str
    author: str
    email: str
    ts: int  # unix seconds
    hour: int  # author-local hour, 0-23
    weekday: int  # author-local weekday, Monday=0
    subject: str
    files: List[Tuple[str, int, int]] = field(default_factory=list)  # path, added, deleted

    @property
    def short(self) -> str:
        return self.sha[:7]


def _git(repo: str, *args: str) -> str:
    cmd = ["git", "-C", repo, "-c", "core.quotepath=off", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        raise GitError("git is not installed or not on PATH") from e
    if p.returncode != 0:
        msg = p.stderr.strip() or "git command failed"
        if any(k in msg for k in ("does not have any commits", "bad default revision", "unknown revision")) and "HEAD" in msg:
            msg = "this repository has no commits yet"
        raise GitError(msg)
    return p.stdout


def load_history(repo: str = ".", rev: str = "HEAD", max_commits: Optional[int] = 5000) -> List[Commit]:
    """Return non-merge commits, oldest first, each with per-file line counts."""
    args = [
        "log", rev, "--no-merges", "--no-renames", "--numstat", "--reverse",
        f"--format=%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%s",
    ]
    if max_commits:
        args.insert(2, f"--max-count={max_commits}")
    out = _git(repo, *args)
    commits: List[Commit] = []
    for chunk in out.split(RS)[1:]:
        head, _, body = chunk.partition("\n")
        parts = head.split(FS)
        if len(parts) < 5:
            continue
        sha, name, email, iso = parts[0], parts[1], parts[2].lower(), parts[3]
        subject = FS.join(parts[4:])
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            continue
        files = []
        for line in body.splitlines():
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            a, d, path = cols
            files.append((path, int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0))
        commits.append(Commit(sha, name, email, int(dt.timestamp()), dt.hour, dt.weekday(), subject, files))
    return commits


def rev_list(repo: str, rev_range: str) -> Set[str]:
    """Full SHAs of non-merge commits in a range such as origin/main..HEAD."""
    out = _git(repo, "rev-list", "--no-merges", rev_range)
    return {line.strip() for line in out.splitlines() if line.strip()}


def repo_name(repo: str) -> str:
    try:
        top = _git(repo, "rev-parse", "--show-toplevel").strip()
    except GitError:
        top = repo
    return top.rstrip("/").split("/")[-1] or "repository"
