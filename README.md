# ShipRisk

**Score every commit for release risk, using nothing but your own git history.**

Code review time is limited. ShipRisk tells reviewers and release managers where to spend it: which commits and files are most likely to be followed by a bug fix, and why. It runs locally, has **zero dependencies** (Python standard library only), and never sends your code anywhere.

Unlike a generic linter, ShipRisk learns from *your* repository: which files keep breaking, who knows which code, and when risky changes tend to happen. It also includes a **backtest** that measures, on your own history, whether its scores actually predict trouble, so you never have to take it on faith.

## Install

```bash
pip install git+https://github.com/ManavRaj09/shiprisk
# or, from a clone:  pip install .
```

Requires Python 3.9+ and git.

## Use

```bash
shiprisk scan                    # score the last 200 commits of the repo in the current folder
shiprisk scan --html report.html # also write a self-contained HTML report
shiprisk hotspots                # risky files: churn, fix rate, single point of knowledge
shiprisk backtest                # how well do scores predict follow-up fixes here?
shiprisk check --range origin/main..HEAD --fail-above 75   # for CI; exit code 1 if too risky
```

Sample output (from a generated demo repo, see `docs/sample-report.html`):

```
Scored 120 commits | median 39 | HIGH 3  MEDIUM 80  LOW 37

 61 HIGH    a30ad43  Chitra   fix: update orders.py #36
              157 lines changed across 1 file; 50% of past changes to api/orders.py were fixes;
              157 source lines changed and no test file touched
```

## How the score works

Each commit gets 0-100 from eight signals. Every signal is computed only from history that existed **before** that commit (there is a test for this), so scores are never contaminated by the future.

| Signal | Weight | What it looks at |
|---|---|---|
| Size | 20 | Lines changed (lock files, minified and image files ignored) |
| Hotspot | 15 | How often the touched files changed in the previous 90 days |
| Bug history | 15 | Share of past changes to these files that were fixes |
| Unfamiliar author | 15 | Author never or rarely touched these files, or is new to the repo |
| Spread | 10 | Number of directories touched |
| No tests | 10 | Source changes with no test file in the same commit |
| Sensitive paths | 10 | Auth, payments, migrations, CI workflows, Dockerfiles, dependency manifests, infra |
| Timing | 5 | Weekend, late night, or Friday evening |

Docs-only commits are scaled down to 20% and test-only commits to 50%. A subject containing hotfix, urgent, wip or hack adds 8 points. Bands: LOW below 30, MEDIUM below 55, HIGH from 55. Weights and thresholds are plain constants at the top of `shiprisk/model.py`; change them to suit your team.

## Use it as a pull request check

Copy `.github/workflows/shiprisk.yml` into your repo. Every pull request gets a risk table in its job summary, and the job fails if any commit scores 80 or more. The checkout must use `fetch-depth: 0` so ShipRisk can see history.

## Honest limits

- It estimates risk from history. It does not read or understand the code itself, so treat scores as a triage hint for human review, not a verdict.
- It needs history. On a repo with a few dozen commits, most signals are weak.
- "Fix" detection is based on commit subjects (fix, bug, hotfix, revert, patch, regression, crash, broken). Teams that never write such subjects will get weak bug-history signals.
- The backtest labels a commit "followed by trouble" when a later fix-style commit touches the same source files within the horizon (14 days by default). That is a proxy, not ground truth. If the backtest shows an AUC near 0.50 on your repo, the scores are not adding information there, and ShipRisk will tell you so.
- The included tests verify the mechanics on synthetic repos. Predictive accuracy on real projects is something to measure with `shiprisk backtest` on repos you care about.

## Development

```bash
python -m unittest discover -s tests -v
```

Layout: `gitlog.py` reads history, `model.py` scores, `hotspots.py` ranks files, `backtest.py` validates, `report.py` renders HTML, `cli.py` ties it together.

## License

MIT
