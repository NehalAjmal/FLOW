import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/models/session.dart';
import '../state/session_controller.dart';

typedef PauseMark = ({String id, DateTime at});

/// When this computer saw the running session go on pause.
///
/// The server only adds a pause to `paused_seconds` on resume, so while a
/// session is paused `elapsedAt(now)` keeps counting. Every on-screen clock
/// reads the time through [ActiveSessionClock.focusAt] with this mark, which
/// stops the clock at the moment of the pause. The mark is kept after the
/// session ends so an end-while-paused is still counted correctly, and it is
/// saved so that a restart during a pause stops at the original moment.
final pausedSinceProvider = NotifierProvider<PausedSince, PauseMark?>(PausedSince.new);

class PausedSince extends Notifier<PauseMark?> {
  static const key = 'flow.pausedSince.v1';

  @override
  PauseMark? build() {
    final s = ref.watch(liveSessionProvider).value?.session;
    final was = stateOrNull;
    if (s == null) return was;
    if (!s.paused) {
      if (was != null) _clear();
      return null;
    }
    if (was != null && was.id == s.sessionId) return was;
    final mark = (id: s.sessionId, at: DateTime.now());
    _restore(mark);
    return mark;
  }

  /// A pause seen for the first time may be one from before a restart: take
  /// the saved moment if it is for this session and earlier; else save ours.
  Future<void> _restore(PauseMark mark) async {
    try {
      final sp = await SharedPreferences.getInstance();
      final saved = sp.getString(key)?.split('|');
      final at = saved != null && saved.length == 2 && saved[0] == mark.id ? DateTime.tryParse(saved[1]) : null;
      if (at != null && at.isBefore(mark.at)) {
        if (ref.mounted && state == mark) state = (id: mark.id, at: at);
      } else {
        await sp.setString(key, '${mark.id}|${mark.at.toIso8601String()}');
      }
    } catch (_) {}
  }

  Future<void> _clear() async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.remove(key);
    } catch (_) {}
  }
}

extension ActiveSessionClock on ActiveSession {
  /// Focus time at [now], stopped while paused.
  Duration focusAt(DateTime now, PauseMark? pausedSince) {
    final mark = pausedSince;
    final stop = paused && mark != null && mark.id == sessionId && mark.at.isBefore(now) ? mark.at : now;
    return elapsedAt(stop);
  }
}
