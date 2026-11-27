import pytest

from engine.adaptive_threshold import AdaptiveThresholdEngine


def test_default_threshold():
    engine = AdaptiveThresholdEngine()

    assert engine.get_threshold() == 0.65


def test_custom_threshold():
    engine = AdaptiveThresholdEngine(0.70)

    assert engine.get_threshold() == 0.70


def test_accepted_increases_threshold():
    engine = AdaptiveThresholdEngine()

    assert engine.update("accepted") == 0.67


def test_dismissed_decreases_threshold():
    engine = AdaptiveThresholdEngine()

    assert engine.update("dismissed") == 0.63


def test_ignored_preserves_threshold():
    engine = AdaptiveThresholdEngine()

    assert engine.update("ignored") == 0.65


def test_upper_threshold_limit():
    engine = AdaptiveThresholdEngine()

    for _ in range(100):
        engine.update("accepted")

    assert engine.get_threshold() == 0.80


def test_lower_threshold_limit():
    engine = AdaptiveThresholdEngine()

    for _ in range(100):
        engine.update("dismissed")

    assert engine.get_threshold() == 0.50


def test_initial_threshold_clamped():
    assert AdaptiveThresholdEngine(0.95).get_threshold() == 0.80
    assert AdaptiveThresholdEngine(0.20).get_threshold() == 0.50


def test_low_focus_triggers_intervention():
    engine = AdaptiveThresholdEngine()

    assert engine.should_intervene(0.40) is True


def test_high_focus_does_not_trigger_intervention():
    engine = AdaptiveThresholdEngine()

    assert engine.should_intervene(0.90) is False


def test_threshold_boundary():
    engine = AdaptiveThresholdEngine()

    assert engine.should_intervene(0.65) is False
    assert engine.should_intervene(0.6499) is True


def test_missing_focus_score():
    engine = AdaptiveThresholdEngine()

    assert engine.should_intervene(None) is False


def test_adaptation_changes_intervention_decision():
    engine = AdaptiveThresholdEngine()

    assert engine.should_intervene(0.66) is False

    engine.update("accepted")

    assert engine.should_intervene(0.66) is True


def test_engine_instances_are_isolated():
    user_a = AdaptiveThresholdEngine()
    user_b = AdaptiveThresholdEngine()

    user_a.update("accepted")
    user_b.update("dismissed")

    assert user_a.get_threshold() == 0.67
    assert user_b.get_threshold() == 0.63


def test_invalid_response():
    engine = AdaptiveThresholdEngine()

    with pytest.raises(ValueError):
        engine.update("invalid")


def test_invalid_threshold():
    with pytest.raises(ValueError):
        AdaptiveThresholdEngine(float("nan"))


def test_invalid_focus_score():
    engine = AdaptiveThresholdEngine()

    for score in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            engine.should_intervene(score)


def test_reset_threshold():
    engine = AdaptiveThresholdEngine()

    engine.update("accepted")
    engine.update("accepted")

    assert engine.reset() == 0.65

from learning.engine import PatternLearner
from datetime import datetime, timedelta, timezone
from interventions.gating import check_gate


def test_threshold_survives_pattern_learning():
    previous_model = {
        "schema_version": "learning_v3",
        "parameters": {
            "adaptive_threshold": 0.73
        }
    }

    session_data = [
        {
            "timestamp": "2026-11-25T10:00:00",
            "input": {
                "keystroke_count": 20,
                "window_switches": 2,
                "idle_seconds": 5
            },
            "output": {
                "fatigue": 0.2,
                "deviation": 0.1
            }
        }
    ]

    updated_model = PatternLearner().update(
        previous_model,
        session_data
    )

    assert updated_model["parameters"]["adaptive_threshold"] == 0.73


def test_threshold_restored_from_saved_model():
    saved_model = {
        "parameters": {
            "adaptive_threshold": 0.71
        }
    }

    engine = AdaptiveThresholdEngine(
        saved_model["parameters"]["adaptive_threshold"]
    )

    assert engine.get_threshold() == 0.71


def test_threshold_with_empty_session():
    previous_model = {
        "parameters": {
            "adaptive_threshold": 0.69
        }
    }

    updated_model = PatternLearner().update(
        previous_model,
        []
    )

    assert updated_model["parameters"]["adaptive_threshold"] == 0.69


def test_adaptive_threshold_respects_prompt_gating():
    engine = AdaptiveThresholdEngine()

    now = datetime.now(timezone.utc)
    focus_score = 0.40

    assert engine.should_intervene(focus_score)

    blocked = check_gate(
        now,
        last_prompt_at=now - timedelta(minutes=14)
    )

    allowed = check_gate(
        now,
        last_prompt_at=now - timedelta(minutes=15)
    )

    assert not blocked.allowed
    assert allowed.allowed
