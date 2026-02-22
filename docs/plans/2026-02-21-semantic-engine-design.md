# Semantic Engine — Design Document

**Date:** 2026-02-21
**Status:** Approved
**Scope:** Replace keyword matching, FIFO memory, and basic prediction with real algorithms

## Problem Statement

4 weaknesses identified in DeepSeek Code:

1. **Memory is simple text storage** — JSON with FIFO queues and counters. No decay, no semantic relevance.
2. **Skills use keyword matching** — 46-entry hardcoded map. Synonyms fail ("renderizar" vs "dibujar").
3. **Predictive intelligence is basic** — Counts LOC and groups error strings. No statistical modeling.
4. **Code is mostly API wrappers** — Clever prompts, not algorithms.

Root cause: **lack of semantic understanding** across all subsystems.

## Solution: Centralized Semantic Engine

One Python-pure engine providing TF-IDF, cosine similarity, Bayesian inference, and temporal decay.
All 4 subsystems consume it. Zero external dependencies.

## Architecture

```
intelligence/semantic_engine.py  (NEW ~300 LOC)
    ├── skills/semantic_skill_index.py   (NEW ~120 LOC, consumes TF-IDF + Cosine)
    ├── skills/skill_injector.py         (MODIFY, consumes SemanticSkillIndex)
    ├── surgical/store.py                (MODIFY, consumes TF-IDF + Decay)
    ├── global_memory/global_store.py    (MODIFY, consumes Bayesian + Decay)
    └── intelligence/predictor.py        (MODIFY, consumes Bayesian + Trend)
```

## Component 1: Semantic Engine Core

File: `src/deepseek_code/intelligence/semantic_engine.py` (~300 LOC)

### TFIDFVectorizer

Pure Python TF-IDF implementation using sparse dictionaries.

- `tokenize(text)` — word split + bigram generation + accent normalization
- `fit(corpus: List[str])` — compute IDF for entire corpus
- `transform(text)` — produce sparse vector {term: tfidf_weight}
- `fit_transform(corpus)` — fit + transform in one pass

Key math:
- TF(t,d) = count(t in d) / total_terms(d)
- IDF(t) = log(N / (1 + df(t)))
- TF-IDF(t,d) = TF(t,d) * IDF(t)

Representation: `Dict[str, float]` sparse vectors (~2KB per document vs ~80KB dense).

### CosineSimilarity

- `similarity(vec_a, vec_b)` — dot product / (||a|| * ||b||)
- `top_k(query_vec, corpus_vecs, k)` — top-k most similar

### BayesianEstimator

Beta distribution for success/failure modeling.

- `Beta(alpha=1, beta=1)` — uniform prior
- `update(successes, failures)` — posterior update
- `mean()` — point estimate P(success) = alpha / (alpha + beta)
- `confidence_interval(level=0.95)` — approximate quantiles
- `risk_score(threshold)` — P(success < threshold)

Confidence interval uses the normal approximation to Beta:
- mean = alpha / (alpha + beta)
- variance = (alpha * beta) / ((alpha + beta)^2 * (alpha + beta + 1))
- CI = mean +/- z * sqrt(variance)

### TemporalDecay

Exponential decay with configurable half-life.

- `decay(age_days, half_life=30)` — returns factor 0.0-1.0
- Formula: `e^(-ln(2) * age_days / half_life)`
- `weighted_score(base_score, age_days, half_life)` — score * decay(age_days)

## Component 2: Semantic Skill Index

File: `src/deepseek_code/skills/semantic_skill_index.py` (~120 LOC)

### SemanticSkillIndex

Pre-computes TF-IDF vectors for all 49 skills at startup.

- Corpus: skill name + keywords from SKILL_KEYWORD_MAP + first paragraph from SKILL.md
- `build_index(skills_dir, keyword_map)` — one-time indexing
- `search(task: str, top_k: int) -> List[Tuple[str, float]]` — semantic search
- `search_with_boost(task, top_k, skill_stats)` — multiply similarity by Bayesian success rate

### Integration with skill_injector.py

`detect_relevant_skills()` changes from:
```python
# OLD: keyword substring matching
for skill_name, keywords in SKILL_KEYWORD_MAP.items():
    score = sum(len(kw) for kw in keywords if kw in normalized)
```

To:
```python
# NEW: semantic similarity with Bayesian boost
results = semantic_index.search_with_boost(message, max_skills, global_skill_stats)
if not results:  # fallback to keywords
    results = _keyword_fallback(message, max_skills, exclude)
```

The keyword map remains as fallback — not deleted.

## Component 3: Intelligent Memory

### SurgicalStore Changes

1. **Smart compaction**: Instead of FIFO `error_log[-30:]`, compute
   `relevance = frequency * decay(age) * (1 + context_similarity)` and keep top-N.

2. **Semantic search**: New method `find_relevant(query, section, top_k)` uses TF-IDF
   to find entries most relevant to current task context.

3. **Contextual briefing**: `build_briefing()` prioritizes entries relevant to
   the current task, not just the most recent ones.

### GlobalStore Changes

1. **Bayesian skill stats**: Replace `success_rate = successes/total` with
   `BayesianEstimator(successes+1, failures+1).mean()` — stable estimates with few data points.

2. **Temporal decay**: All stats weighted by `decay(age_days, half_life=60)`.

3. **Semantic error clustering**: `cross_project_errors` grouped by TF-IDF similarity
   instead of exact `error_type` string match.

## Component 4: Bayesian Predictor

### HealthReport Enhancements

New fields:
```python
bayesian_risk_score: float      # 0-100 composite
confidence_intervals: dict      # {indicator: (lower, upper)}
trend_slopes: dict              # {indicator: slope_per_week}
```

### New Analysis Methods

1. **Bayesian failure probability**: `Beta(failures+1, successes+1)` with 95% CI
2. **Monotonic trend test**: Simplified Mann-Kendall — counts concordant vs discordant pairs
3. **Anomaly flagging**: Entries deviating >2sigma from Bayesian prior
4. **Composite risk**: Weighted combination of all Bayesian indicators (0-100 scale)

## File Impact Summary

| File | Action | Est. LOC |
|------|--------|----------|
| `intelligence/semantic_engine.py` | NEW | ~300 |
| `skills/semantic_skill_index.py` | NEW | ~120 |
| `skills/skill_injector.py` | MODIFY | ~50 lines change |
| `surgical/store.py` | MODIFY | ~60 lines change |
| `global_memory/global_store.py` | MODIFY | ~40 lines change |
| `intelligence/predictor.py` | MODIFY | ~80 lines change |
| **Total new** | | **~420 LOC** |
| **Total modified** | | **~230 LOC** |

## Constraints

- Zero external dependencies (pure Python math)
- No file exceeds 400 LOC
- Keyword map preserved as fallback (backward compatible)
- All existing tests continue to pass
- Memory format backward compatible (new fields are additive)

## Design Decisions

1. **Sparse dicts over arrays**: ~40x memory savings for TF-IDF vectors
2. **Bigrams in tokenization**: Captures "game engine" as atomic concept
3. **Beta(1,1) prior**: Uniform prior — no bias toward success or failure with no data
4. **Half-life 30 days (surgical), 60 days (global)**: Surgical needs faster adaptation; global is more stable
5. **Keyword fallback**: Never delete the keyword map — it's the safety net when TF-IDF has low confidence
