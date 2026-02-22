"""Tests de integracion end-to-end — el motor semantico alimenta todos los subsistemas."""
import pytest
from deepseek_code.intelligence.semantic_engine import (
    TFIDFVectorizer, cosine_similarity, BayesianEstimator,
    temporal_decay, mann_kendall_trend,
)


class TestSemanticEngineEndToEnd:
    """Verifica que el motor semantico funciona de punta a punta."""

    def test_tfidf_powers_skill_matching(self):
        """El indice de skills usa TF-IDF del semantic engine."""
        from deepseek_code.skills.semantic_skill_index import SemanticSkillIndex
        from deepseek_code.skills.skill_constants import SKILL_KEYWORD_MAP

        idx = SemanticSkillIndex()
        idx.build_from_keywords(SKILL_KEYWORD_MAP)

        # Query with synonyms that keywords wouldn't catch
        results = idx.search("render 2d game graphics on screen", top_k=5)
        assert len(results) > 0
        names = [name for name, _ in results]
        # Should find canvas or game-related skills
        assert any("canvas" in n or "game" in n for n in names)

    def test_skill_injector_uses_semantic(self):
        """detect_relevant_skills() now uses semantic matching."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills

        results = detect_relevant_skills("implementar sistema de audio con efectos de sonido", max_skills=5)
        assert isinstance(results, list)
        assert len(results) > 0
        # Should find audio-related skills
        assert any("audio" in name or "sound" in name for name in results)

    def test_surgical_store_semantic_search(self, tmp_path):
        """SurgicalStore.find_relevant() uses TF-IDF from semantic engine."""
        from deepseek_code.surgical.store import SurgicalStore

        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "integration_test"))
        store.add_error({"type": "truncation", "message": "response was truncated at 4000 tokens"})
        store.add_error({"type": "missing_todos", "message": "5 TODOs were not filled"})
        store.add_error({"type": "truncation", "message": "output cut off mid-function"})
        store.save()

        results = store.find_relevant("truncation cut off tokens", "error_log", top_k=2)
        assert len(results) > 0
        types = [r.get("type") for r in results]
        assert "truncation" in types

    def test_global_store_bayesian_stats(self, tmp_path):
        """GlobalStore computes Bayesian stats using BayesianEstimator."""
        from deepseek_code.global_memory.global_store import GlobalStore

        store = GlobalStore(str(tmp_path))
        store.load()
        for _ in range(8):
            store.update_skill_stat("test-skill", success=True, truncated=False)
        for _ in range(2):
            store.update_skill_stat("test-skill", success=False, truncated=True)

        stat = store.data["skill_stats"]["test-skill"]
        assert "bayesian_mean" in stat
        # 8 successes, 2 failures: Beta(9,3) -> mean = 9/12 = 0.75
        assert 0.6 < stat["bayesian_mean"] < 0.9
        assert stat["bayesian_ci_lower"] < stat["bayesian_mean"]
        assert stat["bayesian_mean"] < stat["bayesian_ci_upper"]

    def test_predictor_bayesian_risk(self):
        """HealthReport includes Bayesian risk score."""
        from deepseek_code.intelligence.predictor import generate_health_report

        store_data = {
            "project_name": "integration",
            "error_log": [
                {"type": "truncation", "timestamp": "2026-02-01T12:00:00"},
            ],
            "delegation_history": [
                {"success": True, "duration_s": 30, "timestamp": "2026-02-01T12:00:00"},
                {"success": True, "duration_s": 25, "timestamp": "2026-02-02T12:00:00"},
                {"success": False, "duration_s": 60, "timestamp": "2026-02-03T12:00:00"},
            ],
        }
        report = generate_health_report(store_data=store_data)
        d = report.to_dict()
        assert "bayesian_risk_score" in d
        assert "confidence_intervals" in d
        assert "trend_slopes" in d
        assert 0 <= d["bayesian_risk_score"] <= 100

    def test_all_components_use_same_engine(self):
        """Verify all subsystems import from the same semantic_engine module."""
        from deepseek_code.intelligence import semantic_engine
        from deepseek_code.skills.semantic_skill_index import SemanticSkillIndex

        # The vectorizer in SemanticSkillIndex should be the same class
        idx = SemanticSkillIndex()
        assert isinstance(idx._vectorizer, semantic_engine.TFIDFVectorizer)

    def test_temporal_decay_in_memory(self, tmp_path):
        """SurgicalStore uses temporal_decay for smart compaction."""
        from deepseek_code.surgical.store import SurgicalStore
        from datetime import datetime, timedelta

        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "decay_test"))

        # Recent entry should have higher relevance than old entry
        now = datetime.now()
        recent = {"type": "Error", "timestamp": now.isoformat()}
        old = {"type": "Error", "timestamp": (now - timedelta(days=60)).isoformat()}

        recent_score = store._entry_relevance(recent)
        old_score = store._entry_relevance(old)
        assert recent_score > old_score
