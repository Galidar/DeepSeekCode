"""Tests para memoria inteligente — decay temporal y busqueda semantica."""
import os
import json
import pytest
from datetime import datetime, timedelta
from deepseek_code.surgical.store import SurgicalStore


class TestSurgicalStoreFindRelevant:
    """Tests para busqueda semantica en SurgicalStore."""

    def test_find_relevant_errors_by_content(self, tmp_path):
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        store.add_error({"type": "TypeError", "message": "Cannot read property of undefined"})
        store.add_error({"type": "SyntaxError", "message": "Unexpected token }"})
        store.add_error({"type": "TypeError", "message": "null is not an object"})
        store.save()

        results = store.find_relevant("undefined null type errors", "error_log", top_k=2)
        assert len(results) <= 2
        # Should prefer TypeErrors over SyntaxError (more semantically similar)
        types = [r.get("type") for r in results]
        assert "TypeError" in types

    def test_find_relevant_empty_section(self, tmp_path):
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        results = store.find_relevant("anything", "error_log", top_k=5)
        assert results == []

    def test_find_relevant_empty_query(self, tmp_path):
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        store.add_error({"type": "Error", "message": "something failed"})
        results = store.find_relevant("", "error_log", top_k=5)
        assert results == []

    def test_find_relevant_delegation_history(self, tmp_path):
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        store.add_delegation({"task": "crear sistema de combate", "success": True})
        store.add_delegation({"task": "implementar login con JWT", "success": True})
        store.add_delegation({"task": "agregar particulas al combate", "success": False})
        store.save()

        results = store.find_relevant("combate pelea battle", "delegation_history", top_k=2)
        assert len(results) <= 2
        tasks = [r.get("task", "") for r in results]
        # At least one combat-related task should appear
        assert any("combate" in t for t in tasks)


class TestSurgicalStoreSmartCompact:
    """Tests para compactacion inteligente con decay temporal."""

    def test_compact_keeps_max_entries(self, tmp_path):
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        for i in range(40):
            store.add_error({"type": f"Error{i}", "message": f"error {i}"})
        store.save()
        assert len(store.data["error_log"]) <= 30

    def test_compact_prefers_frequent_patterns(self, tmp_path):
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))
        # Add a pattern used many times
        for _ in range(5):
            store.add_pattern({"name": "frequently_used", "description": "used a lot"})
        # Add many patterns used once
        for i in range(20):
            store.add_pattern({"name": f"rare_pattern_{i}", "description": f"rare {i}"})
        store.save()

        # The frequently used pattern should survive compaction
        names = [p["name"] for p in store.data["patterns"]]
        assert "frequently_used" in names

    def test_relevance_score_method(self, tmp_path):
        """Test that _entry_relevance returns a float score."""
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))

        entry = {
            "type": "Error",
            "message": "test error",
            "timestamp": datetime.now().isoformat(),
        }
        score = store._entry_relevance(entry)
        assert isinstance(score, float)
        assert score >= 0.0

    def test_old_entries_have_lower_relevance(self, tmp_path):
        """Older entries should have lower relevance due to decay."""
        store = SurgicalStore(str(tmp_path))
        store.load(str(tmp_path / "test_project"))

        now = datetime.now()
        recent_entry = {
            "type": "Error", "message": "recent",
            "timestamp": now.isoformat(),
        }
        old_entry = {
            "type": "Error", "message": "old",
            "timestamp": (now - timedelta(days=90)).isoformat(),
        }

        recent_score = store._entry_relevance(recent_entry)
        old_score = store._entry_relevance(old_entry)
        assert recent_score > old_score


class TestGlobalStoreBayesian:
    """Tests para GlobalStore con stats Bayesianos."""

    def test_bayesian_skill_stat(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        store.update_skill_stat("canvas-2d", success=True, truncated=False)
        store.update_skill_stat("canvas-2d", success=True, truncated=False)
        store.update_skill_stat("canvas-2d", success=False, truncated=True)
        store.save()

        stat = store.data["skill_stats"]["canvas-2d"]
        assert "bayesian_mean" in stat
        assert 0.0 <= stat["bayesian_mean"] <= 1.0
        # 2 successes, 1 failure: Beta(3,2) -> mean = 3/5 = 0.6
        assert stat["bayesian_mean"] > 0.5

    def test_bayesian_with_few_data_points(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        store.update_skill_stat("new-skill", success=True, truncated=False)
        stat = store.data["skill_stats"]["new-skill"]
        # With 1 success: Beta(2,1) -> mean = 2/3 ≈ 0.667
        assert "bayesian_mean" in stat
        assert 0.5 < stat["bayesian_mean"] < 0.8

    def test_bayesian_confidence(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        for _ in range(20):
            store.update_skill_stat("well-tested", success=True, truncated=False)
        stat = store.data["skill_stats"]["well-tested"]
        assert "bayesian_ci_lower" in stat
        assert "bayesian_ci_upper" in stat
        # 20 successes, 0 failures — confidence should be high
        assert stat["bayesian_ci_lower"] > 0.7

    def test_semantic_error_clustering(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        store.add_cross_error("TypeError: undefined is not a function", "project_a")
        store.add_cross_error("TypeError: Cannot read property of undefined", "project_b")
        store.save()

        # Both are TypeError related to undefined — should exist in errors
        errors = store.data["cross_project_errors"]
        assert len(errors) >= 1  # At least 1 (could merge or keep separate)
        # The total count across all matching errors should be >= 2
        total = sum(e.get("count", 0) for e in errors)
        assert total >= 2

    def test_exact_match_still_works(self, tmp_path):
        from deepseek_code.global_memory.global_store import GlobalStore
        store = GlobalStore(str(tmp_path))
        store.load()
        store.add_cross_error("truncation", "project_a")
        store.add_cross_error("truncation", "project_b")
        errors = store.data["cross_project_errors"]
        # Exact match should increment count
        truncation_errors = [e for e in errors if e["type"] == "truncation"]
        assert len(truncation_errors) == 1
        assert truncation_errors[0]["count"] == 2
        assert len(truncation_errors[0]["projects"]) == 2
