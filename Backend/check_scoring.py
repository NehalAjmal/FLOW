"""Checks for the scoring engine. Run from the Backend folder: python check_scoring.py"""
import itertools
from engine.ultradian import UltradianEngine
from engine.deviation import DeviationEngine
from engine.decision import DecisionEngine, compute_trough_pressure

passed = failed = 0


def check(label, ok, got=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {got}")


def raises_value_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return True
    return False


def score_after(minutes, cycle=90):
    engine = UltradianEngine(cycle_minutes=cycle)
    engine.start()
    engine.start_time -= minutes * 60
    return engine.compute()


print("\n1. Ultradian")
cases = [
    (0, 90, 0.0, "starts at 0"),
    (45, 90, 0.5, "halfway through 90 min is 0.5"),
    (90, 90, 1.0, "full cycle is 1.0"),
    (150, 90, 1.0, "capped at 1 after the cycle"),
    (45, 60, 0.75, "uses the personal cycle (45 of 60 min)"),
]
for minutes, cycle, expected, label in cases:
    got = score_after(minutes, cycle)
    check(label, got == expected, f"got {got}")

engine = UltradianEngine()
engine.start()
engine.start_time -= 80 * 60
engine.reset_after_break()
check("goes back to 0 after a break", engine.compute() == 0.0)

scores = [score_after(m) for m in range(0, 121, 10)]
check("never goes down as time passes", scores == sorted(scores), scores)


print("\n2. Intent deviation")
one_tick = dict(keystrokes=10, switches=4, idle_seconds=12)
by_level = {lvl: DeviationEngine().compute(**one_tick, declared_difficulty=lvl)
            for lvl in ("light", "moderate", "heavy")}
check("light, moderate and heavy give different scores", len(set(by_level.values())) == 3, by_level)
check("same activity looks more off-task for heavy than light", by_level["heavy"] > by_level["light"])

focused = DeviationEngine().compute(30, 0, 2, "moderate")
check("focused typing is low (under 0.3)", focused < 0.3, f"got {focused}")

distracted = DeviationEngine().compute(0, 8, 28, "moderate")
check("idle and switching is high (over 0.7)", distracted > 0.7, f"got {distracted}")

check("rejects negative input",
      raises_value_error(DeviationEngine().compute, keystrokes=-1, switches=0, idle_seconds=0))

engine = DeviationEngine()
engine.compute(0, 8, 30, "moderate")
after = [engine.compute(30, 0, 2, "moderate") for _ in range(10)]
slow = sum(1 for s in after if s > after[-1] + 0.01)
print(f"  smoothing: {slow} focused ticks (about {slow / 2:.1f} min) are still pulled up by one distracted tick")


print("\n3. Score fusion")
fusion = DecisionEngine()
signal_names = ["fatigue", "deviation", "ultradian", "biometric"]
weights_ok = True
for size in range(1, 5):
    for present in itertools.combinations(signal_names, size):
        result = fusion.compute(**{n: 0.5 if n in present else None for n in signal_names})
        total = sum(c["weight"] for c in result["contributions"].values())
        if abs(total - 1.0) > 1e-9 or set(result["contributions"]) != set(present):
            weights_ok = False
            print(f"    bad weights for {present}: sum={total}")
check("weights sum to 1 for all 15 combinations of missing signals", weights_ok)
check("no signals gives state 'unknown'", fusion.compute()["state"] == "unknown")

result = fusion.compute(fatigue=0.4, deviation=0.2, ultradian=0.3, biometric=None)
used = list(result["contributions"])
check("fatigue counted once, no biometric without heart data",
      used.count("fatigue") == 1 and "biometric" not in used, used)

camera_off = fusion.compute(fatigue=None, deviation=0.1, ultradian=0.2, biometric=None)
check("deep work reachable with camera off", camera_off["state"] == "deep_work",
      f"score={camera_off['focus_score']} state={camera_off['state']}")

camera_on = fusion.compute(fatigue=0.2, deviation=0.15, ultradian=0.3, biometric=None)
check("deep work reachable with camera on and mild fatigue", camera_on["state"] == "deep_work",
      f"score={camera_on['focus_score']} state={camera_on['state']}")

tired = fusion.compute(fatigue=0.9, deviation=0.1, ultradian=0.1)
check("severe fatigue is never deep work", tired["state"] != "deep_work", f"state={tired['state']}")
check("rejects NaN", raises_value_error(fusion.compute, fatigue=float("nan")))


print("\n4. Trough penalty (dip at minute 45)")
trough = {m: compute_trough_pressure(m, 45) for m in (0, 25, 30, 38, 44, 45, 60, 90, 120)}
print(f"  {trough}")
check("pressure drops once the dip has passed", trough[90] < 0.5, f"minute 90: {trough[90]}")


print("\n5. Simulated 90-minute session (steady typing, camera off, moderate task)")
dev_engine, fusion = DeviationEngine(), DecisionEngine()
timeline = []
for tick in range(180):
    minute = tick // 2
    deviation = dev_engine.compute(25, 1, 3, "moderate")
    result = fusion.compute(deviation=deviation, ultradian=minute / 90,
                            trough_pressure=compute_trough_pressure(minute, 45))
    timeline.append((minute, result["state"], result["focus_score"]))

for minute in (0, 15, 30, 40, 45, 60, 75, 89):
    _, state, score = next(row for row in timeline if row[0] == minute)
    print(f"  minute {minute:>2}: {state:<10} score {score}")
deep_minutes = sum(1 for _, state, _ in timeline if state == "deep_work") / 2
print(f"  minutes in deep_work: {deep_minutes} of 90")

print(f"\nTOTAL: {passed} passed, {failed} failed")