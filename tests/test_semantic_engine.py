"""Tests para el Semantic Engine — TF-IDF, Cosine, Bayesian, Decay."""
import math
import pytest
from deepseek_code.intelligence.semantic_engine import (
    TFIDFVectorizer,
    cosine_similarity,
    BayesianEstimator,
    temporal_decay,
    weighted_score,
    mann_kendall_trend,
)


class TestTFIDFVectorizer:
    def test_tokenize_basic(self):
        v = TFIDFVectorizer()
        tokens = v.tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_accents(self):
        v = TFIDFVectorizer()
        tokens = v.tokenize("animacion grafica")
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

    def test_single_word_document(self):
        v = TFIDFVectorizer()
        v.fit(["hello", "world"])
        vec = v.transform("hello")
        assert "hello" in vec


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
        assert upper - lower < 0.3

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
        b.update(successes=1, failures=9)
        risk = b.risk_score(threshold=0.5)
        assert risk > 0.5

    def test_from_stats(self):
        b = BayesianEstimator.from_stats(successes=7, total=10)
        assert abs(b.mean() - (8 / 12)) < 0.001


class TestTemporalDecay:
    def test_zero_age(self):
        assert abs(temporal_decay(0, half_life=30) - 1.0) < 0.001

    def test_one_half_life(self):
        assert abs(temporal_decay(30, half_life=30) - 0.5) < 0.001

    def test_two_half_lives(self):
        assert abs(temporal_decay(60, half_life=30) - 0.25) < 0.001

    def test_weighted_score_fn(self):
        score = weighted_score(10.0, age_days=30, half_life=30)
        assert abs(score - 5.0) < 0.01

    def test_negative_age_clamps(self):
        # Edad negativa deberia retornar 1.0 (o al menos >= 1.0)
        assert temporal_decay(-5, half_life=30) >= 1.0


class TestMonotonicTrend:
    def test_increasing(self):
        values = [1, 2, 3, 4, 5, 6]
        tau, trend = mann_kendall_trend(values)
        assert trend == "increasing"
        assert tau > 0.5

    def test_decreasing(self):
        values = [6, 5, 4, 3, 2, 1]
        tau, trend = mann_kendall_trend(values)
        assert trend == "decreasing"
        assert tau < -0.5

    def test_stable(self):
        values = [3, 3, 3, 3, 3]
        tau, trend = mann_kendall_trend(values)
        assert trend == "stable"

    def test_too_few_values(self):
        tau, trend = mann_kendall_trend([1, 2])
        assert trend == "stable"
