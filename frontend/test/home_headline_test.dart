import 'package:flow/api/models/day.dart';
import 'package:flow/api/models/session.dart';
import 'package:flow/screens/home_screen.dart' show dayHeadline;
import 'package:flutter_test/flutter_test.dart';

// Home's title is the day's conclusion, pinned to fixed data here so each
// branch is checked on purpose (the smoke test only knows the clock).
DateTime at(int h, int m) => DateTime(2026, 11, 27, h, m);

TimelineSession s(int h0, int m0, int h1, int m1, {TimelineSessionState state = TimelineSessionState.done}) =>
    TimelineSession(id: '$h0$m0', start: at(h0, m0), end: at(h1, m1), demand: Demand.moderate, state: state);

DayTimeline day(List<TimelineSession> sessions) => DayTimeline(
  date: at(0, 0),
  sessions: sessions,
  breaks: const [],
  nudges: const [],
  meetings: const [],
  pressure: const [],
  forecast: const [],
  forecastBand: const [],
  forecastConfidence: null,
  usualBand: const [],
  usualDays: 0,
  totals: const DayTotals(focusMinutes: 0, breaksTaken: 0, breaksSuggested: 0, breaksSkipped: 0),
);

void main() {
  test('nothing to conclude yet: no headline, so Home greets', () {
    expect(dayHeadline(day(const []), today: true, weekday: 'Friday'), isNull);
    expect(dayHeadline(day([s(9, 0, 9, 15)]), today: true, weekday: 'Friday'), isNull, reason: 'under 20 min is not a stretch');
  });

  test('the longest stretch, joining sessions under 10 min apart', () {
    final d = day([s(9, 20, 10, 10), s(10, 15, 11, 45), s(14, 0, 15, 0)]);
    expect(dayHeadline(d, today: true, weekday: 'Friday'), 'Best stretch today: 9:20 to 11:45');
    expect(dayHeadline(d, today: false, weekday: 'Tuesday'), 'Best stretch on Tuesday: 9:20 to 11:45');
  });

  test('a block running now wins', () {
    final d = day([s(9, 20, 11, 45), s(16, 0, 16, 50, state: TimelineSessionState.active)]);
    expect(dayHeadline(d, today: true, weekday: 'Friday'), 'In a focus block until 4:50');
  });

  test('a past day with no stretch says so', () {
    expect(dayHeadline(day(const []), today: false, weekday: 'Monday'), 'No long stretch on Monday');
  });
}
