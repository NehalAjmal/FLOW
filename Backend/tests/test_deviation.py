import pytest

from engine.deviation import DeviationEngine


def test_score_range():
    engine = DeviationEngine()

    score = engine.compute(
        keystrokes=20,
        switches=2,
        idle_seconds=5,
    )

    assert 0.0 <= score <= 1.0


def test_difficulty_changes_score():
    light = DeviationEngine()
    heavy = DeviationEngine()

    light_score = light.compute(
        keystrokes=10,
        switches=2,
        idle_seconds=5,
        declared_difficulty="light",
    )

    heavy_score = heavy.compute(
        keystrokes=10,
        switches=2,
        idle_seconds=5,
        declared_difficulty="heavy",
    )

    assert light_score != heavy_score


def test_high_switching_increases_deviation():
    focused = DeviationEngine()
    distracted = DeviationEngine()

    focused_score = focused.compute(
        20, 0, 0, "moderate"
    )

    distracted_score = distracted.compute(
        20, 10, 0, "moderate"
    )

    assert distracted_score > focused_score


def test_idle_increases_deviation():
    active = DeviationEngine()
    idle = DeviationEngine()

    active_score = active.compute(
        20, 0, 0, "moderate"
    )

    idle_score = idle.compute(
        20, 0, 30, "moderate"
    )

    assert idle_score > active_score


def test_invalid_difficulty():
    engine = DeviationEngine()

    with pytest.raises(ValueError):
        engine.compute(
            10, 2, 5, "extreme"
        )


def test_negative_activity():
    engine = DeviationEngine()

    with pytest.raises(ValueError):
        engine.compute(
            -10, 2, 5
        )


def test_history_limited_to_ten():
    engine = DeviationEngine()

    for _ in range(15):
        engine.compute(20, 1, 2)

    assert len(engine.history) == 10


def test_reset_clears_history():
    engine = DeviationEngine()

    engine.compute(20, 1, 2)
    engine.reset()

    assert len(engine.history) == 0
