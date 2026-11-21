"""Self-contained HTML report: a seismograph of the repo plus the details behind it."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from statistics import median
from typing import Dict, List, Optional

from .model import LOW_MAX, MEDIUM_MAX, Assessment

CSS = """
:root{--bg:#E9EEF2;--panel:#F7F9FA;--ink:#17202B;--mute:#566574;--rule:#C3CDD6;
--low:#5B7083;--med:#B87800;--high:#C0392B}
@media (prefers-color-scheme:dark){:root{--bg:#141B22;--panel:#1B242D;--ink:#E4EAEF;--mute:#93A2B0;
--rule:#2D3A46;--low:#8CA2B5;--med:#E0A92E;--high:#F0685A}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Avenir Next","Segoe UI","Helvetica Neue",system-ui,sans-serif;
font-variant-numeric:tabular-nums}
main{max-width:1040px;margin:0 auto;padding:40px 20px 64px}
h1{font-size:1.1rem;font-weight:600;margin:0;color:var(--mute)}
.verdict{font-size:clamp(1.5rem,3.4vw,2.3rem);line-height:1.2;font-weight:650;margin:10px 0 28px;max-width:30ch}
h2{font-size:1.05rem;margin:44px 0 10px}
p.note{color:var(--mute);margin:0 0 14px;max-width:68ch}
.trace{background:var(--panel);border:1px solid var(--rule);border-radius:6px;padding:10px}
.trace svg{display:block;width:100%;height:auto}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--rule)}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;color:var(--mute);font-size:.88rem}
td.num{text-align:right}
.pill{display:inline-block;min-width:2.6em;text-align:center;padding:1px 8px;border-radius:4px;font-weight:650;border:1.5px solid}
.LOW{color:var(--low);border-color:var(--low)}.MEDIUM{color:var(--med);border-color:var(--med)}
.HIGH{color:var(--high);border-color:var(--high)}
code{font:.9em ui-monospace,Menlo,Consolas,monospace}
.why{color:var(--mute);font-size:.92rem}
.flag{color:var(--high);font-weight:600}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
"""


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


def _trace(assessments: List[Assessment]) -> str:
    items = assessments[-300:]
    w, h, base = 1000, 150, 75
    n = max(1, len(items))
    step = w / n
    pts, dots = [], []
    for i, a in enumerate(items):
        amp = a.score / 100 * 66
        x = i * step + step / 2
        pts.append(f"{x:.1f},{base - amp * (1 if i % 2 == 0 else -1):.1f}")
        if a.band == "HIGH":
            tip = f"{a.score} {a.commit.short} {a.commit.subject}"
            dots.append(f'<circle cx="{x:.1f}" cy="{base - amp * (1 if i % 2 == 0 else -1):.1f}" r="3.5" '
                        f'fill="var(--high)"><title>{escape(tip)}</title></circle>')
    guides = ""
    for label, val in (("medium", LOW_MAX), ("high", MEDIUM_MAX)):
        y = base - val / 100 * 66
        guides += (f'<line x1="0" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--rule)" stroke-dasharray="4 4"/>'
                   f'<text x="{w - 4}" y="{y - 4:.1f}" text-anchor="end" font-size="11" fill="var(--mute)">{label} starts at {val}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Risk score of each commit over time">'
            f'<line x1="0" x2="{w}" y1="{base}" y2="{base}" stroke="var(--rule)"/>{guides}'
            f'<polyline fill="none" stroke="var(--ink)" stroke-width="1" points="{" ".join(pts)}"/>{"".join(dots)}</svg>')


def render(name: str, assessments: List[Assessment], hotspots: List[Dict], bt: Dict, top: int = 15) -> str:
    scores = [a.score for a in assessments]
    high = sum(1 for a in assessments if a.band == "HIGH")
    verdict = (f"{high} of {len(assessments)} recent commits were high risk." if assessments
               else "No commits to score.")
    ranked = sorted(assessments, key=lambda a: a.score, reverse=True)[:top]

    rows = "".join(
        f'<tr><td><span class="pill {a.band}">{a.score}</span></td><td><code>{escape(a.commit.short)}</code></td>'
        f'<td>{escape(a.commit.subject)}<div class="why">{escape(a.commit.author)}: '
        f'{escape("; ".join(a.reasons))}</div></td></tr>' for a in ranked)

    hrows = "".join(
        f'<tr><td><code>{escape(r["path"])}</code></td><td class="num">{r["commits"]}</td>'
        f'<td class="num">{r["recent"]}</td><td class="num">{round(r["fix_ratio"] * 100)}%</td>'
        f'<td>{escape(r["owner"])} ({round(r["owner_share"] * 100)}%)'
        f'{" <span class=flag>single point of knowledge</span>" if r["bus_factor_1"] else ""}</td>'
        f'<td class="num">{r["risk"]}</td></tr>' for r in hotspots)

    if bt.get("n"):
        b = bt["by_band"]
        auc = bt["auc"]
        fit = ("Ranking quality (AUC) is " + (f"{auc:.2f}" if auc is not None else "not measurable")
               + ". 0.50 is a coin flip and 1.00 is perfect.")
        bt_html = (f'<p class="note">Of {bt["n"]} commits with a full {bt["horizon_days"]}-day follow-up, '
                   f'{_pct(bt["base_rate"])} were followed by a fix to the same files. '
                   f'High-risk commits: {_pct(b["HIGH"]["rate"])} (of {b["HIGH"]["n"]}). '
                   f'Medium: {_pct(b["MEDIUM"]["rate"])} (of {b["MEDIUM"]["n"]}). '
                   f'Low: {_pct(b["LOW"]["rate"])} (of {b["LOW"]["n"]}). {fit}</p>')
    else:
        bt_html = '<p class="note">Not enough history to test the model yet. It needs commits older than the follow-up window.</p>'

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    med = f"Median score {int(median(scores))}." if scores else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShipRisk report for {escape(name)}</title><style>{CSS}</style></head><body><main>
<h1>ShipRisk report for {escape(name)}, generated {stamp}</h1>
<p class="verdict">{escape(verdict)}</p>
<div class="trace">{_trace(assessments)}</div>
<p class="note">Each swing is one commit, oldest on the left. Taller means riskier. {med} Red dots are high-risk commits; hover for details.</p>
<h2>Riskiest commits</h2>
<div class="scroll"><table><thead><tr><th>Score</th><th>Commit</th><th>What and why</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Risky files</h2>
<p class="note">Files that change often, break often, or are understood by one person.</p>
<div class="scroll"><table><thead><tr><th>File</th><th>Commits</th><th>Last 90 days</th><th>Were fixes</th><th>Main author</th><th>Risk</th></tr></thead><tbody>{hrows}</tbody></table></div>
<h2>Does the model fit this repo?</h2>
{bt_html}
</main></body></html>"""
