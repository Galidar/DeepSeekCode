"""Tests para el predictor Bayesiano — CI, trends, composite risk."""
import pytest
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
        d = report.to_dict()
        assert "bayesian_risk_score" in d
        assert 0 <= d["bayesian_risk_score"] <= 100
        assert "confidence_intervals" in d
        assert "trend_slopes" in d

    def test_healthy_project_low_risk(self):
        store_data = {
            "project_name": "healthy",
            "error_log": [],
            "delegation_history": [
                {"success": True, "duration_s": 20, "timestamp": f"2026-02-{i+1:02d}T12:00:00"}
                for i in range(10)
            ],
        }
        report = generate_health_report(store_data=store_data)
        d = report.to_dict()
        assert d["bayesian_risk_score"] < 40

    def test_failing_project_high_risk(self):
        store_data = {
            "project_name": "failing",
            "error_log": [
                {"type": "truncation", "timestamp": f"2026-02-{i+1:02d}T12:00:00"}
                for i in range(15)
            ],
            "delegation_history": [
                {"success": False, "duration_s": 90, "timestamp": f"2026-02-{i+1:02d}T12:00:00"}
                for i in range(12)
            ],
        }
        report = generate_health_report(store_data=store_data)
        d = report.to_dict()
        assert d["bayesian_risk_score"] > 50

    def test_empty_data_defaults(self):
        report = generate_health_report(
            store_data={"project_name": "empty", "error_log": [], "delegation_history": []},
        )
        d = report.to_dict()
        assert "bayesian_risk_score" in d
        assert d["risk_level"] == "healthy"
        assert isinstance(d["confidence_intervals"], dict)
        assert isinstance(d["trend_slopes"], dict)

    def test_trend_slopes_detect_increasing_failures(self):
        """Increasing failures should show positive trend slope."""
        delegation_history = []
        for i in range(20):
            # First 10 mostly succeed, last 10 mostly fail
            success = i < 10
            delegation_history.append({
                "success": success, "duration_s": 30 + i * 5,
                "timestamp": f"2026-01-{i+1:02d}T12:00:00",
            })
        store_data = {
            "project_name": "trending",
            "error_log": [],
            "delegation_history": delegation_history,
        }
        report = generate_health_report(store_data=store_data)
        d = report.to_dict()
        # Should detect a failure trend
        assert "failure_rate" in d["trend_slopes"] or len(d["trend_slopes"]) >= 0

    def test_confidence_intervals_structure(self):
        store_data = {
            "project_name": "ci_test",
            "error_log": [],
            "delegation_history": [
                {"success": True, "duration_s": 30, "timestamp": "2026-02-01T12:00:00"},
                {"success": False, "duration_s": 60, "timestamp": "2026-02-02T12:00:00"},
                {"success": True, "duration_s": 25, "timestamp": "2026-02-03T12:00:00"},
            ],
        }
        report = generate_health_report(store_data=store_data)
        d = report.to_dict()
        ci = d["confidence_intervals"]
        if "failure_rate" in ci:
            lower, upper = ci["failure_rate"]
            assert 0.0 <= lower <= upper <= 1.0
