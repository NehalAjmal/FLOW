
import pytest

from engine.ultradian import UltradianEngine


def test_initial_score():
    engine = UltradianEngine()
    assert engine.compute() == 0.0


def test_half_cycle(monkeypatch):
    engine = UltradianEngine(90)
    engine.start_time = 1000

    monkeypatch.setattr(
        "engine.ultradian.time.time",
        lambda: 1000 + 45 * 60
    )

    assert engine.compute() == 0.5


def test_full_cycle(monkeypatch):
    engine = UltradianEngine(90)
    engine.start_time = 1000

    monkeypatch.setattr(
        "engine.ultradian.time.time",
        lambda: 1000 + 90 * 60
    )

    assert engine.compute() == 1.0


def test_no_automatic_reset(monkeypatch):
    engine = UltradianEngine(90)
    engine.start_time = 1000

    monkeypatch.setattr(
        "engine.ultradian.time.time",
        lambda: 1000 + 120 * 60
    )

    assert engine.compute() == 1.0


def test_invalid_cycle():
    with pytest.raises(ValueError):
        UltradianEngine(0)


def test_break_reset(monkeypatch):
    engine = UltradianEngine(90)
    engine.start_time = 1000

    monkeypatch.setattr(
        "engine.ultradian.time.time",
        lambda: 5000
    )

    engine.reset_after_break()

    assert engine.compute() == 0.0
