import 'dart:math' as math;

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:material_ui/material_ui.dart';

import '../api/models/agent.dart';
import '../api/models/consent.dart';
import '../api/models/session.dart';
import '../desktop/window_controller.dart';
import '../router/routes.dart';
import '../state/account_controllers.dart';
import '../state/auth_controller.dart';
import '../state/data_providers.dart';
import '../state/session_controller.dart';
import '../theme/motion.dart';
import '../theme/tokens.dart';
import '../ui/brand/wordmark.dart';
import '../ui/dial.dart';
import '../ui/feature_note.dart';
import '../ui/kit.dart';
import '../ui/nudge_card.dart';
import '../ui/nudge_style.dart';
import '../widgets/common.dart';
import 'auth_layout.dart';
import 'auth_screens.dart';

/// Welcome guide (DESIGN_SPEC §5, §34): six steps, about two minutes, and the
/// whole window.
///
/// Two panes. On the left a **stage** that fills the page and shows the thing
/// itself, live, built from the app's own parts: a day that plays itself, the
/// signals going from dashed to solid as you allow them, the link to the
/// agent, where a nudge will appear, a nudge to try, the dial. On the right
/// what the step is, its controls, and Back / Next. A day line along the top
/// is the progress: solid behind you, dashed ahead (line = not yet).
///
/// Step 2 (behavior consent) is required: neither Next nor Skip passes it
/// until behavior sensing is granted. Left/right arrow keys move between
/// steps. Narrow windows stack the stage above the text.
/// Also reachable from Settings › Help as /guide.
class GuideScreen extends ConsumerStatefulWidget {
  const GuideScreen({super.key});
  @override
  ConsumerState<GuideScreen> createState() => _GuideScreenState();
}

class _GuideScreenState extends ConsumerState<GuideScreen> {
  static const steps = 6;
  int _i = 0;
  bool _forward = true;
  int _minutes = 50;
  bool _starting = false;

  static const _titles = [
    (
      'What Flow does',
      'Flow follows the rhythm of your work, never its content, and suggests a break before your focus runs down. Watch a day go by.',
    ),
    (
      'What Flow may use',
      'Nothing is on until you turn it on. Behavior sensing is the one Flow needs; the rest are optional and can change any time in Privacy.',
    ),
    ('Connect the agent', 'A small helper on this computer counts activity. It never reads window titles or what you type.'),
    ('How should nudges arrive?', 'Pick one. The screen on the left shows where it will appear. You can change it in Settings.'),
    ('Try a practice nudge', 'This one is pretend. Take it, snooze it, or ask why: nothing is recorded.'),
    ('Ready when you are', 'Pick a length on the dial. Flow learns your rhythm from the first few sessions.'),
  ];

  static const _tones = [FieldTone.brand, FieldTone.planned, FieldTone.planned, FieldTone.rest, FieldTone.rest, FieldTone.now];

  @override
  void initState() {
    super.initState();
    HardwareKeyboard.instance.addHandler(_onKey);
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_onKey);
    super.dispose();
  }

  /// ← / → move between steps, unless a text field has the keyboard.
  bool _onKey(KeyEvent e) {
    if (e is! KeyDownEvent) return false;
    if (FocusManager.instance.primaryFocus?.context?.widget is EditableText) return false;
    if (e.logicalKey == LogicalKeyboardKey.arrowRight) {
      _go(_i + 1);
      return true;
    }
    if (e.logicalKey == LogicalKeyboardKey.arrowLeft) {
      _go(_i - 1);
      return true;
    }
    return false;
  }

  bool get _consentOk => ref.read(consentProvider).value?.canUseFlow ?? false;

  bool _canLeave(int step) => step != 1 || _consentOk;

  void _go(int i) {
    if (i < 0 || i >= steps || i == _i) return;
    if (i > _i && !_canLeave(_i)) return;
    // never jump past the consent step without it
    if (i > 1 && !_consentOk) i = 1;
    if (i == _i) return;
    setState(() {
      _forward = i > _i;
      _i = i;
    });
  }

  void _finish() {
    if (!_consentOk) return _go(1);
    context.go(Routes.home);
  }

  Future<void> _startFirst() async {
    if (!_consentOk) return _go(1);
    if (_starting) return;
    setState(() => _starting = true);
    final ok = await runGuarded(
      context,
      () => ref
          .read(liveSessionProvider.notifier)
          .start(StartSessionRequest(demand: Demand.moderate, plannedMinutes: _minutes, shareTaskWithLlm: false)),
    );
    if (!mounted) return;
    setState(() => _starting = false);
    if (ok) context.go(Routes.home);
  }

  Widget _stage(int i) => switch (i) {
    0 => const _DayStage(),
    1 => const _SensingStage(),
    2 => const _AgentStage(),
    3 => const _NudgeStage(),
    4 => const _PracticeStage(),
    _ => _DialStage(minutes: _minutes, onMinutes: (m) => setState(() => _minutes = m), busy: _starting, onStart: _startFirst),
  };

  Widget _body(int i) => switch (i) {
    0 => const _WhatFlowDoes(),
    1 => const _Consent(),
    2 => const _Agent(),
    3 => const NudgeStyleOptions(),
    4 => const _PracticeNotes(),
    _ => _StartBody(minutes: _minutes),
  };

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    ref.watch(consentProvider); // rebuild Next/Skip when consent changes
    final reduced = Motion.reduced(context);
    final (title, note) = _titles[_i];
    final last = _i == steps - 1;

    final stage = AnimatedSwitcher(
      duration: reduced ? Duration.zero : const Duration(milliseconds: 320),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeIn,
      child: ColorField(
        key: ValueKey('stage-$_i'),
        tone: _tones[_i],
        radius: 24,
        padding: const EdgeInsets.all(28),
        child: SizedBox.expand(child: _stage(_i)),
      ),
    );

    // the step's words and controls; slides in from the side it came from
    final text = AnimatedSwitcher(
      duration: reduced ? Duration.zero : const Duration(milliseconds: 300),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeIn,
      layoutBuilder: (current, previous) => Stack(alignment: Alignment.topLeft, children: [...previous, ?current]),
      transitionBuilder: (child, a) {
        final incoming = child.key == ValueKey('text-$_i');
        final dx = (incoming ? 1 : -1) * (_forward ? 1 : -1) * 36.0;
        return FadeTransition(
          opacity: a,
          child: AnimatedBuilder(
            animation: a,
            child: child,
            builder: (context, child) => Transform.translate(offset: Offset(dx * (1 - a.value), 0), child: child),
          ),
        );
      },
      child: Column(
        key: ValueKey('text-$_i'),
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(flowCaps('Step ${_i + 1} of $steps'), style: FlowType.label(p, size: 10, color: p.text3)),
          const SizedBox(height: 10),
          Text(title, style: FlowType.headline(p, size: 34)),
          const SizedBox(height: 10),
          Text(note, style: FlowType.note(p, size: 15.5)),
          const SizedBox(height: 22),
          _body(_i),
        ],
      ),
    );

    final nav = Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_i == 1 && !_consentOk)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text('Behavior sensing is needed to use Flow', style: TextStyle(color: p.text2, fontSize: 12.5)),
          ),
        if (last) ...[
          AuthPrimary(label: _starting ? 'Starting…' : 'Start your first session', onPressed: _starting ? null : _startFirst),
          const SizedBox(height: 6),
          Row(
            children: [
              AuthLink('Back', onPressed: () => _go(_i - 1)),
              const Spacer(),
              AuthLink('Explore first', onPressed: _finish),
            ],
          ),
        ] else
          Row(
            children: [
              if (_i > 0) AuthLink('Back', onPressed: () => _go(_i - 1)),
              const Spacer(),
              SizedBox(
                width: 150,
                child: AuthPrimary(label: 'Next', onPressed: _canLeave(_i) ? () => _go(_i + 1) : null),
              ),
            ],
          ),
      ],
    );

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 18, 20, 10),
              child: Row(
                children: [
                  const FlowWordmark(capHeight: 18),
                  const SizedBox(width: 28),
                  Expanded(
                    child: _Progress(index: _i, count: steps, onTap: (k) => k < _i ? _go(k) : null),
                  ),
                  const SizedBox(width: 20),
                  if (!last) AuthLink('Skip setup', onPressed: _consentOk ? _finish : () => _go(1)),
                  AuthLink('Sign out', onPressed: () => ref.read(authProvider.notifier).logout()),
                ],
              ),
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, box) {
                  final wide = box.maxWidth >= 980;
                  if (!wide) {
                    // narrow: the stage on top, the words under it, one scroll
                    return ListView(
                      padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
                      children: [
                        SizedBox(height: (box.maxHeight * 0.42).clamp(220.0, 380.0), child: stage),
                        const SizedBox(height: 22),
                        text,
                        const SizedBox(height: 22),
                        nav,
                      ],
                    );
                  }
                  final column = (box.maxWidth * 0.34).clamp(400.0, 520.0);
                  return Padding(
                    padding: const EdgeInsets.fromLTRB(20, 4, 28, 22),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(child: stage),
                        const SizedBox(width: 36),
                        SizedBox(
                          width: column,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Expanded(
                                child: SingleChildScrollView(padding: const EdgeInsets.only(top: 18, bottom: 12), child: text),
                              ),
                              nav,
                            ],
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Progress as a day line: solid where you have been, the current step in the
/// accent (now), dashed ahead (not yet). Earlier steps can be clicked.
class _Progress extends StatelessWidget {
  const _Progress({required this.index, required this.count, required this.onTap});
  final int index;
  final int count;
  final void Function(int) onTap;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return Semantics(
      label: 'Step ${index + 1} of $count',
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Row(
          children: [
            for (var k = 0; k < count; k++) ...[
              if (k > 0) const SizedBox(width: 6),
              Expanded(
                child: MouseRegion(
                  cursor: k < index ? SystemMouseCursors.click : SystemMouseCursors.basic,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () => onTap(k),
                    child: SizedBox(height: 22, child: CustomPaint(painter: _SegmentPainter(p, k < index ? 1 : (k == index ? 0 : -1)))),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SegmentPainter extends CustomPainter {
  _SegmentPainter(this.p, this.state);
  final FlowPalette p;

  /// 1 done · 0 now · -1 ahead
  final int state;

  @override
  void paint(Canvas c, Size s) {
    final y = s.height / 2;
    if (state < 0) {
      final dash = Paint()
        ..color = p.text3
        ..strokeWidth = 1.4;
      for (var x = 0.0; x < s.width; x += 7) {
        c.drawLine(Offset(x, y), Offset(math.min(x + 3.5, s.width), y), dash);
      }
    } else {
      c.drawLine(
        Offset(0, y),
        Offset(s.width, y),
        Paint()
          ..color = state == 0 ? p.accent : p.text1
          ..strokeWidth = state == 0 ? 3 : 2
          ..strokeCap = StrokeCap.round,
      );
    }
  }

  @override
  bool shouldRepaint(_SegmentPainter o) => o.state != state || o.p != p;
}

// ── 1 ─ What Flow does ─────────────────────────────────────────────────────

class _WhatFlowDoes extends StatelessWidget {
  const _WhatFlowDoes();
  @override
  Widget build(BuildContext context) => const Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      FeatureNote(
        number: 1,
        title: 'Your day, as blocks',
        body: 'Each session rises from the line as it happens. Taller means more demanding.',
      ),
      SizedBox(height: 12),
      FeatureNote(
        number: 2,
        title: 'Pressure, under it',
        body: 'The curve climbs as focus wears down. The dashed line is where Flow speaks up.',
      ),
      SizedBox(height: 12),
      FeatureNote(
        number: 3,
        title: 'A nudge, with its reason',
        body: 'At the line Flow suggests a break and shows why. After it, pressure drops.',
      ),
      SizedBox(height: 12),
      FeatureNote(number: 4, title: 'It learns your rhythm', body: 'After a few sessions it times nudges to you, not to a fixed clock.'),
    ],
  );
}

/// A working day that plays itself once (tap to replay): the NOW line sweeps
/// across, each session's block grows as its time passes (dashed until then),
/// the pressure curve draws under it, reaches the nudge line, a nudge pops,
/// a break follows and pressure falls.
class _DayStage extends StatefulWidget {
  const _DayStage();
  @override
  State<_DayStage> createState() => _DayStageState();
}

class _DayStageState extends State<_DayStage> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 7500));

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (Motion.reduced(context)) {
        _c.value = 1;
      } else {
        LaunchGate.whenVisible(() {
          if (mounted) _c.forward();
        });
      }
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return Semantics(
      button: true,
      label: 'A day in Flow: three sessions, pressure rising to the nudge line, a break. Activate to replay.',
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () {
            if (!Motion.reduced(context)) _c.forward(from: 0);
          },
          child: Stack(
            children: [
              Positioned.fill(
                child: RepaintBoundary(child: CustomPaint(painter: _DayPainter(p, _c, MediaQuery.textScalerOf(context)))),
              ),
              Positioned(
                left: 0,
                bottom: 0,
                child: AnimatedBuilder(
                  animation: _c,
                  builder: (context, _) => AnimatedOpacity(
                    opacity: _c.isCompleted ? 1 : 0,
                    duration: Motion.fade,
                    child: Text(flowCaps('Click to play the day again'), style: FlowType.label(p, size: 9.5, color: p.text3)),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DayPainter extends CustomPainter {
  _DayPainter(this.p, this.anim, this.scaler) : super(repaint: anim);
  final FlowPalette p;
  final Animation<double> anim;
  final TextScaler scaler;

  // (start, end, height) as fractions of the day's width / the block room
  static const _sessions = [(0.06, 0.25, 0.62), (0.31, 0.55, 1.0), (0.66, 0.88, 0.78)];
  static const _nudgeAt = 0.55; // where pressure meets the line: end of the long session

  /// Pressure 0..1.1 at day fraction [x]: climbs through a session, eases
  /// between them, and falls after the break that follows the nudge.
  static double pressure(double x) {
    double seg(double a, double b, double from, double to) =>
        from + (to - from) * Curves.easeInOut.transform(((x - a) / (b - a)).clamp(0.0, 1.0));
    if (x < 0.06) return 0.12;
    if (x < 0.25) return seg(0.06, 0.25, 0.12, 0.58);
    if (x < 0.31) return seg(0.25, 0.31, 0.58, 0.42);
    if (x < 0.55) return seg(0.31, 0.55, 0.42, 1.0);
    if (x < 0.66) return seg(0.55, 0.66, 1.0, 0.2); // the break
    if (x < 0.88) return seg(0.66, 0.88, 0.2, 0.74);
    return seg(0.88, 1.0, 0.74, 0.5);
  }

  @override
  void paint(Canvas c, Size s) {
    // the day sweeps for the first 86% of the clock, then rests
    final now = (anim.value / 0.86).clamp(0.0, 1.0);
    // the brand field is a warm stone, light in the light theme: draw in ink,
    // not in paper white (which all but vanished on it)
    final ink = p.text1;
    final left = 8.0, right = s.width - 8;
    final w = right - left;
    double x(double f) => left + w * f;
    final floor = s.height * 0.5; // sessions stand on this line
    final room = floor - 46; // tallest block
    final lineY = s.height * 0.62; // the nudge line
    final baseY = s.height - 34; // pressure zero

    TextPainter text(String t, {double size = 10, Color? color, bool bold = false}) => TextPainter(
      text: TextSpan(
        text: flowCaps(t),
        style: FlowType.label(
          p,
          size: size,
          color: color ?? ink.withValues(alpha: 0.7),
        ).copyWith(fontWeight: bold ? FontWeight.w700 : null),
      ),
      textDirection: TextDirection.ltr,
      textScaler: scaler,
    )..layout();

    // floor + hours
    c.drawLine(Offset(left, floor), Offset(right, floor), Paint()..color = ink.withValues(alpha: 0.45));
    for (var i = 0; i <= 8; i++) {
      final hx = x(i / 8);
      c.drawLine(Offset(hx, floor), Offset(hx, floor + 4), Paint()..color = ink.withValues(alpha: 0.35));
      final tp = text('${9 + i}', size: 9, color: ink.withValues(alpha: 0.45));
      tp.paint(c, Offset(hx - tp.width / 2, floor + 7));
    }

    // sessions: solid as far as time has got, dashed for the rest of the plan
    final tones = [p.pastModerate, p.pastHeavy, p.pastLight];
    const depth = 9.0;
    for (final (i, (a, b, hf)) in _sessions.indexed) {
      final x0 = x(a), x1 = x(b), h = room * hf;
      final dash = Paint()
        ..color = ink.withValues(alpha: 0.5)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.1;
      // the plan (not yet)
      if (now < b) {
        final plan = Path()..addRect(Rect.fromLTRB(math.max(x0, x(now)), floor - h, x1, floor));
        for (final m in plan.computeMetrics()) {
          for (var d = 0.0; d < m.length; d += 7) {
            c.drawPath(m.extractPath(d, math.min(d + 3.5, m.length)), dash);
          }
        }
      }
      // what has happened
      if (now > a) {
        final xe = math.min(x(now), x1);
        final face = tones[i];
        c.drawRect(Rect.fromLTRB(x0, floor - h, xe, floor), Paint()..color = face);
        c.drawPath(
          Path()
            ..moveTo(x0, floor - h)
            ..lineTo(x0 + depth, floor - h - depth)
            ..lineTo(xe + depth, floor - h - depth)
            ..lineTo(xe, floor - h)
            ..close(),
          Paint()..color = Faces.top(face),
        );
        c.drawPath(
          Path()
            ..moveTo(xe, floor - h)
            ..lineTo(xe + depth, floor - h - depth)
            ..lineTo(xe + depth, floor - depth)
            ..lineTo(xe, floor)
            ..close(),
          Paint()..color = Faces.side(face),
        );
      }
    }

    // the nudge line
    final amber = p.amber;
    final nl = Paint()
      ..color = amber.withValues(alpha: 0.9)
      ..strokeWidth = 1.2;
    for (var d = left; d < right; d += 9) {
      c.drawLine(Offset(d, lineY), Offset(math.min(d + 4.5, right), lineY), nl);
    }
    final nlabel = text('nudge line', size: 9, color: amber);
    nlabel.paint(c, Offset(right - nlabel.width, lineY - nlabel.height - 4));

    // pressure, drawn as far as now
    double py(double f) => baseY - (baseY - lineY) * pressure(f);
    final curve = Path()..moveTo(x(0), py(0));
    const n = 120;
    final upto = (now * n).floor();
    for (var i = 1; i <= upto; i++) {
      curve.lineTo(x(i / n), py(i / n));
    }
    curve.lineTo(x(now), py(now));
    c.drawPath(
      Path.from(curve)
        ..lineTo(x(now), baseY)
        ..lineTo(x(0), baseY)
        ..close(),
      Paint()..color = ink.withValues(alpha: 0.16),
    );
    c.drawPath(
      curve,
      Paint()
        ..color = ink.withValues(alpha: 0.9)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeJoin = StrokeJoin.round,
    );
    final plabel = text('pressure', size: 9);
    plabel.paint(c, Offset(left, baseY + 6));

    // the nudge: pops where pressure meets the line, then the break
    if (now >= _nudgeAt) {
      final since = ((now - _nudgeAt) / 0.07).clamp(0.0, 1.0);
      final pop = Curves.easeOutBack.transform(since);
      final at = Offset(x(_nudgeAt), lineY);
      c.drawCircle(at, 6 * pop, Paint()..color = amber);
      // the suggestion itself, as a little card
      final tp = TextPainter(
        text: TextSpan(
          text: 'Take 5?',
          style: FlowType.headline(p, size: 17, color: p.text1),
        ),
        textDirection: TextDirection.ltr,
        textScaler: scaler,
      )..layout();
      final card = RRect.fromRectAndRadius(
        Rect.fromLTWH(at.dx - (tp.width + 26) / 2, at.dy - 18 - (tp.height + 14) * pop, tp.width + 26, (tp.height + 14) * pop),
        const Radius.circular(8),
      );
      c.drawRRect(card, Paint()..color = p.amberTint);
      c.drawRRect(
        card,
        Paint()
          ..style = PaintingStyle.stroke
          ..color = amber,
      );
      if (pop > 0.9) tp.paint(c, Offset(card.left + 13, card.top + 7));
      // the break: an amber bar on the floor between the two sessions
      final be = math.min(now, 0.66);
      if (be > _nudgeAt) {
        c.drawRRect(
          RRect.fromRectAndRadius(Rect.fromLTRB(x(_nudgeAt) + 3, floor - 7, x(be) - 3, floor - 2), const Radius.circular(2)),
          Paint()..color = amber,
        );
        if (now > 0.62) {
          final bl = text('break', size: 9, color: amber);
          bl.paint(c, Offset((x(_nudgeAt) + x(0.66)) / 2 - bl.width / 2, floor - 22));
        }
      }
    }

    // NOW
    if (anim.value < 0.86) {
      final nx = x(now);
      final accent = p.accent;
      c.drawLine(
        Offset(nx, 18),
        Offset(nx, baseY),
        Paint()
          ..color = accent
          ..strokeWidth = 1.6,
      );
      final tp = text('now', size: 9.5, color: accent, bold: true);
      tp.paint(c, Offset((nx - tp.width / 2).clamp(left, right - tp.width), 2));
    }
  }

  @override
  bool shouldRepaint(_DayPainter o) => o.p != p || o.scaler != scaler;
}

// ── 2 ─ What it senses + consent ───────────────────────────────────────────

class _Consent extends ConsumerWidget {
  const _Consent();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final consent = ref.watch(consentProvider);
    return AsyncSection(
      lines: 5,
      value: consent,
      onRetry: () => ref.invalidate(consentProvider),
      builder: (c) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final scope in ConsentScope.values)
            ConsentRow(
              title: consentTitle(scope) + (scope.required ? ' (required)' : ''),
              description: consentDescription(scope),
              value: c.granted(scope),
              onChanged: (v) => runGuarded(context, () => ref.read(consentProvider.notifier).set(scope, v)),
            ),
        ],
      ),
    );
  }
}

/// What reaches Flow, as live meters: dashed outlines until you allow a
/// signal, then they fill and move. Under them, what is never read.
class _SensingStage extends ConsumerWidget {
  const _SensingStage();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final c = ref.watch(consentProvider).value;
    bool on(ConsentScope s) => c?.granted(s) ?? false;
    final rows = [
      ('Typing rhythm', 'how often keys are pressed, never which', on(ConsentScope.behavior), 0),
      ('Window switches', 'how often, and the kind of app in front', on(ConsentScope.behavior), 1),
      ('Idle time', 'gaps with no activity', on(ConsentScope.behavior), 2),
      ('Eye openness', 'one number, worked out on this computer', on(ConsentScope.camera), 3),
      ('Next 3 hours', 'so a nudge avoids your meetings', on(ConsentScope.calendar), 4),
    ];
    return LayoutBuilder(
      builder: (context, box) {
        final compact = box.maxHeight < 420;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionLabel('What reaches Flow'),
            SizedBox(height: compact ? 8 : 14),
            for (final (label, detail, live, seed) in compact ? rows.take(3) : rows)
              Expanded(
                child: Row(
                  children: [
                    Expanded(
                      flex: 5,
                      child: _Meter(on: live, seed: seed),
                    ),
                    const SizedBox(width: 18),
                    Expanded(
                      flex: 6,
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            label,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(color: live ? p.text1 : p.text2, fontSize: 14.5, fontWeight: FontWeight.w600),
                          ),
                          Text(
                            live ? detail : 'off',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(color: p.text2, fontSize: 12, height: 1.35),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            SizedBox(height: compact ? 8 : 14),
            const SectionLabel('Never read'),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                for (final t in const ['window titles', 'what you type', 'your screen', 'camera images'])
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(color: p.hairline),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.close_rounded, size: 13, color: p.text3),
                        const SizedBox(width: 5),
                        Text(
                          t,
                          style: TextStyle(color: p.text2, fontSize: 12, decoration: TextDecoration.lineThrough),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ],
        );
      },
    );
  }
}

/// A small bar meter. Off: dashed outlines (not yet). On: the bars fill and
/// settle to a pattern, in the "past" stone tones.
class _Meter extends StatelessWidget {
  const _Meter({required this.on, required this.seed});
  final bool on;
  final int seed;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return TweenAnimationBuilder<double>(
      tween: Tween(end: on ? 1 : 0),
      duration: Motion.reduced(context) ? Duration.zero : const Duration(milliseconds: 700),
      curve: Curves.easeOutCubic,
      builder: (context, v, _) => CustomPaint(size: Size.infinite, painter: _MeterPainter(p, v, seed)),
    );
  }
}

class _MeterPainter extends CustomPainter {
  _MeterPainter(this.p, this.v, this.seed);
  final FlowPalette p;
  final double v;
  final int seed;

  @override
  void paint(Canvas c, Size s) {
    const n = 14;
    final r = math.Random(seed * 97 + 5);
    final slot = s.width / n;
    final w = slot * 0.6;
    final h = math.min(s.height * 0.72, 64.0);
    final base = s.height / 2 + h / 2;
    c.drawLine(Offset(0, base), Offset(s.width, base), Paint()..color = p.hairline);
    for (var i = 0; i < n; i++) {
      final f = 0.25 + r.nextDouble() * 0.75;
      final x = i * slot + (slot - w) / 2;
      final full = Rect.fromLTWH(x, base - h * f, w, h * f);
      if (v < 1) {
        // the outline of what would be measured
        final dash = Paint()
          ..color = p.future.withValues(alpha: 0.8 * (1 - v))
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1;
        for (var y = full.top; y < full.bottom; y += 5) {
          c.drawLine(Offset(full.left, y), Offset(full.left, math.min(y + 2.5, full.bottom)), dash);
          c.drawLine(Offset(full.right, y), Offset(full.right, math.min(y + 2.5, full.bottom)), dash);
        }
        for (var xx = full.left; xx < full.right; xx += 5) {
          c.drawLine(Offset(xx, full.top), Offset(math.min(xx + 2.5, full.right), full.top), dash);
        }
      }
      if (v > 0) {
        // fills from the line up, one bar after another
        final t = ((v * 1.4) - i / n * 0.4).clamp(0.0, 1.0);
        c.drawRRect(
          RRect.fromRectAndCorners(
            Rect.fromLTWH(x, base - h * f * t, w, h * f * t),
            topLeft: const Radius.circular(2),
            topRight: const Radius.circular(2),
          ),
          Paint()..color = f > 0.75 ? p.pastHeavy : (f > 0.5 ? p.pastModerate : p.pastLight),
        );
      }
    }
  }

  @override
  bool shouldRepaint(_MeterPainter o) => o.v != v || o.p != p || o.seed != seed;
}

// ── 3 ─ Connect the agent ──────────────────────────────────────────────────

class _Agent extends ConsumerStatefulWidget {
  const _Agent();
  @override
  ConsumerState<_Agent> createState() => _AgentState();
}

class _AgentState extends ConsumerState<_Agent> {
  final _code = TextEditingController();
  StageState _stage = StageState.rest;
  String? _error;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _pair(String code) async {
    setState(() {
      _stage = StageState.busy;
      _error = null;
    });
    try {
      await ref.read(agentStatusProvider.notifier).pair(code);
      if (mounted) setState(() => _stage = StageState.success);
    } catch (e) {
      if (mounted) {
        setState(() {
          _stage = StageState.error;
          _error = errorText(e);
          _code.clear();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final status = ref.watch(agentStatusProvider);
    final (line, sub) = switch (status.connection) {
      AgentConnection.connected => ('Connected', 'Agent ${status.agentVersion ?? ''} is measuring activity on this computer.'),
      AgentConnection.unpaired => ('Agent found', 'Enter the 6-digit code the agent shows.'),
      AgentConnection.disconnected => ('Agent not running', 'Install or start the Flow agent on this computer, then enter its code.'),
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          line,
          style: TextStyle(color: p.text1, fontSize: 15, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 4),
        Text(sub, style: TextStyle(color: p.text2, fontSize: 13)),
        if (status.connection != AgentConnection.connected) ...[
          const SizedBox(height: 18),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 340),
            child: CodeBoxes(controller: _code, onComplete: _pair, enabled: _stage != StageState.busy),
          ),
          if (_error != null) ...[const SizedBox(height: 8), AuthError(_error!)],
          const SizedBox(height: 8),
          Text('You can do this later from Settings › Agent.', style: TextStyle(color: p.text3, fontSize: 12)),
        ],
      ],
    );
  }
}

/// Flow ⟷ agent, large: the link is dashed until a real pairing, then solid.
class _AgentStage extends ConsumerWidget {
  const _AgentStage();
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final connected = ref.watch(agentStatusProvider).connection == AgentConnection.connected;
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Transform.scale(scale: 1.5, child: _ConnectionLine(connected: connected)),
        ),
        const SizedBox(height: 44),
        Text(
          connected ? 'This computer is linked.' : 'Not linked yet: the line is dashed until the agent answers.',
          textAlign: TextAlign.center,
          style: FlowType.note(p, size: 15),
        ),
        const SizedBox(height: 36),
        // what travels along that line, and what does not
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionLabel('Sent along it'),
                    const SizedBox(height: 8),
                    for (final t in const [
                      'key presses per minute',
                      'window switches per minute',
                      'idle seconds',
                      'the kind of app in front',
                    ])
                      Padding(
                        padding: const EdgeInsets.only(bottom: 5),
                        child: Row(
                          children: [
                            Icon(Icons.check_rounded, size: 14, color: p.text2),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(t, style: TextStyle(color: p.text1, fontSize: 13)),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 24),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionLabel('Never'),
                    const SizedBox(height: 8),
                    for (final t in const ['which keys', 'window titles', 'file or site names', 'anything on your screen'])
                      Padding(
                        padding: const EdgeInsets.only(bottom: 5),
                        child: Row(
                          children: [
                            Icon(Icons.close_rounded, size: 14, color: p.text3),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                t,
                                style: TextStyle(color: p.text2, fontSize: 13, decoration: TextDecoration.lineThrough),
                              ),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// App ⟷ agent: a dashed line (not yet) that becomes solid only on a real
/// pairing; the plug end snaps in.
class _ConnectionLine extends StatelessWidget {
  const _ConnectionLine({required this.connected});
  final bool connected;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    Widget node(String label, IconData icon) => Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: p.raised,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: p.hairline),
          ),
          child: Icon(icon, size: 18, color: p.text2),
        ),
        const SizedBox(height: 6),
        Text(flowCaps(label), style: FlowType.label(p, size: 9, color: p.text3)),
      ],
    );
    return Row(
      children: [
        node('Flow', Icons.space_dashboard_outlined),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: TweenAnimationBuilder<double>(
              tween: Tween(end: connected ? 1 : 0),
              duration: const Duration(milliseconds: 500),
              curve: Curves.easeOutCubic,
              builder: (context, v, _) => CustomPaint(size: const Size(double.infinity, 12), painter: _LinkPainter(p, v)),
            ),
          ),
        ),
        node('Agent', Icons.memory_outlined),
      ],
    );
  }
}

class _LinkPainter extends CustomPainter {
  _LinkPainter(this.p, this.v);
  final FlowPalette p;
  final double v;

  @override
  void paint(Canvas c, Size s) {
    final y = s.height / 2;
    final dashed = Paint()
      ..color = p.text3
      ..strokeWidth = 1.2;
    for (var x = 6.0; x < s.width - 6; x += 8) {
      c.drawLine(Offset(x, y), Offset(x + 4, y), dashed);
    }
    if (v > 0) {
      c.drawLine(
        Offset(6, y),
        Offset(6 + (s.width - 12) * v, y),
        Paint()
          ..color = p.accent
          ..strokeWidth = 1.6,
      );
    }
  }

  @override
  bool shouldRepaint(_LinkPainter o) => o.v != v || o.p != p;
}

// ── 4 ─ Nudge style ────────────────────────────────────────────────────────

class _NudgeStage extends ConsumerWidget {
  const _NudgeStage();
  @override
  Widget build(BuildContext context, WidgetRef ref) => Center(
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 720),
      child: NudgeStylePreview(style: ref.watch(desktopPrefsProvider).nudgeStyle),
    ),
  );
}

// ── 5 ─ Practice nudge ─────────────────────────────────────────────────────

class _PracticeNotes extends StatelessWidget {
  const _PracticeNotes();
  @override
  Widget build(BuildContext context) => const Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      FeatureNote(
        number: 1,
        title: 'Take the break',
        body: 'Flow times it and keeps the session for you. Afterwards pressure starts low again.',
      ),
      SizedBox(height: 12),
      FeatureNote(number: 2, title: 'Snooze', body: 'Pushes the nudge back 5, 10 or 20 minutes. Flow notes that the timing was early.'),
      SizedBox(height: 12),
      FeatureNote(number: 3, title: 'Why?', body: 'Shows which signals pushed pressure up, and by how much.'),
      SizedBox(height: 12),
      FeatureNote(number: 4, title: 'The flag', body: 'Tell Flow a nudge was wrong. It is the fastest way to teach it.'),
    ],
  );
}

/// A nudge to play with. Nothing here is sent anywhere.
class _PracticeStage extends StatefulWidget {
  const _PracticeStage();
  @override
  State<_PracticeStage> createState() => _PracticeStageState();
}

class _PracticeStageState extends State<_PracticeStage> {
  bool _why = false;
  String? _note;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    // the card grows with the stage (it stays fully clickable when scaled)
    builder: (context, box) => Center(
      child: SingleChildScrollView(
        child: Transform.scale(
          scale: (box.maxWidth * 0.8 / 520).clamp(1.0, 1.5),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: NudgeCardView(
              message: "You're 48 minutes in and your typing rhythm has broken up. A short break now usually buys you the next hour.",
              reason: 'Window switching is 40% above your usual for this hour.',
              onBreak: () => setState(() => _note = 'In a real session this starts your break.'),
              onSnooze: (m) => setState(() => _note = 'snoozed $m min'),
              onDismiss: () => setState(() => _note = 'dismissed: Flow will learn from that'),
              onReport: () => setState(() => _note = 'flagged as wrong: Flow adjusts its timing'),
              onWhy: () => setState(() => _why = !_why),
              why: _why
                  ? const [
                      (name: 'Window switching', share: 0.46),
                      (name: 'Typing rhythm', share: 0.31),
                      (name: 'Time into cycle', share: 0.23),
                    ]
                  : null,
              note: _note,
            ),
          ),
        ),
      ),
    ),
  );
}

// ── 6 ─ Start ──────────────────────────────────────────────────────────────

class _StartBody extends StatelessWidget {
  const _StartBody({required this.minutes});
  final int minutes;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final ends = DateTime.now().add(Duration(minutes: minutes));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            DurationNumeral(minutes, size: 40),
            const SizedBox(width: 12),
            Flexible(child: Text('ends ${TimeOfDay.fromDateTime(ends).format(context)}', style: FlowType.note(p, size: 14.5))),
          ],
        ),
        const SizedBox(height: 16),
        const FeatureNote(number: 1, title: 'Turn the dial', body: 'Drag it round, scroll over it, or click a point on the ring.'),
        const SizedBox(height: 12),
        const FeatureNote(
          number: 2,
          title: 'Past three hours',
          body: 'It carries on to a second ring, up to four hours. Flow suggests breaks along the way.',
        ),
      ],
    );
  }
}

class _DialStage extends StatelessWidget {
  const _DialStage({required this.minutes, required this.onMinutes, required this.busy, required this.onStart});
  final int minutes;
  final ValueChanged<int> onMinutes;
  final bool busy;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) => Center(
      // the dial takes the room it is given
      child: DurationDial(
        minutes: minutes,
        onChanged: onMinutes,
        size: (box.biggest.shortestSide * 0.72).clamp(180.0, 420.0),
        onCenterTap: busy ? null : onStart,
      ),
    ),
  );
}
