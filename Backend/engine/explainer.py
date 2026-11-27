from typing import Optional
from engine.decision import DecisionEngine

SIGNAL_NAMES = (
    "deviation",
    "fatigue",
    "ultradian",
    "biometric",
)


def build_explanation(
    *,
    decision: Optional[dict],
    state: str,
    focus_score: float,
    adaptive_threshold: float,
    trough_pressure: float,
    trigger: str,
    minutes_in_state: float,
) -> dict:

    trough_pressure = DecisionEngine._normalize(
        trough_pressure,
        "trough_pressure"
    )

    if trough_pressure is None:
        trough_pressure = 0.0


    below_threshold = focus_score < adaptive_threshold

    contributions = (
        decision.get("contributions", {})
        if decision is not None
        else {}
    )

    weighted_fusion = bool(contributions)

    signals = {}

    for name in SIGNAL_NAMES:

        item = contributions.get(name)

        if item is None:
            signals[name] = {
                "available": False,
                "raw_value": None,
                "focus_value": None,
                "weight": None,
                "contribution": None,
            }
            continue

        value = float(item["value"])

        raw_value = (
            value
            if name == "biometric"
            else 1.0 - value
        )

        signals[name] = {
            "available": True,
            "raw_value": round(raw_value, 6),
            "focus_value": round(value, 6),
            "weight": round(item["weight"], 6),
            "contribution": round(
                item["contribution"], 6
            ),
        }

    weighted_score = (
        sum(
            item["contribution"]
            for item in contributions.values()
        )
        if weighted_fusion
        else None
    )

    trough_penalty = (
        trough_pressure * 0.20
        if weighted_fusion
        else None
    )

    reasons = []

    if trigger == "predicted_trough":
        reasons.append(
            "A predicted focus dip is approaching. "
            "FLOW recommends a preventive break."
        )

    elif trigger == "sustained_low_focus":
        reasons.append(
            f"Focus is below the personalized "
            f"threshold of {adaptive_threshold:.0%}. "
            f"The {state} state has lasted "
            f"{minutes_in_state:.1f} minutes."
        )

    if not weighted_fusion:
        reasons.append(
            "The fallback scoring method was used. "
            "Weighted signal contributions are unavailable."
        )

    else:
        available_signals = {
            name: item
            for name, item in signals.items()
            if item["available"]
        }

        if available_signals:

            weakest_signal = max(
                available_signals,
                key=lambda name: (
                    available_signals[name]["weight"]
                    * (
                        1.0
                        - available_signals[name]["focus_value"]
                    )
                ),
            )

            descriptions = {
                "deviation": (
                    "Activity differed from the expected "
                    "task engagement pattern."
                ),
                "fatigue": (
                    "The fatigue signal reduced "
                    "the estimated focus score."
                ),
                "ultradian": (
                    "Elapsed time in the work cycle "
                    "reduced the estimated focus score."
                ),
                "biometric": (
                    "Measured biometric readiness "
                    "reduced the estimated focus score."
                ),
            }

            if available_signals[weakest_signal]["focus_value"] < 1:
                reasons.append(
                    descriptions[weakest_signal]
                )

        if trough_pressure > 0:
            reasons.append(
                "Predicted trough pressure applied "
                "an additional focus-score penalty."
            )

    return {
        "schema_version": "1.0",
        "decision_source": (
            "weighted_fusion"
            if weighted_fusion
            else "fallback"
        ),
        "trigger": trigger,
        "state": state,
        "focus_score": round(focus_score, 4),
        "adaptive_threshold": round(
            adaptive_threshold, 4
        ),
        "below_threshold": below_threshold,
        "minutes_in_state": round(
            minutes_in_state, 2
        ),
        "weighted_score": (
            round(weighted_score, 6)
            if weighted_score is not None
            else None
        ),
        "trough_pressure": round(
            trough_pressure, 4
        ),
        "trough_penalty": (
            round(trough_penalty, 6)
            if trough_penalty is not None
            else None
        ),
        "signals": signals,
        "reason": " ".join(reasons),
    }
