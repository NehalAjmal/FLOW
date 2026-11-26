import cv2
import numpy as np
import time
import threading
import os

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from ml_models.rppg import PulseEstimator, forehead_roi_mean


class FatigueService:
    def __init__(self):
        self.running = False
        self.thread = None
        self.detector = None

        self.cap = None  #  camera handle

        self.state = {}
        self._lock = threading.Lock()
        self._lifecycle = threading.Lock()
        self._stop = threading.Event()
        self._updated = 0.0
        self.pulse = PulseEstimator()

        # eye landmarks
        self.LEFT_EYE = [33, 160, 158, 133, 153, 144]
        self.RIGHT_EYE = [362, 385, 387, 263, 373, 380]

        # calibration
        self.baseline_ear = None
        self.ear_history = []
        self.calibration_frames = 50

        self.closed_frames = 0
        self.fatigue_score = 0.0

    # ─────────────────────────────
    # INIT DETECTOR
    # ─────────────────────────────
    def _init_detector(self):
        if self.detector is not None:
            return

        MODEL_PATH = os.path.join(
            os.path.dirname(__file__),
            "face_landmarker.task"
        )

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f" Model not found at {MODEL_PATH}\n"
                f"Download and place in ml_models/"
            )

        base_options = python.BaseOptions(
            model_asset_path=MODEL_PATH
        )

        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
            num_faces=1
        )

        self.detector = vision.FaceLandmarker.create_from_options(options)
        print(" MediaPipe initialized")

    # ─────────────────────────────
    # START
    # ─────────────────────────────
    def start(self):
        with self._lifecycle:
            if self.thread and self.thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError("Previous camera worker is still stopping")
                return
            self._clear()
            self.baseline_ear = None
            self.ear_history = []
            self.closed_frames = 0
            self.fatigue_score = 0.0
            self.pulse = PulseEstimator()
            self._stop.clear()
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _clear(self):
        with self._lock:
            self.state = {}
            self._updated = 0.0

    def stop(self):
        with self._lifecycle:
            self._stop.set()
            self.running = False
            self._clear()
            if self.thread:
                self.thread.join(timeout=3)
            return not (self.thread and self.thread.is_alive())

    def get_state(self):
        with self._lock:
            if self._stop.is_set() or not self.running or time.monotonic() - self._updated > 2:
                return {}
            return dict(self.state)

    def _run(self):
        try:
            self._init_detector()
            if self._stop.is_set():
                return
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                return
            while not self._stop.is_set():
                ret, frame = self.cap.read()
                if not ret:
                    self._clear()
                    self.closed_frames = 0
                    self.pulse = PulseEstimator()
                    self._stop.wait(0.1)
                    continue
                rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                result = self.detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                if not result.face_landmarks:
                    self._clear()
                    self.closed_frames = 0
                    self.pulse = PulseEstimator()
                    self._stop.wait(0.03)
                    continue
                face = result.face_landmarks[0]
                h, w = frame.shape[:2]
                ear = float((self._compute_ear(self._get_points(face, self.LEFT_EYE, w, h)) + self._compute_ear(self._get_points(face, self.RIGHT_EYE, w, h))) / 2)
                if not np.isfinite(ear) or not 0 < ear <= 1:
                    self._clear()
                    self.closed_frames = 0
                    self.pulse = PulseEstimator()
                    continue
                if self.baseline_ear is None:
                    self.ear_history.append(ear)
                    if len(self.ear_history) >= self.calibration_frames:
                        self.baseline_ear = float(np.mean(self.ear_history))
                    self._stop.wait(0.03)
                    continue
                points = self._get_points(face, [1, 33, 263, 152, 10], w, h)
                xs, ys = points[:, 0], points[:, 1]
                green = forehead_roi_mean(cv2.flip(frame, 1), (min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)))
                if np.isfinite(green):
                    self.pulse.add_sample(green)
                self.pulse.estimate()
                if ear / self.baseline_ear < 0.75:
                    self.closed_frames += 1
                else:
                    if self.closed_frames > 15:
                        self.fatigue_score += 0.1
                    self.closed_frames = 0
                if self.closed_frames > 20:
                    self.fatigue_score += 0.02
                self.fatigue_score = min(self.fatigue_score * 0.98, 1.0)
                bpm = self.pulse.bpm
                confidence = self.pulse.confidence
                valid_hr = bpm is not None and np.isfinite(bpm) and np.isfinite(confidence) and 0.15 <= confidence <= 1 and 42 <= bpm <= 200
                with self._lock:
                    if not self._stop.is_set():
                        self.state = {"fatigue_score": round(self.fatigue_score, 3), "ear": ear, "heart_rate_bpm": float(bpm) if valid_hr else None, "hr_confidence": float(confidence) if valid_hr else None}
                        self._updated = time.monotonic()
                self._stop.wait(0.03)
        finally:
            try:
                if self.cap is not None:
                    self.cap.release()
            finally:
                self.cap = None
                try:
                    if self.detector is not None:
                        self.detector.close()
                finally:
                    self.detector = None
                    self.running = False
                    self._clear()

    # ─────────────────────────────
    # HELPERS
    # ─────────────────────────────
    def _compute_ear(self, eye):
        A = np.linalg.norm(eye[1] - eye[5])
        B = np.linalg.norm(eye[2] - eye[4])
        C = np.linalg.norm(eye[0] - eye[3])
        return (A + B) / (2.0 * C) if C > 0 else float("nan")

    def _get_points(self, face, indices, w, h):
        return np.array([
            [int(face[i].x * w), int(face[i].y * h)]
            for i in indices
        ])


#  SINGLETON INSTANCE
fatigue_service = FatigueService()
