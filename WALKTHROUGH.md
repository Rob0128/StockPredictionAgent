# How It Works — Step by Step

A plain-English walk through the app, from the moment it starts to how it
records picks and "scores" their performance. Each step links to the exact
file and line that does the work.

> **Important framing:** this is a **paper research journal**. It never places
> trades and holds no money. "Profit" here means a *measured 1-day return vs
> the QQQ benchmark*, recorded for learning — not realized cash. There is no
> brokerage account and no real accounting ledger. See
> [Step 11 — "Profit" / accounting](#step-11--profit--accounting-the-honest-truth).

---

## Step 0 — What kicks it off

There are two ways a run starts, both ending at the same Python entry point:

- **Manually:** you run `python -m market_journal.main --date today`.
- **Automatically:** Windows Task Scheduler runs the task `MarketJournalDaily`
  every weekday at 22:30, which executes
  [scripts/run_daily.ps1](scripts/run_daily.ps1). That script activates the
  venv, runs the same `python -m market_journal.main` command, and appends all
  output to `logs/run-<date>.log`. The task is created/updated by
  [scripts/register_task.ps1](scripts/register_task.ps1).

---

## Step 1 — Entry point parses the date

File: [src/market_journal/main.py](src/market_journal/main.py)

1. [cli()](src/market_journal/main.py#L43) reads the `--date` and `--offline`
   command-line flags.
2. [resolve_date()](src/market_journal/main.py#L18) converts `today` /
   `yesterday` / `YYYY-MM-DD` into a concrete date string like `2026-06-26`.
3. [run()](src/market_journal/main.py#L30) sets offline mode if asked, makes
   sure the `data/` folders exist (`ensure_dirs()`), builds the workflow, and
   starts it with a tiny initial state:
   `initial = {"run_date": run_date, "warnings": []}`
   ([main.py line 38](src/market_journal/main.py#L38)).

From here, a **LangGraph** pipeline of 13 steps runs in a fixed order. They all
share one dictionary called `state` — each step reads what it needs and adds
its results back in.

---

## Step 2 — Build & start the pipeline

File: [src/market_journal/graph.py](src/market_journal/graph.py)

- [build_graph()](src/market_journal/graph.py#L253) registers every step as a
  node and wires them in a straight line from `START`
  ([graph.py line 270](src/market_journal/graph.py#L270)) to `END`
  ([graph.py line 283](src/market_journal/graph.py#L283)).
- `app.invoke(initial)` ([main.py line 39](src/market_journal/main.py#L39))
  runs the chain.

The order is:

```
load_memory → load_yesterday → fetch_prices → calculate_features
  → score_yesterday → fetch_context → build_candidates
  → news_catalyst → risk → committee
  → write_decision → render_report → update_memory
```

---

## Step 3 — Load what it learned before

[node_load_memory](src/market_journal/graph.py#L40) reads
`data/memory/strategy_memory.json` via
[load_memory()](src/market_journal/storage/memory.py#L61). This holds the
active "rules", past observations, and rolling performance stats.

---

## Step 4 — Find yesterday's picks (to grade them)

[node_load_yesterday](src/market_journal/graph.py#L44) finds the most recent
prior decision file using
[find_previous_decision()](src/market_journal/storage/decisions.py#L44) and
stashes its picks so the next steps can measure how they did.

---

## Step 5 — Get prices

[node_fetch_prices](src/market_journal/graph.py#L53) downloads recent
OHLCV (open/high/low/close/volume) for all 25 tickers plus the benchmarks
(QQQ, SPY) and sector ETFs, using yfinance via
[fetch_prices()](src/market_journal/data/prices.py). Results are cached per day
so re-runs don't re-download.

---

## Step 6 — Compute features

[node_calculate_features](src/market_journal/graph.py#L59) turns raw prices into
signals per ticker: momentum (5d/20d returns), strength vs QQQ, volume vs its
20-day average, volatility. Built by
[build_ticker_features()](src/market_journal/features.py).

---

## Step 7 — Grade yesterday (the "measure" step)

[node_score_yesterday](src/market_journal/graph.py#L89) calls
[review_yesterday()](src/market_journal/agents/performance_review.py#L17). For
each of yesterday's picks it computes the **1-day return** and subtracts the
QQQ return to get **excess return**, then a **hit rate** (how many beat QQQ).
This is the closest thing to "did we make money" — measured on paper, in
percent. The result is the `performance_review` block.

---

## Step 8 — Gather context (news / filings / macro)

[node_fetch_context](src/market_journal/graph.py#L97) enriches each ticker with:

- Company news + next-earnings date (Finnhub) — [data/news.py](src/market_journal/data/news.py)
- SEC filing flags, e.g. 8-K / 10-Q / Form 4 (SEC EDGAR) — [data/filings.py](src/market_journal/data/filings.py)
- A market-wide macro snapshot: VIX, 10-year yield, regime — [data/macro.py](src/market_journal/data/macro.py)

---

## Step 9 — Score and shortlist candidates

[node_build_candidates](src/market_journal/graph.py#L134) runs the **transparent
score** on every ticker via
[score_ticker()](src/market_journal/scoring.py#L86):

```
candidate_score = momentum + relative_strength + volume_confirmation + catalyst
                  − earnings_risk_penalty − volatility_penalty − weak_evidence_penalty
```

Each component is a small, readable function in
[scoring.py](src/market_journal/scoring.py#L22) (no trained model). It sorts by
score and keeps the **top 6** as candidates, each with its evidence list and a
[score_breakdown()](src/market_journal/scoring.py#L109).

---

## Step 10 — The LLM agents decide

Three LLM agents apply judgement on top of the numbers:

1. **News/Catalyst** — [assess_candidate()](src/market_journal/agents/news_catalyst.py#L21)
   (gpt-4o-mini): is the catalyst real or noise?
2. **Risk/Challenge** — [review_candidates()](src/market_journal/agents/risk.py#L55)
   (gpt-4o): per-ticker and portfolio-level risk notes.
3. **Portfolio Committee** — [decide()](src/market_journal/agents/portfolio_committee.py#L90)
   (gpt-4o, structured output): the final decision maker. Picks **up to 3**
   paper picks, each tagged `long` / `watch` / `avoid` with a confidence
   (1–5), a probability band, a thesis, and an `entry_reference_price` (the
   price we'd "buy" at on paper). Audit fields (`model_used`, `created_at`,
   `evidence_sources`) are stamped by code here, not the model.

These run in [node_news_catalyst](src/market_journal/graph.py#L174),
[node_risk](src/market_journal/graph.py#L188), and
[node_committee](src/market_journal/graph.py#L194).

---

## Step 11 — "Profit" / accounting (the honest truth)

There is **no trading and no cash ledger**. "Performance" is reconstructed each
day, not stored as money:

- Each pick records an `entry_reference_price` when it's made (Step 10).
- The **next** day, Step 7 re-prices that ticker and computes its 1-day return
  and excess vs QQQ — see
  [review_yesterday()](src/market_journal/agents/performance_review.py#L17).
- Rolling summary stats (e.g. recent hit rate, average excess vs benchmark)
  are kept in `data/memory/strategy_memory.json` under `recent_performance`,
  updated by [integrate_update()](src/market_journal/storage/memory.py#L86).

So the "accounting" is: **per-day percentage returns vs QQQ, recorded inside
each decision file, with rolling averages in memory.** No dollars, no
positions held, no realized P&L ledger. (A true append-only equity ledger
could be added later — it doesn't exist yet.)

---

## Step 12 — Write the files

File: [src/market_journal/graph.py](src/market_journal/graph.py)

1. [node_write_decision](src/market_journal/graph.py#L208) saves the full
   record (macro, yesterday's review, candidates, risk, the committee's picks,
   warnings) to `data/decisions/<date>.json` via
   [save_decision()](src/market_journal/storage/decisions.py#L20).
   **Re-running the same day overwrites this file.**
2. [node_render_report](src/market_journal/graph.py#L223) writes a readable
   Markdown report to `data/reports/<date>.md` via
   [save_report()](src/market_journal/storage/decisions.py#L37).

---

## Step 13 — Learn for next time

[node_update_memory](src/market_journal/graph.py#L236) asks the Memory agent
([propose_update()](src/market_journal/agents/memory_agent.py#L26), gpt-4o) for
a few cautious observations and lessons, then merges them conservatively with
[integrate_update()](src/market_journal/storage/memory.py#L86). A tentative
lesson only becomes a hard "rule" after it shows up **≥3 times across ≥2
separate weeks** (`PROMOTION_THRESHOLD` / `MIN_DISTINCT_WEEKS`, within the
`PROMOTION_WINDOW` of recent runs), so the strategy isn't rewritten every day
and one strange week can't promote a rule alone. Saved to
`data/memory/strategy_memory.json`.

---

## Step 14 — Print a summary

Back in [cli()](src/market_journal/main.py#L43), the app prints the day's
picks, yesterday's hit rate / average excess return, any warnings, and the
disclaimer, then exits.

---

## The three files that ARE the system's "memory"

| File | Written by | Purpose |
| --- | --- | --- |
| `data/decisions/<date>.json` | Step 12 | Full audit record; also tomorrow's grading target |
| `data/reports/<date>.md` | Step 12 | Human-readable daily report |
| `data/memory/strategy_memory.json` | Step 13 | Slow-learning rules + rolling performance stats |

The closed loop: **decide → record → measure → learn → improve** — repeated
every weekday.
