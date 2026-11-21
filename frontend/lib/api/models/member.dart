import '../../core/json.dart';
import 'day.dart';
import 'session.dart';
import 'team.dart';

/// Per-person data for the team's admin (GET /admin/members…).
///
/// Admin only. People join a team through an invite that says the admin can
/// see this. It is deliberately coarse: time, counts and responses. Never
/// task text, window titles, apps, typing or camera data — those fields do
/// not exist in these models, so the UI cannot show them by accident.

class NudgeResponses {
  const NudgeResponses({required this.taken, required this.snoozed, required this.dismissed});
  final int taken;
  final int snoozed;
  final int dismissed;

  int get total => taken + snoozed + dismissed;

  factory NudgeResponses.fromJson(Json j) =>
      NudgeResponses(taken: intOrNull(j['taken']) ?? 0, snoozed: intOrNull(j['snoozed']) ?? 0, dismissed: intOrNull(j['dismissed']) ?? 0);
}

/// One person's week at a glance (a row on the People page).
class MemberSummary {
  const MemberSummary({
    required this.id,
    required this.name,
    required this.focusByDay,
    required this.sessions,
    required this.breaksTaken,
    required this.breaksSuggested,
    required this.nudges,
    required this.strain,
    this.lastActiveAt,
    this.inSession = false,
    this.prevFocusMinutes,
  });

  /// Focus minutes in the week before this one (for "vs last week"); null
  /// when the server does not send it or the person is new.
  final int? prevFocusMinutes;

  final String id;
  final String name;

  /// Focus minutes Mon..Sun of the current week (always 7 entries).
  final List<int> focusByDay;
  final int sessions;
  final int breaksTaken;
  final int breaksSuggested;
  final NudgeResponses nudges;

  /// `low` | `moderate` | `high`: break pressure, not a health measure.
  final String strain;
  final DateTime? lastActiveAt;
  final bool inSession;

  int get focusMinutes => focusByDay.fold(0, (a, b) => a + b);

  /// Days with any focus this week.
  int get daysActive => focusByDay.where((m) => m > 0).length;

  /// Change against last week in minutes; null when unknown.
  int? get focusDelta => prevFocusMinutes == null ? null : focusMinutes - prevFocusMinutes!;

  /// Share of break suggestions answered with a break (0..1); null with none.
  double? get breakUptake => breaksSuggested == 0 ? null : breaksTaken / breaksSuggested;
  int get strainRank => switch (strain) {
    'high' => 2,
    'moderate' => 1,
    _ => 0,
  };

  factory MemberSummary.fromJson(Json j) {
    final days = intList(j['focus_by_day']);
    return MemberSummary(
      id: reqStr(j, 'id'),
      name: str(j['name']) ?? 'Unnamed',
      focusByDay: [for (var i = 0; i < 7; i++) i < days.length ? days[i] : 0],
      sessions: intOrNull(j['sessions']) ?? 0,
      breaksTaken: intOrNull(j['breaks_taken']) ?? 0,
      breaksSuggested: intOrNull(j['breaks_suggested']) ?? 0,
      nudges: NudgeResponses.fromJson(asJson(j['nudges'] ?? const <String, Object?>{})),
      strain: str(j['strain']) ?? 'low',
      lastActiveAt: dateOrNull(j['last_active_at']),
      inSession: boolOr(j['in_session'], false),
      prevFocusMinutes: intOrNull(j['prev_focus_minutes']),
    );
  }
}

class MemberSession {
  const MemberSession({required this.start, required this.end, required this.demand});
  final DateTime start;
  final DateTime end;
  final Demand demand;

  factory MemberSession.fromJson(Json j) => MemberSession(
    start: dateOrNull(j['start']) ?? DateTime.now(),
    end: dateOrNull(j['end']) ?? DateTime.now(),
    demand: enumFromWire(Demand.values, j['demand'], Demand.moderate),
  );
}

class MemberDay {
  const MemberDay({required this.date, required this.sessions, required this.breaks, required this.nudges});
  final DateTime date;
  final List<MemberSession> sessions;
  final List<TimelineBreak> breaks;
  final List<TimelineNudge> nudges;

  int get focusMinutes => sessions.fold(0, (a, s) => a + s.end.difference(s.start).inMinutes);

  factory MemberDay.fromJson(Json j) => MemberDay(
    date: dateOrNull(j['date']) ?? DateTime.now(),
    sessions: asJsonList(j['sessions']).map(MemberSession.fromJson).toList(),
    breaks: asJsonList(j['breaks']).map(TimelineBreak.fromJson).toList(),
    nudges: asJsonList(j['nudges']).map(TimelineNudge.fromJson).toList(),
  );
}

/// One person's page: their week as timelines, plus two trends.
class MemberDetail {
  const MemberDetail({required this.summary, required this.days, required this.focusTrend, required this.strainTrend});
  final MemberSummary summary;

  /// Mon..Sun of the current week.
  final List<MemberDay> days;

  /// Focus minutes per day, last 30 days.
  final List<TrendPoint> focusTrend;

  /// Break pressure 0..1 per day, last 14 days.
  final List<TrendPoint> strainTrend;

  // ── worked out here from [days]: no extra fields for the server to send ──

  Iterable<MemberSession> get _sessions => days.expand((d) => d.sessions);

  /// Minutes of focus in each hour of the day (0..23), over the week.
  List<int> get focusByHour {
    final out = List<int>.filled(24, 0);
    for (final s in _sessions) {
      var t = s.start;
      while (t.isBefore(s.end)) {
        final next = DateTime(t.year, t.month, t.day, t.hour + 1);
        final upto = next.isBefore(s.end) ? next : s.end;
        out[t.hour] += upto.difference(t).inMinutes;
        t = upto;
      }
    }
    return out;
  }

  /// Focus minutes by demand: light, moderate, heavy.
  ({int light, int moderate, int heavy}) get demandMix {
    var l = 0, m = 0, h = 0;
    for (final s in _sessions) {
      final mins = s.end.difference(s.start).inMinutes;
      switch (s.demand) {
        case Demand.light:
          l += mins;
        case Demand.moderate:
          m += mins;
        default:
          h += mins;
      }
    }
    return (light: l, moderate: m, heavy: h);
  }

  /// Mean session length in minutes (0 with no sessions).
  int get averageSessionMinutes {
    final all = _sessions.toList();
    if (all.isEmpty) return 0;
    return (all.fold(0, (a, s) => a + s.end.difference(s.start).inMinutes) / all.length).round();
  }

  /// The longest run of focus without a break taken, in minutes: back-to-back
  /// sessions count as one stretch unless a break was taken between them.
  int get longestStretchMinutes {
    var best = 0;
    for (final d in days) {
      final taken = [for (final b in d.breaks) if (b.mark == BreakMark.taken) b.at];
      final sessions = [...d.sessions]..sort((a, b) => a.start.compareTo(b.start));
      var run = 0;
      MemberSession? prev;
      for (final s in sessions) {
        final rested = prev != null && taken.any((t) => !t.isBefore(prev!.start) && !t.isAfter(s.start));
        final gap = prev == null ? 0 : s.start.difference(prev.end).inMinutes;
        if (prev == null || rested || gap > 45) run = 0; // a real pause resets it too
        run += s.end.difference(s.start).inMinutes;
        if (run > best) best = run;
        prev = s;
      }
    }
    return best;
  }

  /// Typical first start and last end on working days, as minutes after
  /// midnight; null with no sessions.
  ({int start, int end})? get usualHours {
    final starts = <int>[], ends = <int>[];
    for (final d in days) {
      if (d.sessions.isEmpty) continue;
      final first = d.sessions.map((s) => s.start).reduce((a, b) => a.isBefore(b) ? a : b);
      final last = d.sessions.map((s) => s.end).reduce((a, b) => a.isAfter(b) ? a : b);
      starts.add(first.hour * 60 + first.minute);
      ends.add(last.hour * 60 + last.minute);
    }
    if (starts.isEmpty) return null;
    int mean(List<int> v) => (v.reduce((a, b) => a + b) / v.length).round();
    return (start: mean(starts), end: mean(ends));
  }

  factory MemberDetail.fromJson(Json j) => MemberDetail(
    summary: MemberSummary.fromJson(asJson(j['summary'])),
    days: asJsonList(j['days']).map(MemberDay.fromJson).toList(),
    focusTrend: asJsonList(j['focus_trend']).map(TrendPoint.fromJson).toList(),
    strainTrend: asJsonList(j['strain_trend']).map(TrendPoint.fromJson).toList(),
  );
}
