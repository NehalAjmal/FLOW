import 'package:flow/api/api_connector.dart';
import 'package:flow/api/api_error.dart';
import 'package:flow/api/mock/mock_apis.dart';
import 'package:flow/api/mock/mock_backend.dart';
import 'package:flow/api/models/consent.dart';
import 'package:flow/api/models/session.dart';
import 'package:flow/api/models/settings.dart';
import 'package:flow/core/session_clock.dart';
import 'package:flow/state/account_controllers.dart';
import 'package:flow/state/auth_controller.dart';
import 'package:flow/state/break_controller.dart';
import 'package:flow/state/data_providers.dart';
import 'package:flow/state/session_controller.dart';
import 'package:flow/widgets/common.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

Future<ProviderContainer> signedIn(MockBackend b, String email) async {
  final c = mockContainer(b);
  c.listen(authProvider, (_, _) {});
  await eventually(() => c.read(authProvider) is SignedOut);
  await c.read(authProvider.notifier).login(email: email, password: 'password');
  return c;
}

void main() {
  group('auth', () {
    test('solo login → signed in, consent already satisfied', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'solo@flow.dev');
      expect(c.read(authProvider), isA<SignedIn>());
      expect((await c.read(consentProvider.future)).canUseFlow, isTrue);
    });

    test('wrong password surfaces invalid_credentials', () async {
      final c = mockContainer(MockBackend(config: MockConfig.fast));
      c.listen(authProvider, (_, _) {});
      await expectLater(
        c.read(authProvider.notifier).login(email: 'solo@flow.dev', password: 'nope'),
        throwsA(isA<ApiError>().having((e) => e.code, 'code', ApiError.invalidCredentials)),
      );
    });

    test('admin needs MFA; wrong code rejected, right code signs in', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'admin@flow.dev');
      expect(c.read(authProvider), isA<MfaRequired>());
      await expectLater(c.read(authProvider.notifier).verifyMfa('000000'), throwsA(isA<ApiError>()));
      await c.read(authProvider.notifier).verifyMfa(MockBackend.mfaCode);
      final s = c.read(authProvider);
      expect(s, isA<SignedIn>());
      expect((s as SignedIn).user.isAdmin, isTrue);
    });

    test('new user has no consent; granting behavior unlocks the app', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'new@flow.dev');
      c.listen(consentProvider, (_, _) {});
      expect((await c.read(consentProvider.future)).canUseFlow, isFalse);
      await c.read(consentProvider.notifier).set(ConsentScope.behavior, true);
      expect(c.read(consentProvider).value!.canUseFlow, isTrue);
    });

    test('expired token signs the user out with a reason', () async {
      final b = MockBackend(config: MockConfig.fast);
      final c = await signedIn(b, 'solo@flow.dev');
      b.scenario = MockScenario.tokenExpiry;
      c.listen(settingsProvider, (_, _) {});
      await expectLater(c.read(settingsProvider.future), throwsA(isA<ApiError>()));
      await eventually(() => c.read(authProvider) is SignedOut);
      expect((c.read(authProvider) as SignedOut).message, contains('expired'));
    });

    test('logout ends a running session', () async {
      final b = MockBackend(config: MockConfig.fast);
      final c = await signedIn(b, 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      await c.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      expect(b.run, isNotNull);
      await c.read(authProvider.notifier).logout();
      expect(b.run, isNull);
      expect(c.read(authProvider), isA<SignedOut>());
    });
  });

  group('settings & consent coupling', () {
    test('enabling camera without camera consent throws ConsentRequired', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'solo@flow.dev');
      c.listen(settingsProvider, (_, _) {});
      c.listen(consentProvider, (_, _) {});
      await c.read(settingsProvider.future);
      await c.read(consentProvider.future);
      await expectLater(c.read(settingsProvider.notifier).patch(const SettingsPatch(cameraEnabled: true)), throwsA(isA<ConsentRequired>()));
    });

    test('withdrawing camera consent switches the camera setting off', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'solo@flow.dev');
      c.listen(settingsProvider, (_, _) {});
      c.listen(consentProvider, (_, _) {});
      await c.read(settingsProvider.future);
      await c.read(consentProvider.future);
      await c.read(consentProvider.notifier).set(ConsentScope.camera, true);
      await c.read(settingsProvider.notifier).patch(const SettingsPatch(cameraEnabled: true));
      expect(c.read(settingsProvider).value!.cameraEnabled, isTrue);
      await c.read(consentProvider.notifier).set(ConsentScope.camera, false);
      expect(c.read(settingsProvider).value!.cameraEnabled, isFalse);
    });
  });

  group('session loop', () {
    test('stream → intervention → snooze clears it → accept starts a break → end', () async {
      final b = MockBackend(config: MockConfig.fast);
      final c = await signedIn(b, 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      c.listen(breakProvider, (_, _) {});
      c.listen(settingsProvider, (_, _) {});
      await c.read(liveSessionProvider.future);

      await c
          .read(liveSessionProvider.notifier)
          .start(const StartSessionRequest(taskText: 'Refactor auth', demand: Demand.heavy, plannedMinutes: 50));
      await eventually(() => c.read(liveSessionProvider).value?.pendingInterventionId != null);
      expect(c.read(liveSessionProvider).value!.connection, LiveConnection.live);

      final id1 = c.read(liveSessionProvider).value!.pendingInterventionId!;
      final i1 = await c.read(interventionApiProvider).get(id1);
      await c.read(interventionActionsProvider).snooze(i1, 5);
      expect(c.read(liveSessionProvider).value!.pendingInterventionId, isNull);

      await eventually(() => c.read(liveSessionProvider).value?.pendingInterventionId != null);
      final id2 = c.read(liveSessionProvider).value!.pendingInterventionId!;
      expect(id2, isNot(id1));
      final br = await c.read(interventionActionsProvider).accept(await c.read(interventionApiProvider).get(id2));
      expect(c.read(breakProvider)?.breakId, br.breakId);

      final result = await c.read(breakProvider.notifier).end();
      expect(result.restorationScore, isNotNull);
      expect(c.read(breakProvider), isNull);

      final summary = await c.read(liveSessionProvider.notifier).end();
      expect(summary.breaksTaken, 1);
      // More nudges may arrive after the break under a slow test runner.
      expect(summary.breaksSuggested, greaterThanOrEqualTo(2));
      expect(c.read(liveSessionProvider).value, isNull);
    });

    test('stream drop falls back to polling, which still delivers the intervention', () async {
      // The mock stream dies after 3 events, before the intervention event,
      // so the nudge can only arrive through the polling fallback.
      final b = MockBackend(
        config: const MockConfig(latency: Duration.zero, tick: Duration(milliseconds: 10), ticksToIntervention: 6),
      )..scenario = MockScenario.streamDrops;
      final c = await signedIn(b, 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      await c.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      await eventually(() => c.read(liveSessionProvider).value?.connection == LiveConnection.polling);
      await eventually(() => c.read(liveSessionProvider).value?.pendingInterventionId != null);
      expect(c.read(liveSessionProvider).value!.connection, LiveConnection.polling);
    });

    test('backend outage while polling shows offline, session stays', () async {
      final b = MockBackend(config: MockConfig.fast)..scenario = MockScenario.streamDrops;
      final c = await signedIn(b, 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      await c.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      await eventually(() => c.read(liveSessionProvider).value?.connection == LiveConnection.polling);
      b.scenario = MockScenario.backendDown;
      await eventually(() => c.read(liveSessionProvider).value?.connection == LiveConnection.offline);
      expect(c.read(liveSessionProvider).value, isNotNull);
    });

    test('pause/resume reflects in state', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      await c.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      await c.read(liveSessionProvider.notifier).pause();
      expect(c.read(liveSessionProvider).value!.session.paused, isTrue);
      await c.read(liveSessionProvider.notifier).resume();
      expect(c.read(liveSessionProvider).value!.session.paused, isFalse);
    });

    test('the clock stops while paused and carries on after resume', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      c.listen(pausedSinceProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      final ctl = c.read(liveSessionProvider.notifier);
      await ctl.start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      expect(c.read(pausedSinceProvider), isNull);
      await ctl.pause();
      final mark = c.read(pausedSinceProvider);
      final s = c.read(liveSessionProvider).value!.session;
      expect(mark?.id, s.sessionId);
      // ten minutes on, a paused clock still shows the moment of the pause
      final later = mark!.at.add(const Duration(minutes: 10));
      expect(s.focusAt(later, mark), s.focusAt(mark.at, mark));
      expect(s.elapsedAt(later) - s.focusAt(later, mark), const Duration(minutes: 10));
      await ctl.resume();
      expect(c.read(pausedSinceProvider), isNull);
      // after resume the server's paused_seconds takes over
      final r = c.read(liveSessionProvider).value!.session;
      expect(r.focusAt(later, null), r.elapsedAt(later));
      // ending while paused keeps the mark, so the logged time excludes the pause
      await ctl.pause();
      expect(c.read(pausedSinceProvider)?.id, s.sessionId);
      await ctl.end();
      expect(c.read(pausedSinceProvider)?.id, s.sessionId);
    });

    test('a restart during a pause keeps the original pause moment', () async {
      SharedPreferences.setMockInitialValues({});
      final b = MockBackend(config: MockConfig.fast);
      final c1 = await signedIn(b, 'solo@flow.dev');
      c1.listen(liveSessionProvider, (_, _) {});
      c1.listen(pausedSinceProvider, (_, _) {});
      await c1.read(liveSessionProvider.future);
      await c1.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      await c1.read(liveSessionProvider.notifier).pause();
      final first = c1.read(pausedSinceProvider)!;
      final sp = await SharedPreferences.getInstance();
      await eventually(() => sp.getString(PausedSince.key) != null);
      c1.dispose();
      final c2 = await signedIn(b, 'solo@flow.dev');
      c2.listen(liveSessionProvider, (_, _) {});
      c2.listen(pausedSinceProvider, (_, _) {});
      await c2.read(liveSessionProvider.future);
      await eventually(() => c2.read(pausedSinceProvider)?.at == first.at);
      await c2.read(liveSessionProvider.notifier).resume();
      expect(c2.read(pausedSinceProvider), isNull);
    });

    test('a server without pause or +15 routes: a clear message, and the clock keeps running', () async {
      final b = MockBackend(config: MockConfig.fast);
      final c = mockContainer(b, session: _NoPauseRoutes(b));
      c.listen(authProvider, (_, _) {});
      await eventually(() => c.read(authProvider) is SignedOut);
      await c.read(authProvider.notifier).login(email: 'solo@flow.dev', password: 'password');
      c.listen(liveSessionProvider, (_, _) {});
      c.listen(pausedSinceProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      final ctl = c.read(liveSessionProvider.notifier);
      await ctl.start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      for (final call in [ctl.pause, () => ctl.extend(15)]) {
        Object? error;
        try {
          await call();
        } catch (e) {
          error = e;
        }
        expect(error, isA<ApiError>());
        expect(errorText(error!), "This server doesn't support that yet.");
      }
      final s = c.read(liveSessionProvider).value!.session;
      expect(s.paused, isFalse);
      expect(s.plannedMinutes, 25);
      expect(c.read(pausedSinceProvider), isNull);
      // a 404 for a real missing thing keeps the server's own words
      expect(errorText(ApiError.fromResponse(404, '{"detail":"Task not found"}')), 'Task not found');
    });

    test('a running session is restored after an app restart', () async {
      final b = MockBackend(config: MockConfig.fast);
      final c1 = await signedIn(b, 'solo@flow.dev');
      c1.listen(liveSessionProvider, (_, _) {});
      await c1.read(liveSessionProvider.future);
      await c1.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      final id = c1.read(liveSessionProvider).value!.session.sessionId;

      final c2 = await signedIn(b, 'solo@flow.dev'); // same backend, fresh app
      c2.listen(liveSessionProvider, (_, _) {});
      expect((await c2.read(liveSessionProvider.future))?.session.sessionId, id);
    });

    test('stuck assistant requires LLM consent', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'solo@flow.dev');
      c.listen(liveSessionProvider, (_, _) {});
      await c.read(liveSessionProvider.future);
      await c.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.light, plannedMinutes: 25));
      final id = c.read(liveSessionProvider).value!.session.sessionId;
      await expectLater(
        c.read(sessionApiProvider).stuck(id),
        throwsA(isA<ApiError>().having((e) => e.code, 'code', ApiError.llmConsentRequired)),
      );
      c.listen(consentProvider, (_, _) {});
      await c.read(consentProvider.future);
      await c.read(consentProvider.notifier).set(ConsentScope.llm, true);
      expect((await c.read(sessionApiProvider).stuck(id)).nextStep, isNotEmpty);
    });
  });

  group('team privacy', () {
    test('small team: summary suppressed with no data', () async {
      final b = MockBackend(config: MockConfig.fast)..scenario = MockScenario.smallTeam;
      final c = await signedIn(b, 'employee@flow.dev');
      c.listen(teamSummaryProvider, (_, _) {});
      final s = await c.read(teamSummaryProvider.future);
      expect(s.suppressed, isTrue);
      expect(s.data, isNull);
    });

    test('non-admin calling admin API gets 403', () async {
      final c = await signedIn(MockBackend(config: MockConfig.fast), 'employee@flow.dev');
      await expectLater(c.read(adminApiProvider).summary(), throwsA(isA<ApiError>().having((e) => e.isForbidden, 'forbidden', true)));
    });
  });

  test('mixed-mode warning when auth is mocked but other areas are real', () {
    expect(apiModeWarnings({...defaultApiModes, ApiArea.session: ApiMode.real}), isNotEmpty);
    expect(apiModeWarnings(defaultApiModes), isEmpty);
  });
}

/// The real backend today: no /pause, /resume or /extend routes.
class _NoPauseRoutes extends MockSessionApi {
  _NoPauseRoutes(super.b);
  static ApiError get _missing => ApiError.fromResponse(404, '{"detail":"Not Found"}');
  @override
  Future<void> pause(String sessionId, {String? reason}) async => throw _missing;
  @override
  Future<void> resume(String sessionId) async => throw _missing;
  @override
  Future<ActiveSession> extend(String sessionId, int minutes) async => throw _missing;
}
