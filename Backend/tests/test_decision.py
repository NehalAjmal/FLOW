
import pytest

from engine.decision import DecisionEngine


def test_deep_work_reachable():
    engine = DecisionEngine()

    result = engine.compute(
        fatigue=0.05,
        deviation=0.05,
        ultradian=0.10,
        biometric=0.90,
    )

    assert result["state"] == "deep_work"
    assert result["focus_score"] >= 0.75


def test_missing_biometric_renormalized():
    engine = DecisionEngine()

    result = engine.compute(
        fatigue=0.0,
        deviation=0.0,
        ultradian=0.0,
        biometric=None,
    )

    assert result["focus_score"] == 1.0

    weights = [
        signal["weight"]
        for signal in result["contributions"].values()
    ]

    assert sum(weights) == pytest.approx(1.0)


def test_ultradian_pressure_reduces_score():
    engine = DecisionEngine()

    early = engine.compute(
        fatigue=0.1,
        deviation=0.1,
        ultradian=0.0,
        biometric=None,
    )

    late = engine.compute(
        fatigue=0.1,
        deviation=0.1,
        ultradian=1.0,
        biometric=None,
    )

    assert (
        early["focus_score"]
        > late["focus_score"]
    )


def test_fatigue_reduces_score():
    engine = DecisionEngine()

    rested = engine.compute(
        fatigue=0.0,
        deviation=0.1,
        ultradian=0.1,
    )

    tired = engine.compute(
        fatigue=0.9,
        deviation=0.1,
        ultradian=0.1,
    )

    assert (
        rested["focus_score"]
        > tired["focus_score"]
    )


def test_severe_fatigue_blocks_deep_work():
    engine = DecisionEngine()

    result = engine.compute(
        fatigue=0.9,
        deviation=0.0,
        ultradian=0.0,
        biometric=1.0,
    )

    assert result["state"] != "deep_work"


def test_no_signals():
    engine = DecisionEngine()

    result = engine.compute()

    assert result["state"] == "unknown"
    assert result["focus_score"] is None


def test_trough_penalty():
    engine = DecisionEngine()

    normal = engine.compute(
        fatigue=0.1,
        deviation=0.1,
        ultradian=0.1,
        trough_pressure=0.0,
    )

    trough = engine.compute(
        fatigue=0.1,
        deviation=0.1,
        ultradian=0.1,
        trough_pressure=1.0,
    )

    assert (
        normal["focus_score"]
        > trough["focus_score"]
    )


def test_invalid_signal():
    engine = DecisionEngine()

    with pytest.raises(ValueError):
        engine.compute(fatigue=float("nan"))


def test_score_bounds():
    engine = DecisionEngine()

    result = engine.compute(
        fatigue=2.0,
        deviation=-1.0,
        ultradian=3.0,
        biometric=0.5,
        trough_pressure=1.0,
    )

    assert 0.0 <= result["focus_score"] <= 1.0
