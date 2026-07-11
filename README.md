# Agentic Market Research Journal

A **daily LangGraph paper-portfolio workflow**. Each run reviews yesterday's
paper picks against a benchmark, gathers public market data / news / filings /
macro context, scores candidates with a transparent formula, and uses LLM
agents to record today's paper picks — then writes a decision log, a Markdown
report, and an updated strategy memory.

> **This is a paper research journal. It does not trade and is not investment
> advice.** It records decisions, evidence, confidence scores, and learnings.

## The closed loop

```
observe → decide → record → measure → explain → learn → improve tomorrow
```

```
load_memory → load_yesterday → fetch_prices → calculate_features
  → score_yesterday(vs QQQ) → fetch_context(news/earnings/filings/macro)
  → build_candidates(transparent score) → news_catalyst(LLM)
  → risk(LLM) → committee(LLM, structured) → write_decision
  → render_report → update_memory(LLM)
```

- **Deterministic nodes:** load memory, load yesterday, fetch prices, compute
  features, score prior picks vs QQQ, fetch context, build & score candidates,
  write decision/report.
- **LLM agents:** News/Catalyst (`gpt-4o-mini`), Risk/Challenge (`gpt-4o`),
  Portfolio Committee (`gpt-4o`, structured output), Memory/Learning (`gpt-4o`).

## Prediction framing

> A paper-tracked confidence estimate for potential **QQQ outperformance over
> the next 1 trading day**, based on transparent public-data signals — not a
> trained model.

Transparent score:

```
candidate_score = momentum + relative_strength + volume_confirmation + catalyst
                  − earnings_risk_penalty − volatility_penalty − weak_evidence_penalty
```

## Data sources

| Input            | Source                  | Key needed            |
| ---------------- | ----------------------- | --------------------- |
| Price / volume   | yfinance                | no                    |
| News / earnings  | Finnhub                 | `FINNHUB_API_KEY`     |
| SEC filings flags| SEC EDGAR               | no (User-Agent only)  |
| Macro snapshot   | FRED (+ VIX via yfinance) | `FRED_API_KEY`      |
| LLM agents       | OpenAI                  | `OPENAI_API_KEY`      |

All clients **degrade gracefully**: missing keys or network simply yield
empty/neutral data plus a recorded warning, so the workflow never crashes.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env   # then fill in keys

# Full run (uses APIs + LLMs if keys present)
python -m market_journal.main --date today

# Deterministic dry-run: no LLM, no network judgement
python -m market_journal.main --date today --offline
```

Artifacts are written under `data/`:

```
data/decisions/YYYY-MM-DD.json   # full decision record (audit fields included)
data/reports/YYYY-MM-DD.md       # human-readable daily report
data/memory/strategy_memory.json # conservative learning state
```

## Strategy memory (conservative)

`strategy_memory.json` separates `observations`, `tentative_lessons`,
`promoted_rules`, and `deprecated_rules`. A tentative lesson is **only promoted
to a rule after appearing ≥3 times across ≥2 separate weeks** (within the last
~60 runs), so a single unusual week can't mint a rule on its own. Paraphrased
lessons are merged by a semantic matcher (LLM, with an exact-text fallback) so
re-wordings count toward the same idea. The Memory agent proposes notes;
promotion is deterministic, so the strategy is not rewritten every day.

## Scheduling (GitHub Actions)

`.github/workflows/daily-run.yml` runs weekdays after the US close, then
**commits the generated `data/` artifacts back to the repo** so the feedback
loop persists. Add repository secrets: `OPENAI_API_KEY`, `FINNHUB_API_KEY`,
`FRED_API_KEY`, `SEC_USER_AGENT`. Trigger manually via *Run workflow*
(`workflow_dispatch`).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Disclaimer

For educational/portfolio purposes only. Simulated decisions, no real trades,
not investment advice.
