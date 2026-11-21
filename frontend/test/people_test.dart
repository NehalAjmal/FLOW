import 'package:flow/api/api_connector.dart';
import 'package:flow/api/api_error.dart';
import 'package:flow/api/mock/mock_backend.dart';
import 'package:flow/api/mock/mock_members.dart';
import 'package:flow/api/models/member.dart';
import 'package:flow/api/models/team.dart';
import 'package:flow/api/models/session.dart';
import 'package:flow/api/models/day.dart';
import 'package:flow/app.dart';
import 'package:flow/router/app_router.dart';
import 'package:flow/router/routes.dart';
import 'package:flow/state/auth_controller.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  detailTests();

  test('member JSON: coarse fields only, tolerant of gaps', () {
    final m = MemberSummary.fromJson({
      'id': 'm1',
      'name': 'Ada',
      'focus_by_day': [60, 90],
      'sessions': 3,
      'breaks_taken': 1,
      'breaks_suggested': 2,
      'nudges': {'taken': 1, 'snoozed': 1, 'dismissed': 0},
      'strain': 'moderate',
      // a backend that leaks these must not surface them anywhere
      'task_text': 'secret project',
      'window_title': 'secret.docx',
    });
    expect(m.focusByDay, [60, 90, 0, 0, 0, 0, 0]);
    expect(m.focusMinutes, 150);
    expect(m.nudges.total, 2);
    expect(m.strainRank, 1);
  });

  test('mock members are stable, and differ enough to compare', () {
    final now = DateTime(2026, 11, 12, 17); // a Thursday
    final a = mockMembers(small: false, now: now), b = mockMembers(small: false, now: now);
    expect(a.length, 8);
    expect([for (final m in a) m.focusMinutes], [for (final m in b) m.focusMinutes]);
    expect(a.map((m) => m.strain).toSet().length, greaterThan(1));
    for (final m in a) {
      expect(m.focusByDay.sublist(4), everyElement(0), reason: 'Fri–Sun have not happened yet');
    }
    expect(mockMember('m_ada', now: now)!.days.length, 7);
    expect(mockMember('nobody', now: now), isNull);
  });

  test('only an admin can list people or open a person', () async {
    final b = MockBackend(config: MockConfig.fast);
    final c = mockContainer(b);
    c.listen(authProvider, (_, _) {});
    await eventually(() => c.read(authProvider) is SignedOut);
    await c.read(authProvider.notifier).login(email: 'employee@flow.dev', password: 'password');
    await expectLater(c.read(adminApiProvider).members(), throwsA(isA<ApiError>()));
    await expectLater(c.read(adminApiProvider).member('m_ada'), throwsA(isA<ApiError>()));
    await c.read(authProvider.notifier).logout();
    await c.read(authProvider.notifier).login(email: 'admin@flow.dev', password: 'password');
    await c.read(authProvider.notifier).verifyMfa(MockBackend.mfaCode);
    expect(await c.read(adminApiProvider).members(), hasLength(8));
    final before = b.audit.length;
    await c.read(adminApiProvider).member('m_ada');
    expect(b.audit.length, before + 1, reason: 'opening a person is recorded');
    expect(b.audit.first.action, 'member.view');
    c.dispose();
  });

  for (final size in const [Size(1024, 700), Size(1440, 900)]) {
    for (final route in [Routes.adminPeople, Routes.adminPerson('m_ben')]) {
      testWidgets('$route lays out at ${size.width.toInt()}×${size.height.toInt()}', (tester) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final c = mockContainer(
          MockBackend(
            config: const MockConfig(latency: Duration.zero, tick: Duration(hours: 1)),
          ),
        );
        await tester.pumpWidget(UncontrolledProviderScope(container: c, child: const FlowApp()));
        await tester.pump(const Duration(seconds: 4));
        await tester.runAsync(() async {
          await c.read(authProvider.notifier).login(email: 'admin@flow.dev', password: 'password');
          await c.read(authProvider.notifier).verifyMfa(MockBackend.mfaCode);
        });
        for (var i = 0; i < 10; i++) {
          await tester.pump(const Duration(milliseconds: 200));
        }
        c.read(appRouterProvider).go(route);
        for (var i = 0; i < 20; i++) {
          await tester.pump(const Duration(milliseconds: 150));
        }
        if (route == Routes.adminPeople) {
          expect(find.text('Ben Hartmann'), findsOneWidget);
          await tester.tap(find.text('Ben Hartmann'));
          for (var i = 0; i < 10; i++) {
            await tester.pump(const Duration(milliseconds: 150));
          }
          expect(c.read(appRouterProvider).state.uri.path, Routes.adminPerson('m_ben'));
        } else {
          expect(find.text('Ben Hartmann'), findsOneWidget);
          expect(find.textContaining('never what anyone works on'), findsOneWidget);
        }
        final err = tester.takeException();
        await tester.pumpWidget(const SizedBox());
        c.dispose();
        await tester.pump(const Duration(seconds: 1));
        expect(err, isNull);
      });
    }
  }

  testWidgets('a non-admin is sent away from the People pages', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final c = mockContainer(
      MockBackend(
        config: const MockConfig(latency: Duration.zero, tick: Duration(hours: 1)),
      ),
    );
    await tester.pumpWidget(UncontrolledProviderScope(container: c, child: const FlowApp()));
    await tester.pump(const Duration(seconds: 4));
    await tester.runAsync(() => c.read(authProvider.notifier).login(email: 'employee@flow.dev', password: 'password'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    c.read(appRouterProvider).go(Routes.adminPerson('m_ada'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 150));
    }
    expect(c.read(appRouterProvider).state.uri.path, Routes.home);
    await tester.pumpWidget(const SizedBox());
    c.dispose();
    await tester.pump(const Duration(seconds: 1));
  });
}

void detailTests() {
  DateTime at(int d, int h, [int m = 0]) => DateTime(2026, 11, 9 + d, h, m); // Mon 9 Nov 2026 + d
  MemberSession s(int d, int h0, int m0, int h1, int m1, Demand demand) =>
      MemberSession(start: at(d, h0, m0), end: at(d, h1, m1), demand: demand);

  final detail = MemberDetail(
    summary: const MemberSummary(
      id: 'x',
      name: 'X',
      focusByDay: [150, 60, 0, 0, 0, 0, 0],
      sessions: 4,
      breaksTaken: 1,
      breaksSuggested: 3,
      nudges: NudgeResponses(taken: 1, snoozed: 1, dismissed: 1),
      strain: 'moderate',
      prevFocusMinutes: 300,
    ),
    days: [
      MemberDay(
        date: at(0, 0),
        // 9:00–10:00, then straight on 10:10–11:00 with no break, then a break, then 13:30–14:10
        sessions: [s(0, 9, 0, 10, 0, Demand.heavy), s(0, 10, 10, 11, 0, Demand.moderate), s(0, 13, 30, 14, 10, Demand.light)],
        breaks: [TimelineBreak(at: at(0, 11, 5), mark: BreakMark.taken)],
        nudges: const [],
      ),
      MemberDay(date: at(1, 0), sessions: [s(1, 9, 30, 10, 30, Demand.moderate)], breaks: const [], nudges: const []),
    ],
    focusTrend: const [],
    strainTrend: const [],
  );

  test('person detail is worked out from the week: hours, mix, average, longest stretch, usual hours', () {
    final h = detail.focusByHour;
    expect(h[9], 60 + 30, reason: 'Mon 9:00–10:00 and Tue 9:30–10:00');
    expect(h[10], 50 + 30);
    expect(h[13], 30);
    expect(h[14], 10);
    expect(h.reduce((a, b) => a + b), 210);
    expect(detail.demandMix, (light: 40, moderate: 110, heavy: 60));
    expect(detail.averageSessionMinutes, 53, reason: '210 minutes over 4 sessions');
    expect(detail.longestStretchMinutes, 110, reason: '9:00–11:00 with a 10 minute gap and no break taken in it');
    expect(detail.usualHours, (start: 9 * 60 + 15, end: 12 * 60 + 20));
    expect(detail.summary.focusDelta, 210 - 300);
    expect(detail.summary.daysActive, 2);
    expect(detail.summary.breakUptake, closeTo(1 / 3, 1e-9));
  });

  test('a break taken between two sessions ends the stretch', () {
    final d = MemberDetail(
      summary: detail.summary,
      days: [
        MemberDay(
          date: at(0, 0),
          sessions: [s(0, 9, 0, 10, 0, Demand.moderate), s(0, 10, 10, 11, 0, Demand.moderate)],
          breaks: [TimelineBreak(at: at(0, 10, 2), mark: BreakMark.taken)],
          nudges: const [],
        ),
      ],
      focusTrend: const [],
      strainTrend: const [],
    );
    expect(d.longestStretchMinutes, 60);
  });

  test('team metrics: optional detail parses, and its absence is not an error', () {
    final bare = TeamMetrics.fromJson({'average_focus': 0.6, 'trend': <Object>[]});
    expect(bare.focusMinutesPerDay, isNull);
    expect(bare.peakHours, isEmpty);
    final full = TeamMetrics.fromJson({
      'average_focus': 0.6,
      'trend': <Object>[],
      'focus_minutes_per_day': 212,
      'sessions_per_day': 3.4,
      'break_uptake': 0.58,
      'peak_hours': [10, 14],
      'focus_minutes_this_week': 480,
    });
    expect(full.focusMinutesPerDay, 212);
    expect(full.sessionsPerDay, 3.4);
    expect(full.breakUptake, 0.58);
    expect(full.peakHours, [10, 14]);
    expect(full.focusMinutesThisWeek, 480);
  });
}
