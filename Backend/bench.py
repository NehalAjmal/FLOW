"""Reproduce the numbers in Section IV-H / Table III that do not come from pytest or check_scoring.py.
Put it in FLOW/Backend and run:  python bench.py   (or from elsewhere: python bench.py path/to/FLOW/Backend)
"""
import sys, json, timeit
import numpy as np
import os
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
from ml_models.rppg import PulseEstimator
from engine.deviation import DeviationEngine
from engine.ultradian import UltradianEngine
from engine.decision import DecisionEngine, compute_trough_pressure

# 1. Heart-rate estimator on synthetic pulse signals (not people).
#    green value = 120 + slow drift + pulse (amplitude 0.5) + noise; 30 fps with timing jitter; 40 s per run.
rng = np.random.default_rng(7)
def run(bpm, noise, fps=30.0, secs=40.0):
    est = PulseEstimator(fps); t = 0.0; outs = []; calls = 0; last = -1
    while t < secs:
        t += 1 / fps + rng.normal(0, 0.004)
        est.add_sample(120 + 0.3 * t + 0.5 * np.sin(2 * np.pi * bpm / 60 * t) + rng.normal(0, noise), now=t)
        if int(t) != last and t > 13:          # ask once per second after the 12-s window fills
            last = int(t); calls += 1
            b, _ = est.estimate(now=t)
            if b is not None: outs.append(b)
    return outs, calls
for noise in (0.5, 1.0, 1.5):
    errs, cover = [], []
    for bpm in (50, 60, 72, 85, 100, 120, 150):
        for _ in range(10):
            o, c = run(bpm, noise); cover.append(len(o) / c); errs += [abs(v - bpm) for v in o]
    e = np.array(errs)
    snr = 20 * np.log10(0.5 / np.sqrt(2) / noise)
    print(f"SNR {snr:5.1f} dB: MAE {e.mean():.2f} BPM, max {e.max():.2f}, within 5 BPM {np.mean(e <= 5)*100:.0f}%, value given {np.mean(cover)*100:.0f}% of seconds")

# 2. Cost of scoring one 30-second record.
dev, ult, dec = DeviationEngine(), UltradianEngine(90), DecisionEngine(); ult.start()
def tick():
    d = dev.compute(keystrokes=30, switches=2, idle_seconds=3, declared_difficulty="moderate")
    return dec.compute(fatigue=0.2, deviation=d, ultradian=ult.compute(), biometric=None,
                       trough_pressure=compute_trough_pressure(30, 45))
n = 20000
print(f"scoring: {timeit.timeit(tick, number=n)/n*1e6:.1f} microseconds per record")

# 3. Size of one stored record (same fields as sessions/service.py writes).
rec = {"ts": "2026-11-23T10:15:30.123456+00:00", "keystrokes": 31, "switches": 2, "idle": 3, "window": "Code",
       "state": "deep_work", "score": 86.4, "fatigue": 0.214, "deviation": 0.12, "ultradian": 0.333, "biometric": None}
s = len(json.dumps(rec)); print(f"record: {s} bytes, {s*120/1024:.1f} KB per hour")
