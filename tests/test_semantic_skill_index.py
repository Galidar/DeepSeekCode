"""Tests para Semantic Skill Index — matching semantico de skills con TF-IDF."""
import pytest
from deepseek_code.skills.semantic_skill_index import SemanticSkillIndex


class TestSemanticSkillIndex:
    def _make_keyword_map(self):
        return {
            "canvas-2d-reference": ["canvas", "2d", "draw", "fillRect", "ctx", "render"],
            "physics-simulation": ["physics", "collision", "gravity", "velocity", "rigid body"],
            "web-audio-api": ["audio", "sound", "music", "oscillator", "frequency"],
            "game-genre-patterns": ["rpg", "platformer", "shooter", "roguelike", "tower defense"],
            "database-patterns": ["database", "sql", "mongo", "redis", "orm", "query"],
        }

    def test_build_index(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        assert len(idx._corpus_vectors) == 5

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

    def test_search_returns_scores_in_range(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("canvas drawing graphics", top_k=3)
        assert all(0.0 <= score <= 1.0 for _, score in results)
        # Results should be sorted descending by score
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_with_boost(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        skill_stats = {
            "canvas-2d-reference": {"injected": 10, "with_success": 9},
            "physics-simulation": {"injected": 10, "with_success": 2},
        }
        results = idx.search_with_boost(
            "render game graphics on screen", top_k=5, skill_stats=skill_stats
        )
        # Canvas should rank higher due to Bayesian boost (90% success vs 20%)
        names = [name for name, score in results]
        if "canvas-2d-reference" in names and "physics-simulation" in names:
            assert names.index("canvas-2d-reference") < names.index("physics-simulation")

    def test_empty_query(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("", top_k=3)
        assert results == []

    def test_no_match_returns_low_scores(self):
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        results = idx.search("kubernetes docker deployment containers yaml", top_k=3)
        for _, score in results:
            assert score < 0.5

    def test_build_from_full_keyword_map(self):
        """Test with the real SKILL_KEYWORD_MAP from the project."""
        from deepseek_code.skills.skill_constants import SKILL_KEYWORD_MAP
        idx = SemanticSkillIndex()
        idx.build_from_keywords(SKILL_KEYWORD_MAP)
        assert len(idx._corpus_vectors) == len(SKILL_KEYWORD_MAP)
        # Search should work with the full map
        results = idx.search("create a 2d platformer game with physics", top_k=5)
        assert len(results) > 0

    def test_search_synonym_matching(self):
        """TF-IDF should handle related terms better than exact keywords."""
        idx = SemanticSkillIndex()
        idx.build_from_keywords(self._make_keyword_map())
        # "draw" and "render" are in canvas keywords — shared terms should help
        results = idx.search("draw 2d canvas game render", top_k=3)
        names = [name for name, score in results]
        assert "canvas-2d-reference" in names
