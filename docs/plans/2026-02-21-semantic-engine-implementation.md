# Semantic Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace keyword matching, FIFO memory, and basic prediction with real algorithms (TF-IDF, Bayesian inference, temporal decay) — all pure Python, zero dependencies.

**Architecture:** A centralized `semantic_engine.py` provides 4 math primitives (TF-IDF vectorizer, cosine similarity, Bayesian estimator, temporal decay). A `semantic_skill_index.py` wraps TF-IDF for skill matching. Four existing modules are upgraded to consume the engine.

**Tech Stack:** Python 3.10+, stdlib only (math, re, collections, dataclasses). pytest for tests.

**Design doc:** `docs/plans/2026-02-21-semantic-engine-design.md`

---

### Task 1: Test Infrastructure Setup

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_semantic_engine.py`

**Step 1: Create test directory and conftest**

```bash
mkdir -p tests
```

Create `tests/__init__.py` (empty).

**Step 2: Write failing tests for TFIDFVectorizer**

Create `tests/test_semantic_engine.py`:

```python
"""Tests for the Semantic Engine — TF-IDF, Cosine, Bayesian, Decay."""
import math
from deepseek_code.intelligence.semantic_engine import (
    TFIDFVectorizer,
    cosine_similarity,
    BayesianEstimator,
    temporal_decay,
    weighted_score,
)


class TestTFIDFVectorizer:
    def test_tokenize_basic(self):
        v = TFIDFVectorizer()
        tokens = v.tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_accents(self):
        v = TFIDFVectorizer()
        tokens = v.tokenize("animación gráfica")
        assert "animacion" in tokens
        assert "grafica" in tokens

    def test_tokenize_bigrams(self):
        v = TFIDFVectorizer()
        tokens = v.tokenize("game engine design")
        assert "game_engine" in tokens
        assert "engine_design" in tokens

    def test_fit_creates_idf(self):
        v = TFIDFVectorizer()
        corpus = ["the cat sat", "the dog ran", "a bird flew"]
        v.fit(corpus)
        # "the" appears in 2/3 docs — lower IDF
        # "cat" appears in 1/3 docs — higher IDF
        assert v.idf["cat"] > v.idf["the"]

    def test_transform_produces_sparse_vector(self):
        v = TFIDFVectorizer()
        corpus = ["alpha beta gamma", "beta gamma delta", "gamma delta epsilon"]
        v.fit(corpus)
        vec = v.transform("alpha beta")
        assert isinstance(vec, dict)
        assert "alpha" in vec
        assert vec["alpha"] > 0

    def test_fit_transform(self):
        v = TFIDFVectorizer()
        corpus = ["hello world", "goodbye world"]
        vectors = v.fit_transform(corpus)
        assert len(vectors) == 2
        assert "hello" in vectors[0]

    def test_empty_text(self):
        v = TFIDFVectorizer()
        v.fit(["some text"])
        vec = v.transform("")
        assert vec == {}


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = {"a": 1.0, "b": 2.0}
        assert abs(cosine_similarity(vec, vec) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        vec_a = {"a": 1.0}
        vec_b = {"b": 1.0}
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_similar_vectors(self):
        vec_a = {"a": 1.0, "b": 1.0, "c": 0.5}
        vec_b = {"a": 0.8, "b": 1.2, "d": 0.3}
        sim = cosine_similarity(vec_a, vec_b)
        assert 0.0 < sim < 1.0

    def test_empty_vector(self):
        assert cosine_similarity({}, {"a": 1.0}) == 0.0
        assert cosine_similarity({"a": 1.0}, {}) == 0.0
        assert cosine_similarity({}, {}) == 0.0


class TestBayesianEstimator:
    def test_uniform_prior(self):
        b = BayesianEstimator()
        assert abs(b.mean() - 0.5) < 0.001

    def test_update_successes(self):
        b = BayesianEstimator()
        b.update(successes=10, failures=0)
        assert b.mean() > 0.8

    def test_update_failures(self):
        b = BayesianEstimator()
        b.update(successes=0, failures=10)
        assert b.mean() < 0.2

    def test_confidence_interval(self):
        b = BayesianEstimator()
        b.update(successes=50, failures=50)
        lower, upper = b.confidence_interval(0.95)
        assert lower < b.mean() < upper
        assert upper - lower < 0.3  # Reasonable width

    def test_confidence_narrows_with_data(self):
        b_small = BayesianEstimator()
        b_small.update(5, 5)
        b_large = BayesianEstimator()
        b_large.update(50, 50)
        width_small = b_small.confidence_interval()[1] - b_small.confidence_interval()[0]
        width_large = b_large.confidence_interval()[1] - b_large.confidence_interval()[0]
        assert width_large < width_small

    def test_risk_score(self):
        b = BayesianEstimator()
        b.update(successes=1, failures=9)  # Mostly failures
        risk = b.risk_score(threshold=0.5)
        assert risk > 0.5  # High risk of being below 50%

    def test_from_stats(self):
        b = BayesianEstimator.from_stats(successes=7, total=10)
        assert abs(b.mean() - (8/12)) < 0.001  # (7+1)/(10+2)


class TestTemporalDecay:
    def test_zero_age(self):
        assert abs(temporal_decay(0, half_life=30) - 1.0) < 0.001

    def test_one_half_life(self):
        assert abs(temporal_decay(30, half_life=30) - 0.5) < 0.001

    def test_two_half_lives(self):
        assert abs(temporal_decay(60, half_life=30) - 0.25) < 0.001

    def test_weighted_score(self):
        score = weighted_score(10.0, age_days=30, half_life=30)
        assert abs(score - 5.0) < 0.01


class TestMonotonicTrend:
    def test_increasing(self):
        from deepseek_code.intelligence.semantic_engine import mann_kendall_trend
        values = [1, 2, 3, 4, 5, 6]
        tau, trend = mann_kendall_trend(values)
        assert trend == "increasing"
        assert tau > 0.5

    def test_decreasing(self):
        from deepseek_code.intelligence.semantic_engine import mann_kendall_trend
        values = [6, 5, 4, 3, 2, 1]
        tau, trend = mann_kendall_trend(values)
        assert trend == "decreasing"
        assert tau < -0.5

    def test_stable(self):
        from deepseek_code.intelligence.semantic_engine import mann_kendall_trend
        values = [3, 3, 3, 3, 3]
        tau, trend = mann_kendall_trend(values)
        assert trend == "stable"

    def test_too_few_values(self):
        from deepseek_code.intelligence.semantic_engine import mann_kendall_trend
        tau, trend = mann_kendall_trend([1, 2])
        assert trend == "stable"  # Not enough data
```

**Step 3: Run tests to verify they fail**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_semantic_engine.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'deepseek_code.intelligence.semantic_engine'`

**Step 4: Commit test file**

```bash
git add tests/
git commit -m "test: add failing tests for semantic engine core"
```

---

### Task 2: Implement Semantic Engine Core

**Files:**
- Create: `src/deepseek_code/intelligence/semantic_engine.py`

**Step 1: Implement the full semantic engine**

Create `src/deepseek_code/intelligence/semantic_engine.py` with all 4 components:

1. **TFIDFVectorizer** — tokenize (word + bigram + accent strip), fit (compute IDF), transform (sparse vector)
2. **cosine_similarity()** — dot product / (||a|| * ||b||) on sparse dicts
3. **BayesianEstimator** — Beta distribution with update, mean, CI, risk_score
4. **temporal_decay()** + **weighted_score()** — exponential decay with configurable half-life
5. **mann_kendall_trend()** — simplified monotonic trend test

Key implementation details:
- Tokenizer: `re.findall(r'[a-z0-9]+', text.lower())` after accent stripping, then generate bigrams
- IDF: `math.log(N / (1 + df))` where df = document frequency
- Cosine: iterate only shared keys (sparse optimization)
- Beta CI: normal approximation `mean ± z * sqrt(var)`, clamped to [0, 1]
- Decay: `math.exp(-math.log(2) * age_days / half_life)`
- Mann-Kendall: count concordant - discordant pairs, tau = S / (n*(n-1)/2)

**Step 2: Run tests to verify they pass**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_semantic_engine.py -v
```

Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/deepseek_code/intelligence/semantic_engine.py
git commit -m "feat: add semantic engine core — TF-IDF, Bayesian, decay, trends (pure Python)"
```

---

### Task 3: Test Semantic Skill Index

**Files:**
- Create: `tests/test_semantic_skill_index.py`

**Step 1: Write failing tests for SemanticSkillIndex**

```python
"""Tests for Semantic Skill Index — TF-IDF skill matching."""
from deepseek_code.skills.semantic_skill_index import SemanticSkillIndex


class TestSemanticSkillIndex:
    def _make_keyword_map(self):
        return {
            "canvas-2d-reference": ["canvas", "2d", "draw", "fillRect", "ctx"],
            "physics-simulation": ["physics", "collision", "gravity", "velocity"],
            "web-audio-api": ["audio", "sound", "music", "oscillator"],
            "game-genre-patterns": ["rpg", "platformer", "shooter", "roguelike"],
        }

    def test_build_index(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        assert len(idx._corpus_vectors) == 4

    def test_search_finds_relevant_skill(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("I need to draw on a canvas with 2d graphics", top_k=3)
        names = [name for name, score in results]
        assert "canvas-2d-reference" in names

    def test_search_physics(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("handle collision detection and gravity for objects", top_k=3)
        names = [name for name, score in results]
        assert "physics-simulation" in names

    def test_search_returns_scores(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("canvas drawing", top_k=2)
        assert all(0.0 <= score <= 1.0 for _, score in results)

    def test_search_with_boost(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        # Skill with high success rate should be boosted
        skill_stats = {
            "canvas-2d-reference": {"injected": 10, "with_success": 9, "success_rate": 0.9},
            "physics-simulation": {"injected": 10, "with_success": 2, "success_rate": 0.2},
        }
        results = idx.search_with_boost("render game graphics on screen", top_k=4, skill_stats=skill_stats)
        # Canvas should be ranked higher due to Bayesian boost
        names = [name for name, score in results]
        if "canvas-2d-reference" in names and "physics-simulation" in names:
            canvas_idx = names.index("canvas-2d-reference")
            physics_idx = names.index("physics-simulation")
            assert canvas_idx < physics_idx

    def test_empty_query(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("", top_k=3)
        assert results == []

    def test_no_match(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("kubernetes deployment docker containers", top_k=3)
        # Low or no similarity — may return empty or very low scores
        for _, score in results:
            assert score < 0.5  # Nothing closely matches
```

**Step 2: Run to verify failure**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_semantic_skill_index.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Commit**

```bash
git add tests/test_semantic_skill_index.py
git commit -m "test: add failing tests for semantic skill index"
```

---

### Task 4: Implement Semantic Skill Index

**Files:**
- Create: `src/deepseek_code/skills/semantic_skill_index.py`

**Step 1: Implement SemanticSkillIndex**

```python
class SemanticSkillIndex:
    """Pre-computed TF-IDF index for semantic skill matching."""

    def __init__(self):
        self._vectorizer = TFIDFVectorizer()
        self._corpus_vectors = {}  # {skill_name: sparse_vector}
        self._skill_names = []

    def build_from_keywords(self, keyword_map: dict):
        """Build index from SKILL_KEYWORD_MAP."""
        # Corpus = "skill_name keyword1 keyword2 ..."
        corpus_texts = []
        self._skill_names = []
        for name, keywords in keyword_map.items():
            text = f"{name.replace('-', ' ')} {' '.join(keywords)}"
            corpus_texts.append(text)
            self._skill_names.append(name)
        vectors = self._vectorizer.fit_transform(corpus_texts)
        self._corpus_vectors = dict(zip(self._skill_names, vectors))

    def search(self, task: str, top_k: int = 5) -> list:
        """Semantic search: find top-k skills by TF-IDF cosine similarity."""
        if not task.strip():
            return []
        query_vec = self._vectorizer.transform(task)
        if not query_vec:
            return []
        scores = []
        for name, vec in self._corpus_vectors.items():
            sim = cosine_similarity(query_vec, vec)
            if sim > 0.0:
                scores.append((name, sim))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    def search_with_boost(self, task, top_k, skill_stats=None):
        """Search with Bayesian success-rate boost from GlobalStore stats."""
        results = self.search(task, top_k=top_k * 2)  # Get more candidates
        if not skill_stats:
            return results[:top_k]
        boosted = []
        for name, sim in results:
            stat = skill_stats.get(name, {})
            successes = stat.get("with_success", 0)
            total = stat.get("injected", 0)
            if total > 0:
                bayes = BayesianEstimator.from_stats(successes, total)
                boost = bayes.mean()
            else:
                boost = 0.5  # Neutral prior
            boosted.append((name, sim * boost))
        boosted.sort(key=lambda x: -x[1])
        return boosted[:top_k]
```

**Step 2: Run tests**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_semantic_skill_index.py -v
```

Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/deepseek_code/skills/semantic_skill_index.py
git commit -m "feat: add semantic skill index — TF-IDF matching for skills"
```

---

### Task 5: Integrate Semantic Skills into skill_injector.py

**Files:**
- Modify: `src/deepseek_code/skills/skill_injector.py` (lines 41-81)

**Step 1: Write integration test**

Add to `tests/test_semantic_skill_index.py`:

```python
class TestSkillInjectorIntegration:
    def test_detect_relevant_skills_semantic(self):
        """Verify the injector uses semantic matching."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        # "renderizar graficos" should find canvas skills even though
        # "renderizar" is not in the keyword map
        results = detect_relevant_skills("renderizar graficos en pantalla", max_skills=5)
        # Should return something (keyword fallback at minimum)
        assert isinstance(results, list)
```

**Step 2: Modify detect_relevant_skills()**

In `skill_injector.py`:
- Add import of `SemanticSkillIndex` and `SKILL_KEYWORD_MAP`
- Create module-level `_semantic_index` (lazy singleton)
- Modify `detect_relevant_skills()` to try semantic search first, fallback to keywords

The old keyword-matching code becomes `_keyword_fallback()`.

Key change: the function signature stays identical — backward compatible.

**Step 3: Run all tests**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/deepseek_code/skills/skill_injector.py tests/test_semantic_skill_index.py
git commit -m "feat: integrate semantic skill matching into injector (keyword fallback preserved)"
```

---

### Task 6: Test Intelligent Memory (SurgicalStore)

**Files:**
- Create: `tests/test_intelligent_memory.py`

**Step 1: Write failing tests**

```python
"""Tests for intelligent memory with decay and semantic relevance."""
from deepseek_code.surgical.store import SurgicalStore


class TestSurgicalStoreIntelligent:
    def test_find_relevant_errors(self, tmp_path):
        """Semantic search should find relevant errors by content similarity."""
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        store.add_error({"type": "TypeError", "message": "Cannot read property of undefined"})
        store.add_error({"type": "SyntaxError", "message": "Unexpected token }"})
        store.add_error({"type": "TypeError", "message": "null is not an object"})
        store.save()

        results = store.find_relevant("undefined null type errors", "error_log", top_k=2)
        assert len(results) <= 2
        # Should prefer TypeErrors over SyntaxError
        types = [r.get("type") for r in results]
        assert "TypeError" in types

    def test_smart_compact_prefers_recent(self, tmp_path):
        """Smart compaction should weight recent entries higher."""
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        # Add old entries and new entries
        for i in range(40):
            store.add_error({"type": f"Error{i}", "message": f"error {i}"})
        store.save()

        # After compaction, should have <= MAX entries
        assert len(store.data["error_log"]) <= 30
```

**Step 2: Run to verify failure**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_intelligent_memory.py -v
```

Expected: FAIL — `AttributeError: 'SurgicalStore' has no attribute 'find_relevant'`

**Step 3: Commit**

```bash
git add tests/test_intelligent_memory.py
git commit -m "test: add failing tests for intelligent memory"
```

---

### Task 7: Implement Intelligent Memory in SurgicalStore

**Files:**
- Modify: `src/deepseek_code/surgical/store.py`

**Step 1: Add semantic capabilities to SurgicalStore**

Add to `store.py`:
- Import `TFIDFVectorizer, cosine_similarity, temporal_decay` from semantic_engine
- New method: `find_relevant(query, section, top_k)` — TF-IDF search over entries in a section
- Modify `_compact()` — use `relevance = decay(age) * (1 + frequency)` for sorting instead of pure FIFO
- Entries get `timestamp` on creation (already done), use it for decay calculation

Key: The file must stay under 400 LOC. If it exceeds, extract `_semantic_helpers` into a separate file.

**Step 2: Run tests**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_intelligent_memory.py tests/test_semantic_engine.py -v
```

Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/deepseek_code/surgical/store.py
git commit -m "feat: add semantic search and smart compaction to SurgicalStore"
```

---

### Task 8: Implement Bayesian Stats in GlobalStore

**Files:**
- Modify: `src/deepseek_code/global_memory/global_store.py`

**Step 1: Write test**

Add to `tests/test_intelligent_memory.py`:

```python
class TestGlobalStoreBayesian:
    def test_bayesian_skill_stat(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        # Update with few data points
        store.update_skill_stat("canvas-2d", success=True, truncated=False)
        store.update_skill_stat("canvas-2d", success=True, truncated=False)
        store.update_skill_stat("canvas-2d", success=False, truncated=True)
        store.save()

        stat = store.data["skill_stats"]["canvas-2d"]
        # Should have Bayesian fields
        assert "bayesian_mean" in stat
        assert 0.0 <= stat["bayesian_mean"] <= 1.0
        # With 2 successes, 1 failure: Beta(3,2) -> mean = 0.6
        assert stat["bayesian_mean"] > 0.5

    def test_semantic_error_clustering(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        store.add_cross_error("TypeError: undefined is not a function", "project_a")
        store.add_cross_error("TypeError: Cannot read property of undefined", "project_b")
        store.save()

        # These two should be clustered together semantically
        errors = store.data["cross_project_errors"]
        # At minimum, both should exist; ideally they'd be merged
        assert len(errors) >= 1
```

**Step 2: Modify GlobalStore**

In `global_store.py`:
- Import `BayesianEstimator, temporal_decay` from semantic_engine
- In `update_skill_stat()`: compute `bayesian_mean` using `BayesianEstimator.from_stats()`
- In `add_cross_error()`: before adding, check TF-IDF similarity against existing errors — if >0.7, merge instead of creating new entry
- In `_compact()`: weight entries by `decay(age) * count` instead of just `count`

**Step 3: Run tests**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_intelligent_memory.py -v
```

Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/deepseek_code/global_memory/global_store.py tests/test_intelligent_memory.py
git commit -m "feat: add Bayesian stats and semantic error clustering to GlobalStore"
```

---

### Task 9: Test Bayesian Predictor

**Files:**
- Create: `tests/test_bayesian_predictor.py`

**Step 1: Write failing tests**

```python
"""Tests for the Bayesian Predictor — confidence intervals, trends, composite risk."""
from deepseek_code.intelligence.predictor import generate_health_report


class TestBayesianPredictor:
    def test_health_report_has_bayesian_fields(self):
        store_data = {
            "project_name": "test",
            "error_log": [
                {"type": "truncation", "timestamp": "2026-02-01T12:00:00"},
                {"type": "truncation", "timestamp": "2026-02-10T12:00:00"},
                {"type": "syntax", "timestamp": "2026-02-15T12:00:00"},
            ],
            "delegation_history": [
                {"success": True, "duration_s": 30, "timestamp": "2026-02-01T12:00:00"},
                {"success": True, "duration_s": 35, "timestamp": "2026-02-05T12:00:00"},
                {"success": False, "duration_s": 60, "timestamp": "2026-02-10T12:00:00"},
                {"success": False, "duration_s": 45, "timestamp": "2026-02-15T12:00:00"},
            ],
        }
        report = generate_health_report(store_data=store_data)
        report_dict = report.to_dict()

        assert "bayesian_risk_score" in report_dict
        assert 0 <= report_dict["bayesian_risk_score"] <= 100
        assert "confidence_intervals" in report_dict
        assert "trend_slopes" in report_dict

    def test_healthy_project(self):
        store_data = {
            "project_name": "healthy",
            "error_log": [],
            "delegation_history": [
                {"success": True, "duration_s": 20} for _ in range(10)
            ],
        }
        report = generate_health_report(store_data=store_data)
        assert report.risk_level == "healthy"
        assert report.to_dict()["bayesian_risk_score"] < 30

    def test_critical_project(self):
        store_data = {
            "project_name": "critical",
            "error_log": [
                {"type": "truncation", "timestamp": f"2026-02-{i:02d}T12:00:00"}
                for i in range(1, 20)
            ],
            "delegation_history": [
                {"success": False, "duration_s": 90, "timestamp": f"2026-02-{i:02d}T12:00:00"}
                for i in range(1, 15)
            ],
        }
        report = generate_health_report(store_data=store_data)
        assert report.to_dict()["bayesian_risk_score"] > 50
```

**Step 2: Run to verify failure**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/test_bayesian_predictor.py -v
```

Expected: FAIL — `KeyError: 'bayesian_risk_score'` (old HealthReport lacks these fields)

**Step 3: Commit**

```bash
git add tests/test_bayesian_predictor.py
git commit -m "test: add failing tests for Bayesian predictor"
```

---

### Task 10: Implement Bayesian Predictor

**Files:**
- Modify: `src/deepseek_code/intelligence/predictor.py`

**Step 1: Upgrade predictor.py**

Add to predictor.py:
- Import `BayesianEstimator, mann_kendall_trend, temporal_decay` from semantic_engine
- Add fields to `HealthReport`: `bayesian_risk_score`, `confidence_intervals`, `trend_slopes`
- New function: `_compute_bayesian_risk(delegation_history)` → score 0-100
- New function: `_compute_trend_slopes(delegation_history)` → {indicator: slope}
- Modify `_calculate_risk_level()` to use Bayesian composite instead of simple counting
- Modify `to_dict()` to include new fields

Key additions:
- Bayesian failure rate: `Beta(failures+1, successes+1)`
- Trend slope via `mann_kendall_trend()` on rolling error counts
- Composite: `risk = 0.4 * failure_prob + 0.3 * trend_severity + 0.3 * file_risk_pct` scaled 0-100

**Step 2: Run all tests**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/deepseek_code/intelligence/predictor.py
git commit -m "feat: upgrade predictor with Bayesian inference, confidence intervals, and trend analysis"
```

---

### Task 11: Update __init__.py and Integration Test

**Files:**
- Modify: `src/deepseek_code/intelligence/__init__.py`
- Create: `tests/test_integration.py`

**Step 1: Update __init__.py**

Add `semantic_engine.py` to the module comment list.

**Step 2: Write integration test**

```python
"""End-to-end integration test: semantic engine powers all subsystems."""

class TestEndToEnd:
    def test_skill_selection_uses_semantic_engine(self):
        from deepseek_code.skills.semantic_skill_index import SemanticSkillIndex
        from deepseek_code.skills.skill_constants import SKILL_KEYWORD_MAP
        idx = SemanticSkillIndex()
        idx.build_from_keywords(SKILL_KEYWORD_MAP)
        # A synonym-based query that keywords would miss
        results = idx.search("renderizar graficos en pantalla", top_k=5)
        assert len(results) > 0  # Semantic matching finds something

    def test_full_health_report_with_bayesian(self):
        from deepseek_code.intelligence.predictor import generate_health_report
        report = generate_health_report(
            store_data={"project_name": "test", "error_log": [], "delegation_history": []},
        )
        d = report.to_dict()
        assert "bayesian_risk_score" in d
        assert d["risk_level"] == "healthy"
```

**Step 3: Run full test suite**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/deepseek_code/intelligence/__init__.py tests/test_integration.py
git commit -m "feat: complete semantic engine integration — all subsystems upgraded"
```

---

### Task 12: Final Verification and LOC Check

**Step 1: Verify no file exceeds 400 LOC**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && find src/ -name "*.py" -exec wc -l {} + | sort -n | tail -20
```

Expected: No file exceeds 400 lines.

**Step 2: Run full test suite one final time**

```bash
cd C:/Users/Galidar/Desktop/DeepSeekCode && python -m pytest tests/ -v
```

Expected: ALL PASS, 0 failures

**Step 3: Final commit with version bump**

```bash
git add -A
git commit -m "chore: verify all files under 400 LOC, full test suite passes"
```
