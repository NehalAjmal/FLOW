"""
FLOW Activity Agent — cross-platform input & window tracking.

Keystroke / mouse tracking uses pynput (Windows / macOS / Linux).
Frontmost-window tracking is platform-specific:
  Windows → win32gui
  macOS   → Quartz CGWindowListCopyWindowInfo (pyobjc)
  Linux   → best-effort via xdotool if installed
Anything unavailable degrades to "Unknown" without crashing the agent.
"""

import platform
import time

import threading

if __package__:
    from .categories import categorize_application
else:
    from categories import categorize_application


class KeystrokeTracker:
    def __init__(self):
        self.count = 0
        self.last_press_time = None
        self.listener = None
        self._lock = threading.Lock()

    def on_press(self, key):
        with self._lock:
            self.count += 1
            self.last_press_time = time.monotonic()

    def start(self):
        from pynput import keyboard
        if self.listener is not None:
            raise RuntimeError("Tracker already started")
        with self._lock:
            self.count = 0
            self.last_press_time = None
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()

    def stop(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener.join(timeout=2)
            if self.listener.is_alive():
                raise RuntimeError("Keyboard listener did not stop")
            self.listener = None
        with self._lock:
            self.count = 0
            self.last_press_time = None

    def get_and_reset(self):
        with self._lock:
            val = self.count
            self.count = 0
            return val

    def idle_seconds(self, cap: int) -> int:
        with self._lock:
            if self.last_press_time is None:
                return cap
            return max(0, min(cap, int(time.monotonic() - self.last_press_time)))


# Foreground identity is local only. Never retrieve window titles.
def _get_window_win32():
    import ctypes
    from ctypes import wintypes
    import win32gui
    import win32process
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None, "unknown"
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return hwnd, "unknown"
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        identity = ""
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            identity = buffer.value
        return hwnd, categorize_application(identity)
    finally:
        kernel.CloseHandle(handle)


def _get_window_macos():
    from AppKit import NSWorkspace
    from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID, kCGWindowLayer, kCGWindowOwnerPID, kCGWindowNumber)
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None, "unknown"
    pid = app.processIdentifier()
    category = categorize_application(app.localizedName())
    for window in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []:
        if window.get(kCGWindowLayer) == 0 and window.get(kCGWindowOwnerPID) == pid:
            return (pid, window.get(kCGWindowNumber)), category
    return (pid, None), category


def _get_window_linux():
    import subprocess
    from pathlib import Path
    def query(*args):
        return subprocess.check_output(["xdotool", *args], text=True, timeout=1, stderr=subprocess.DEVNULL).strip()
    window = query("getactivewindow")
    try:
        pid = int(query("getwindowpid", window))
        identity = str(Path(f"/proc/{pid}/exe").resolve(strict=True))
    except (OSError, ValueError, subprocess.SubprocessError):
        identity = ""
    return window, categorize_application(identity)


class WindowTracker:
    def __init__(self):
        self._last_id = None
        self.last_category = "unknown"
        self.switch_count = 0
        self._lock = threading.Lock()
        self._impl = {"Windows": _get_window_win32, "Darwin": _get_window_macos,
                      "Linux": _get_window_linux}.get(platform.system())

    @property
    def available(self):
        return self._impl is not None

    def update(self):
        try:
            identity, category = self._impl() if self._impl else (None, "unknown")
        except Exception:
            identity, category = None, "unknown"
        with self._lock:
            if identity is not None:
                if self._last_id is not None and identity != self._last_id:
                    self.switch_count += 1
                self._last_id = identity
            self.last_category = category
        return category

    def snapshot_and_reset(self):
        with self._lock:
            result = self.switch_count, self.last_category
            self.switch_count = 0
            return result

    def get_and_reset(self):
        return self.snapshot_and_reset()[0]
