import itertools

import pytest

from engine.decision import DecisionEngine
from engine.explainer import build_explanation


SIGNALS = {
    "deviation": 0.70,
    "fatigue": 0.60,
    "ultradian": 0.40,
    "biometric": 0.80,
}


def explain(
    signals=None,
    threshold=0.65,
    trough=0.0,
    trigger="sustained_low_focus",
):
    if signals is None:
        signals = SIGNALS

    decision = DecisionEngine().compute(
        **signals,
        trough_pressure=trough,
    )

    return build_explanation(
        decision=decision,
        state=decision["state"],
        focus_score=decision["focus_score"],
        adaptive_threshold=threshold,
        trough_pressure=trough,
        trigger=trigger,
        minutes_in_state=6.0,
    )


def test_all_four_signals():
    result = explain()

    assert result["decision_source"] == "weighted_fusion"
    assert result["focus_score"] == pytest.approx(0.44)
    assert result["weighted_score"] == pytest.approx(0.44)

    expected = {
        "deviation": (0.70, 0.30, 0.40, 0.12),
        "fatigue": (0.60, 0.40, 0.30, 0.12),
        "ultradian": (0.40, 0.60, 0.20, 0.12),
        "biometric": (0.80, 0.80, 0.10, 0.08),
    }

    for name, values in expected.items():
        signal = result["signals"][name]

        assert signal["available"] is True

        actual = (
            signal["raw_value"],
            signal["focus_value"],
            signal["weight"],
            signal["contribution"],
        )

        assert actual == pytest.approx(values)


COMBINATIONS = [
    combination
    for count in range(1, 5)
    for combination in itertools.combinations(
        SIGNALS.keys(), count
    )
]


@pytest.mark.parametrize("available", COMBINATIONS)
def test_all_signal_combinations(available):
    inputs = {
        name: value if name in available else None
        for name, value in SIGNALS.items()
    }

    result = explain(inputs)

    weights = []
    contributions = []

    for name, signal in result["signals"].items():
        if name in available:
            assert signal["available"] is True

            weights.append(signal["weight"])
            contributions.append(
                signal["contribution"]
            )

            assert signal["raw_value"] == pytest.approx(
                SIGNALS[name]
            )

            assert signal["contribution"] == pytest.approx(
                signal["weight"] * signal["focus_value"],
                abs=2e-6,
            )

        else:
            assert signal["available"] is False
            assert signal["raw_value"] is None
            assert signal["focus_value"] is None
            assert signal["weight"] is None
            assert signal["contribution"] is None

    assert sum(weights) == pytest.approx(
        1.0, abs=4e-6
    )

    assert sum(contributions) == pytest.approx(
        result["weighted_score"],
        abs=4e-6,
    )


@pytest.mark.parametrize(
    "trough,expected_penalty",
    [
        (0.0, 0.0),
        (0.3, 0.06),
        (0.6, 0.12),
        (0.9, 0.18),
        (1.0, 0.20),
        (2.0, 0.20),
        (-1.0, 0.0),
    ],
)
def test_trough_penalty(trough, expected_penalty):
    result = explain(trough=trough)

    assert result["trough_penalty"] == pytest.approx(
        expected_penalty
    )

    reconstructed = max(
        0.0,
        min(
            1.0,
            result["weighted_score"]
            - result["trough_penalty"],
        ),
    )

    assert result["focus_score"] == pytest.approx(
        reconstructed,
        abs=1e-4,
    )


def test_score_clamped_to_zero():
    result = explain(
        {
            "deviation": 1.0,
            "fatigue": 1.0,
            "ultradian": 1.0,
            "biometric": 0.0,
        },
        trough=1.0,
    )

    assert result["weighted_score"] == 0.0
    assert result["trough_penalty"] == 0.20
    assert result["focus_score"] == 0.0


def test_fallback_has_no_fake_contributions():
    result = build_explanation(
        decision=None,
        state="stuck",
        focus_score=0.35,
        adaptive_threshold=0.65,
        trough_pressure=0.0,
        trigger="sustained_low_focus",
        minutes_in_state=6.0,
    )

    assert result["decision_source"] == "fallback"
    assert result["weighted_score"] is None
    assert result["trough_penalty"] is None

    for signal in result["signals"].values():
        assert signal["available"] is False
        assert signal["contribution"] is None
        assert signal["weight"] is None

    assert "fallback" in result["reason"].lower()


def test_predictive_trough_above_threshold():
    result = explain(
        {
            "deviation": 0.0,
            "fatigue": 0.0,
            "ultradian": 0.0,
            "biometric": 1.0,
        },
        threshold=0.65,
        trough=0.9,
        trigger="predicted_trough",
    )

    assert result["trigger"] == "predicted_trough"
    assert result["below_threshold"] is False
    assert result["focus_score"] == pytest.approx(0.82)
    assert "preventive break" in result["reason"]


@pytest.mark.parametrize(
    "threshold,expected",
    [
        (0.55, False),
        (0.60, False),
        (0.65, True),
        (0.80, True),
    ],
)
def test_threshold_comparison(threshold, expected):
    result = explain(
        {
            "deviation": 0.40,
            "fatigue": None,
            "ultradian": None,
            "biometric": None,
        },
        threshold=threshold,
        trigger="predicted_trough",
    )

    assert result["focus_score"] == pytest.approx(0.60)
    assert result["below_threshold"] is expected


def test_raw_values_are_normalized():
    result = explain(
        {
            "deviation": -1.0,
            "fatigue": 2.0,
            "ultradian": 0.5,
            "biometric": 3.0,
        }
    )

    assert result["signals"]["deviation"]["raw_value"] == 0.0
    assert result["signals"]["fatigue"]["raw_value"] == 1.0
    assert result["signals"]["biometric"]["raw_value"] == 1.0


def test_explanation_is_independent_of_decision():
    decision = DecisionEngine().compute(**SIGNALS)

    result = build_explanation(
        decision=decision,
        state=decision["state"],
        focus_score=decision["focus_score"],
        adaptive_threshold=0.65,
        trough_pressure=0.0,
        trigger="sustained_low_focus",
        minutes_in_state=6.0,
    )

    decision["contributions"]["fatigue"]["value"] = 0.99

    assert result["signals"]["fatigue"]["focus_value"] == 0.40
