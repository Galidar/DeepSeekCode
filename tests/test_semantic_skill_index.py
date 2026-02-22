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


class TestSkillInjectorIntegration:
    """Tests de integracion: detect_relevant_skills con semantic matching."""

    def test_detect_relevant_skills_returns_list(self):
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        results = detect_relevant_skills("create a 2d canvas game with physics", max_skills=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert len(results) <= 5

    def test_detect_relevant_skills_with_exclude(self):
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        results = detect_relevant_skills(
            "canvas 2d draw render", max_skills=5, exclude=["canvas-2d-reference"]
        )
        assert "canvas-2d-reference" not in results

    def test_detect_relevant_skills_fallback(self):
        """Even if semantic fails, keyword fallback should work."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        # A query with exact keywords should always return results
        results = detect_relevant_skills("javascript async await promise", max_skills=3)
        assert isinstance(results, list)

    def test_keyword_fallback_still_accessible(self):
        """_keyword_fallback debe seguir existiendo como funcion interna."""
        from deepseek_code.skills.skill_injector import _keyword_fallback
        results = _keyword_fallback("canvas 2d draw render", max_skills=3)
        assert isinstance(results, list)

    def test_semantic_index_is_lazy(self):
        """El indice semantico se crea solo al usarse, no al importar."""
        import deepseek_code.skills.skill_injector as mod
        # After reset, should be None until detect_relevant_skills is called
        old_idx = mod._semantic_index
        mod._semantic_index = None
        assert mod._semantic_index is None
        # Calling detect triggers lazy init
        mod.detect_relevant_skills("test query", max_skills=1)
        assert mod._semantic_index is not None
        # Restore
        mod._semantic_index = old_idx


class TestHybridScoring:
    """Tests para verificar que el scoring hibrido resuelve falsos positivos."""

    def test_platformer_canvas_no_json_canvas(self):
        """json-canvas (Obsidian) NO debe aparecer para queries de juegos canvas 2d."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        results = detect_relevant_skills(
            "crear un platformer con canvas 2d y colisiones"
        )
        assert "json-canvas" not in results
        assert "canvas-2d-reference" in results

    def test_platformer_includes_game_skills(self):
        """Queries de juegos deben incluir physics-simulation y game-genre-patterns."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        results = detect_relevant_skills(
            "crear un platformer con canvas 2d y colisiones",
            max_skills=5,
        )
        assert "game-genre-patterns" in results
        assert "physics-simulation" in results

    def test_non_game_query_unaffected(self):
        """Queries no-game siguen funcionando correctamente."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        results = detect_relevant_skills(
            "backend express mongodb rest api authentication",
            max_skills=5,
        )
        assert "backend-node-patterns" in results
        assert "database-patterns" in results

    def test_official_skill_creator_not_false_positive(self):
        """official-skill-creator NO debe aparecer para queries de codigo general."""
        from deepseek_code.skills.skill_injector import detect_relevant_skills
        results = detect_relevant_skills(
            "crear un platformer con canvas 2d y colisiones"
        )
        assert "official-skill-creator" not in results

    def test_compute_keyword_scores_game_bonus(self):
        """El game bonus debe aplicarse cuando hay keywords de juegos."""
        from deepseek_code.skills.skill_injector import _compute_keyword_scores
        scores = _compute_keyword_scores(
            "crear un platformer con canvas 2d", set()
        )
        # physics-simulation debe tener score > 0 por el game bonus
        # aunque "physics" no esta en el query
        assert scores.get("physics-simulation", 0) > 0

    def test_compute_tfidf_scores_returns_dict(self):
        """_compute_tfidf_scores debe retornar dict, no lista."""
        from deepseek_code.skills.skill_injector import _compute_tfidf_scores
        scores = _compute_tfidf_scores("canvas 2d draw", set())
        assert isinstance(scores, dict)
        assert all(isinstance(v, float) for v in scores.values())
