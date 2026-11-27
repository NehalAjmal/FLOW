import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../api/api_connector.dart';
import '../api/mock/mock_apis.dart';
import '../api/mock/mock_backend.dart';
import '../core/token_store.dart';
import '../desktop/compact_views.dart';
import '../desktop/desktop_host.dart';
import '../desktop/window_controller.dart';
import '../router/app_router.dart';
import '../router/routes.dart';
import '../state/auth_controller.dart';
import '../state/session_controller.dart';
import '../tasks/tasks.dart';
import '../theme/tokens.dart';
import '../ui/pressable.dart';
import 'coach.dart';

/// The sign-up tutorial: a sandboxed copy of the real app on sample data.
/// The screen dims, one control is lit with one line, you press it, and the
/// result plays out fast. Nothing is sent anywhere and nothing is sensed:
/// there is no account yet. Ends with the way into Create account.
class TutorialScreen extends StatefulWidget {
  const TutorialScreen({super.key});
  @override
  State<TutorialScreen> createState() => _TutorialScreenState();
}

enum _Step { dial, start, watch, take, rest, learn, done }

class _TutorialScreenState extends State<TutorialScreen> {
  final _registry = CoachRegistry();
  final _stage = GlobalKey();
  late MockBackend _b;
  late ProviderContainer _c;
  bool _ready = false;
  _Step _step = _Step.dial;
  Timer? _poll;
  Offset? _down;
  int _run = 0;

  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    final run = ++_run;
    // fast ticks: pressure reaches the line in about 4 s
    _b = MockBackend(
      config: const MockConfig(latency: Duration(milliseconds: 60), tick: Duration(milliseconds: 450), ticksToIntervention: 9),
    );
    _c = ProviderContainer(overrides: _sandbox(_b), retry: (_, _) => null);
    _c.read(mockBackendProvider);
    try {
      await _c.read(authProvider.notifier).login(email: 'solo@flow.dev', password: 'password');
    } catch (_) {}
    if (!mounted || run != _run) return;
    setState(() {
      _ready = true;
      _step = _Step.dial;
    });
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(milliseconds: 120), (_) => _check());
  }

  /// Advances steps that finish on their own (the app's state changed).
  void _check() {
    if (!mounted || !_ready) return;
    final live = _c.read(liveSessionProvider).value;
    final next = switch (_step) {
      _Step.start when live != null => _Step.watch,
      _Step.watch when live?.pendingInterventionId != null => _Step.take,
      _Step.take when _b.breakActive => _Step.rest,
      _Step.rest when !_b.breakActive => _Step.learn,
      _ => _step,
    };
    if (next != _step) {
      setState(() => _step = next);
      if (next == _Step.learn) _toInsights();
    }
    // keep the lit hole on its control as layouts settle; rebuild only when
    // it actually moved (no 8 Hz rebuild of the whole sandbox)
    final hole = _measure();
    if (hole != _lastHole) setState(() {});
  }

  Rect? _lastHole;

  Rect? _measure() {
    final mark = _copy.mark;
    final stage = _stage.currentContext?.findRenderObject();
    return mark != null && stage is RenderBox && stage.hasSize ? _registry.rectOf(mark, stage) : null;
  }

  /// After the break: end the sample session (no more nudges) and show what
  /// Flow learns over days.
  Future<void> _toInsights() async {
    try {
      await _c.read(liveSessionProvider.notifier).end();
    } catch (_) {}
    if (!mounted) return;
    _c.read(appRouterProvider).go(Routes.patterns);
  }

  Future<void> _again() async {
    _poll?.cancel();
    final old = _c;
    setState(() => _ready = false);
    await _boot();
    old.dispose();
  }

  void _leave(String to) {
    _poll?.cancel();
    context.go(to);
  }

  @override
  void dispose() {
    _poll?.cancel();
    _c.dispose();
    super.dispose();
  }

  ({String? mark, String title, String? body, bool pass}) get _copy => switch (_step) {
    _Step.dial => (mark: 'dial', title: 'Pick a length', body: 'Drag the dial. The dashed block on your day shows where it would land.', pass: true),
    _Step.start => (mark: 'start', title: 'Press Start', body: 'Your block begins. In here, time runs fast.', pass: true),
    _Step.watch => (
      mark: 'day',
      title: 'Watch the pressure climb',
      body: 'Flow reads signs like how often you switch windows, never what is on your screen. The curve is rising toward your line.',
      pass: false,
    ),
    _Step.take => (
      mark: 'take-break',
      title: 'Your line: a good moment for a break',
      body: 'Take it. You could also snooze it, or ask why.',
      pass: true,
    ),
    _Step.rest => (mark: 'end-break', title: 'Breaks are short', body: 'In here you can cut it short. Press it to come back.', pass: true),
    _Step.learn => (
      mark: 'week',
      title: 'Over days, Flow learns your rhythm',
      body: 'When you focus best, how long you last, which breaks help. Every reading is you against your own usual, never a score.',
      pass: false,
    ),
    _Step.done => (
      mark: null,
      title: 'That was a whole day in 90 seconds.',
      body: 'Flow just learned a stranger\'s rhythm. Let it learn yours.',
      pass: false,
    ),
  };

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final copy = _copy;
    final hole = _lastHole = _measure();
    return Scaffold(
      backgroundColor: p.bg,
      body: Stack(
        key: _stage,
        children: [
          if (_ready)
            Positioned.fill(
              child: Listener(
                behavior: HitTestBehavior.translucent,
                onPointerDown: (e) => _down = e.localPosition,
                onPointerUp: (e) {
                  // the dial step ends once you have turned it
                  final d = _down;
                  if (_step == _Step.dial && d != null && hole != null && hole.inflate(8).contains(d) && (e.localPosition - d).distance > 6) {
                    setState(() => _step = _Step.start);
                  }
                },
                child: CoachScope(
                  registry: _registry,
                  child: UncontrolledProviderScope(
                    container: _c,
                    child: _SandboxApp(theme: Theme.of(context)),
                  ),
                ),
              ),
            ),
          if (_ready && (copy.mark == null || hole != null))
            Positioned.fill(
              child: CoachLight(
                hole: hole,
                passThrough: copy.pass,
                title: copy.title,
                body: copy.body,
                actions: [
                  if (_step == _Step.done) ...[
                    Pressable(tone: PressableTone.primary, onPressed: () => _leave(Routes.register), child: const Text('Create my account')),
                    CoachQuiet('Watch again', _again),
                  ],
                  if (_step == _Step.watch) CoachQuiet('Speed it up', () => _b.forceNudge()),
                  if (_step == _Step.learn)
                    Pressable(tone: PressableTone.primary, onPressed: () => setState(() => _step = _Step.done), child: const Text('Next')),
                ],
              ),
            ),
          if (!_ready) const Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 1.5))),
          // a way out, always
          if (_step != _Step.done)
            Positioned(right: 18, top: 14, child: SafeArea(child: CoachQuiet('Skip to Create account', () => _leave(Routes.register)))),
        ],
      ),
    );
  }
}

/// The real app, on the sandbox's own providers and router.
class _SandboxApp extends ConsumerWidget {
  const _SandboxApp({required this.theme});
  final ThemeData theme;
  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
    debugShowCheckedModeBanner: false,
    theme: theme,
    routerConfig: ref.watch(appRouterProvider),
    builder: (context, child) => WindowFrame(child: child ?? const SizedBox()),
  );
}

/// Every API on the mock backend, with a sample task list, no tokens kept,
/// and no native window: nothing in here touches the real app or the OS.
List<Override> _sandbox(MockBackend b) {
  final now = DateTime.now();
  return [
    tokenStoreProvider.overrideWithValue(MemoryTokenStore()),
    mockBackendProvider.overrideWith((ref) {
      ref.onDispose(b.dispose);
      return b;
    }),
    authApiProvider.overrideWithValue(MockAuthApi(b)),
    consentApiProvider.overrideWithValue(MockConsentApi(b)),
    settingsApiProvider.overrideWithValue(MockSettingsApi(b)),
    pauseApiProvider.overrideWithValue(MockPauseApi(b)),
    sessionApiProvider.overrideWithValue(MockSessionApi(b)),
    interventionApiProvider.overrideWithValue(MockInterventionApi(b)),
    breakApiProvider.overrideWithValue(MockBreakApi(b)),
    insightsApiProvider.overrideWithValue(MockInsightsApi(b)),
    calendarApiProvider.overrideWithValue(MockCalendarApi(b)),
    privacyApiProvider.overrideWithValue(MockPrivacyApi(b)),
    teamApiProvider.overrideWithValue(MockTeamApi(b)),
    adminApiProvider.overrideWithValue(MockAdminApi(b)),
    metaApiProvider.overrideWithValue(MockMetaApi(b)),
    scheduleApiProvider.overrideWithValue(MockScheduleApi(b)),
    localAgentApiProvider.overrideWith((ref) {
      final agent = MockLocalAgentApi(b);
      ref.onDispose(agent.dispose);
      return agent;
    }),
    desktopHostProvider.overrideWithValue(const NoopDesktopHost()),
    tasksStoreProvider.overrideWithValue(
      MemoryTasksStore([
        FlowTask(id: 'demo-1', title: 'Read chapter 4', estimateMinutes: 45, createdAt: now),
        FlowTask(id: 'demo-2', title: 'Draft the project outline', estimateMinutes: 60, createdAt: now),
      ]),
    ),
  ];
}
