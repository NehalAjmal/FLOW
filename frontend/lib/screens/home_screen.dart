import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../tutorial/coach.dart';
import '../api/models/agent.dart';
import '../api/models/consent.dart';
import '../api/models/day.dart';
import '../api/models/schedule.dart';
import '../api/models/session.dart';
import '../desktop/window_controller.dart';
import '../router/routes.dart';
import '../state/account_controllers.dart';
import '../state/auth_controller.dart';
import '../state/data_providers.dart';
import '../state/session_controller.dart';
import '../tasks/tasks.dart';
import '../theme/motion.dart';
import '../theme/tokens.dart';
import '../ui/dial.dart';
import '../ui/drum_wheel.dart';
import '../ui/iso/month_terrain.dart';
import '../ui/feature_note.dart';
import '../ui/kit.dart';
import '../ui/loading_blocks.dart';
import '../ui/score/day_score.dart';
import '../widgets/common.dart' show errorText, runGuarded, showError;
import 'shell.dart' show FlowHeader;
import '../core/session_clock.dart';

String demandLabel(Demand d) => switch (d) {
  Demand.light => 'Light',
  Demand.moderate => 'Moderate',
  Demand.heavy => 'Heavy',
};

const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// The day in one line: the longest unbroken stretch of focus (sessions less
/// than 10 min apart join), or the block running now. Null when there is
/// nothing to say yet.
String? dayHeadline(DayTimeline? d, {required bool today, required String weekday}) {
  if (d == null) return null;
  if (today && d.active != null) return 'In a focus block until ${_hm(d.active!.end)}';
  final done = d.sessions.where((s) => s.state == TimelineSessionState.done).toList()..sort((a, b) => a.start.compareTo(b.start));
  // join sessions less than 10 min apart into stretches; keep the longest
  final spans = <(DateTime, DateTime)>[];
  for (final s in done) {
    if (spans.isNotEmpty && s.start.difference(spans.last.$2).inMinutes <= 10) {
      final (a, b) = spans.removeLast();
      spans.add((a, s.end.isAfter(b) ? s.end : b));
    } else {
      spans.add((s.start, s.end));
    }
  }
  final best = spans.isEmpty ? null : spans.reduce((x, y) => y.$2.difference(y.$1) > x.$2.difference(x.$1) ? y : x);
  final when = today ? 'today' : 'on $weekday';
  if (best == null || best.$2.difference(best.$1).inMinutes < 20) return today ? null : 'No long stretch $when';
  return 'Best stretch $when: ${_hm(best.$1)} to ${_hm(best.$2)}';
}

String _hm(DateTime t) => '${(t.hour - 1) % 12 + 1}:${t.minute.toString().padLeft(2, '0')}';
DateTime _day(DateTime t) => DateTime(t.year, t.month, t.day);

/// Home (DESIGN_SPEC §6): DISPLAY (Day Score) → READ-OUT → CONTROL DECK
/// [look back: wheel + terrain] [start: presets, task, demand, dial, Start].
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});
  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  late DateTime _selected = _day(DateTime.now());
  DateTime _now = DateTime.now();
  Timer? _tick;
  int? _minutes; // null until the suggestion arrives
  Demand _demand = Demand.moderate;
  bool _shareAi = false;
  bool _busy = false;
  bool _explain = false; // "How to read this" layer
  final _task = TextEditingController();
  String? _taskId; // the task picked from "Next up", if any

  @override
  void initState() {
    super.initState();
    // the Score moves with the clock; once every 30 s is plenty for minutes
    _tick = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    _task.dispose();
    super.dispose();
  }

  bool get _isToday => DateUtils.isSameDay(_selected, _now);

  Future<void> _start(int minutes) async {
    if (_busy) return; // a second click or key press while the first is in flight
    setState(() => _busy = true);
    final ok = await runGuarded(
      context,
      () => ref
          .read(liveSessionProvider.notifier)
          .start(
            StartSessionRequest(
              // an empty field is "no task", not a task called ""
              taskText: _task.text.trim().isEmpty ? null : _task.text.trim(),
              demand: _demand,
              plannedMinutes: minutes,
              shareTaskWithLlm: _shareAi && _task.text.trim().isNotEmpty,
            ),
          ),
    );
    if (!mounted) return;
    // log this session against the picked task, unless its text was changed
    if (ok) {
      final picked = ref.read(tasksProvider).value?.where((t) => t.id == _taskId).firstOrNull;
      ref.read(activeTaskIdProvider.notifier).set(picked != null && picked.title == _task.text.trim() ? picked.id : null);
    }
    setState(() {
      _busy = false;
      if (ok) {
        _taskId = null;
        _selected = _day(DateTime.now());
        _task.clear();
      }
    });
  }

  Future<void> _end() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('End this session?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep going')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('End session')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final summary = await ref.read(liveSessionProvider.notifier).end();
      if (mounted) context.go(Routes.sessionEndFor(summary.sessionId), extra: summary);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final user = ref.watch(currentUserProvider);
    final day = ref.watch(dayTimelineProvider(_selected));
    final live = ref.watch(liveSessionProvider).value;
    final suggested = ref.watch(preCheckProvider).value?.suggestedMinutes;
    final minutes = _minutes ?? suggested ?? 50;
    final hour = _now.hour;
    final greet = hour < 12 ? 'Good morning' : (hour < 18 ? 'Good afternoon' : 'Good evening');
    final first = user?.name.trim().split(' ').first ?? '';
    final headline = dayHeadline(day.value, today: _isToday, weekday: _weekdays[_selected.weekday - 1]);

    return LayoutBuilder(
      builder: (context, viewport) {
        // Rule B: never look empty. The Score takes the room the window has.
        // up to 640: on a tall window the Score grows instead of leaving an
        // empty band under the deck
        // The pressure track is kept short (about 40% less than it was): it
        // explains the least, so the deck sits higher on the page.
        final scoreH = ((viewport.maxHeight - 96 - 52 - 300) * 0.78).clamp(300.0, 480.0);
        return ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            FlowHeader(
              // the day's one-line conclusion; the greeting only while there
              // is nothing to conclude yet
              title: headline ?? (first.isEmpty ? greet : '$greet, $first'),
              subtitle: [
                if (headline != null && first.isNotEmpty) '$greet, $first',
                '${_weekdays[_now.weekday - 1].substring(0, 3)} ${_now.day} ${_months[_now.month - 1]}',
              ].join(' · '),
              action: _ExplainToggle(on: _explain, onChanged: (v) => setState(() => _explain = v)),
            ),
            const _AgentBanner(),
            const SizedBox(height: 8),
            _ExplainRow(
              on: _explain,
              notes: const [
                (
                  1,
                  'Your day, as blocks',
                  'Each session rises from the hour line. Taller = more demanding. Fresh ones start green and dry to stone.',
                ),
                (
                  2,
                  'Pressure',
                  'How close you are to needing a break. It turns amber only above the dashed nudge line. The dots under it are your breaks.',
                ),
                (3, 'Now', 'The green line. Dashed blocks to its right are planned, not yet happened.'),
              ],
            ),
            // ── DISPLAY ─────────────────────────────────────────────────────
            switch (day) {
              AsyncData(:final value) => _Display(
                height: scoreH,
                day: value,
                now: _now,
                ghost: live == null && _isToday ? minutes : 0,
                onGhost: (m) => setState(() => _minutes = m),
                onSession: (s) => s.id == null ? null : context.go(Routes.sessionEndFor(s.id!)),
              ),
              AsyncError(:final error) => _Inline(text: errorText(error), onRetry: () => ref.invalidate(dayTimelineProvider(_selected))),
              _ => SizedBox(
                height: scoreH,
                child: Padding(
                  padding: const EdgeInsets.only(right: 24),
                  child: Center(
                    child: LoadingBlocks(height: scoreH * 0.55, count: 8, label: 'Loading your day'),
                  ),
                ),
              ),
            },
            // ── READ-OUT ───────────────────────────────────────────────────
            Padding(padding: const EdgeInsets.only(right: 24, top: 2, bottom: 14), child: ReadOut(_readout(day.value))),
            Divider(height: 1, thickness: 1, color: p.hairline, endIndent: 24),
            const SizedBox(height: 16),
            _ExplainRow(
              on: _explain,
              notes: const [
                (4, 'Look back', 'Your last four weeks as a little city. Scroll the wheel or click a day to see it above.'),
                (5, 'Start', 'Pick a length on the dial (drag it, or use the presets). The ghost block above shows where it would land.'),
              ],
            ),
            // ── CONTROL DECK ───────────────────────────────────────────────
            Padding(
              padding: const EdgeInsets.only(right: 24),
              child: LayoutBuilder(
                builder: (context, box) {
                  final lookBack = ColorField(
                    tone: FieldTone.past,
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                    child: CoachMark(
                      'lookback',
                      child: _LookBack(selected: _selected, today: _day(_now), onSelect: (d) => setState(() => _selected = _day(d))),
                    ),
                  );
                  // about to start = planned (ultramarine); running = now (green)
                  final start = CoachMark(
                    'deck',
                    child: ColorField(
                      tone: live == null ? FieldTone.planned : FieldTone.now,
                      padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
                      child: live == null
                          ? _StartGroup(
                              minutes: minutes,
                              suggestion: suggested,
                              demand: _demand,
                              task: _task,
                              shareAi: _shareAi,
                              busy: _busy,
                              now: _now,
                              onMinutes: (m) => setState(() => _minutes = m),
                              onDemand: (d) => setState(() => _demand = d),
                              onShareAi: (v) => setState(() => _shareAi = v),
                              onStart: () => _start(minutes),
                              onPickTask: (t, m) => setState(() {
                                _taskId = t.id;
                                _task.text = t.title;
                                _minutes = m;
                              }),
                            )
                          : _SessionGroup(live: live, onEnd: _end),
                    ),
                  );
                  // below ~1100 px the two groups stack; the order stays display → read-out → deck
                  if (box.maxWidth < 860) {
                    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [start, const SizedBox(height: 20), lookBack]);
                  }
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 4, child: lookBack),
                      const SizedBox(width: 24),
                      Expanded(flex: 6, child: start),
                    ],
                  );
                },
              ),
            ),
          ],
        );
      },
    );
  }

  String _readout(DayTimeline? d) {
    final name = _weekdays[_selected.weekday - 1];
    final parts = <String>['$name ${_selected.day}'];
    if (d != null) {
      parts.add(flowDuration(d.totals.focusMinutes, caps: true)); // shown in caps
      if (_isToday) {
        final next = d.meetings.where((m) => m.start.isAfter(_now)).toList()..sort((a, b) => a.start.compareTo(b.start));
        if (next.isNotEmpty) parts.add('next meeting ${_hm(next.first.start)}');
      } else {
        parts.add('${d.totals.breaksTaken} of ${d.totals.breaksSuggested} breaks');
      }
    }
    return parts.join(' · ');
  }
}

class _Inline extends StatelessWidget {
  const _Inline({required this.text, this.onRetry});
  final String text;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return SizedBox(
      height: 300,
      child: Center(
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off_outlined, size: 16, color: p.problem),
            const SizedBox(width: 8),
            Text(text, style: TextStyle(color: p.text2)),
            if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _AgentBanner extends ConsumerWidget {
  const _AgentBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final a = ref.watch(agentStatusProvider);
    final consent = ref.watch(consentProvider).value;
    if (a.connection == AgentConnection.connected || consent == null || !consent.granted(ConsentScope.behavior)) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(right: 24, bottom: 4),
      child: Row(
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: p.text3),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Behavior sensing isn\'t connected, so Flow can only nudge on timing for now.',
              style: TextStyle(fontSize: 12.5, color: p.text2),
            ),
          ),
          TextButton(onPressed: () => context.go(Routes.settings), child: const Text('Connect the agent')),
        ],
      ),
    );
  }
}

// ── DISPLAY: margin numbers + the Day Score ───────────────────────────────

class _Display extends StatelessWidget {
  const _Display({
    required this.height,
    required this.day,
    required this.now,
    required this.ghost,
    required this.onGhost,
    required this.onSession,
  });
  final double height;
  final DayTimeline day;
  final DateTime now;
  final int ghost;
  final ValueChanged<int> onGhost;
  final void Function(TimelineSession) onSession;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final t = day.totals;
    final delta = t.usualFocusMinutes == null ? null : t.focusMinutes - t.usualFocusMinutes!;
    Widget margin(Widget big, String label, String? sub, {Color? subColor}) => Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        big,
        const SizedBox(height: 3),
        Text(flowCaps(label), style: FlowType.label(p, size: 9, color: p.text3)),
        if (sub != null) Text(sub, style: FlowType.chart(p, size: 10, color: subColor ?? p.text3)),
      ],
    );
    final h = height;
    return SizedBox(
      height: h,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 112,
            child: Stack(
              children: [
                Positioned(
                  top: (h * 0.40).clamp(0, 112.0) - 52,
                  child: margin(
                    DurationNumeral(t.focusMinutes, size: 28),
                    'focused',
                    delta == null
                        ? null
                        : // two lines: the margin is 112 px and "vs usual" was cut to "vs u"
                          '${delta >= 0 ? '+' : '−'}${flowDuration(delta.abs())}\nvs your usual',
                  ),
                ),
                Positioned(
                  top: (h * 0.40).clamp(0, 112.0) + 76,
                  child: margin(
                    TabularNumeral('${t.breaksTaken}/${t.breaksSuggested}', style: FlowType.numeral(p, 28)),
                    'breaks',
                    t.breaksSkipped > 0 ? '${t.breaksSkipped} skipped' : null,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(right: 24),
              child: CoachMark(
                'day',
                child: DayScore(
                  day: day,
                  now: now,
                  ghostMinutes: ghost,
                  height: h,
                  onGhostDrag: ghost > 0 ? onGhost : null,
                  onSessionTap: onSession,
                  // drag across the future to plan a session on this weekday
                  onScheduleDraft: (a, b) => _scheduleFromDraft(context, a, b),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── DECK: look back (wheel flush with terrain) ───────────────────────────

class _LookBack extends ConsumerWidget {
  const _LookBack({required this.selected, required this.today, required this.onSelect});
  final DateTime selected;
  final DateTime today;
  final ValueChanged<DateTime> onSelect;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final mins = ref.watch(rollingMinutesProvider);
    final offset = selected.difference(today).inDays; // 0 = today, -27 = four weeks back
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionLabel('Look back'),
        const SizedBox(height: 10),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // the wheel picks the day; its caption says which, so what it
            // does is never a guess
            Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DrumWheel(
                  value: offset,
                  min: -27,
                  max: 0,
                  length: 184,
                  onChanged: (d) => onSelect(today.add(Duration(days: d))),
                  semanticLabel: 'Day',
                  semanticValue: (d) => d == 0 ? 'today' : '${-d} days ago',
                ),
                const SizedBox(height: 6),
                SizedBox(
                  width: 44,
                  child: AnimatedSwitcher(
                    duration: Motion.reduced(context) ? Duration.zero : Motion.fade,
                    child: Text(
                      offset == 0 ? 'today' : '${-offset}d ago',
                      key: ValueKey(offset),
                      textAlign: TextAlign.center,
                      style: FlowType.chart(p, size: 9, color: p.text2),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(width: 6),
            Expanded(
              child: switch (mins) {
                AsyncData(:final value) => LayoutBuilder(
                  builder: (context, box) => MonthTerrain(
                    month: today,
                    minutes: value,
                    selected: selected,
                    onSelect: onSelect,
                    size: Size(box.maxWidth.clamp(220, 440), 220),
                  ),
                ),
                AsyncError() => Text('Couldn\'t load the last 4 weeks.', style: TextStyle(color: p.text3, fontSize: 12)),
                _ => const SizedBox(height: 220, child: Center(child: LoadingBlocks(height: 110, count: 5))),
              },
            ),
          ],
        ),
      ],
    );
  }
}

// ── DECK: start group ──────────────────────────────────────────────────────

class _StartGroup extends ConsumerWidget {
  const _StartGroup({
    required this.minutes,
    required this.suggestion,
    required this.demand,
    required this.task,
    required this.shareAi,
    required this.busy,
    required this.now,
    required this.onMinutes,
    required this.onDemand,
    required this.onShareAi,
    required this.onStart,
    required this.onPickTask,
  });

  final void Function(FlowTask task, int minutes) onPickTask;
  final int minutes;
  final int? suggestion;
  final Demand demand;
  final TextEditingController task;
  final bool shareAi;
  final bool busy;
  final DateTime now;
  final ValueChanged<int> onMinutes;
  final ValueChanged<Demand> onDemand;
  final ValueChanged<bool> onShareAi;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final llm = ref.watch(consentProvider).value?.granted(ConsentScope.llm) ?? false;
    final ends = now.add(Duration(minutes: minutes));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionLabel('Start'),
        const SizedBox(height: 10),
        LayoutBuilder(
          builder: (context, box) {
            // Too narrow for controls · dial · button side by side: the Start
            // button moves under the controls instead of being squeezed.
            final tight = box.maxWidth < 660;
            final start = Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                CoachMark(
                  'start',
                  child: Pressable(
                    tone: PressableTone.primary,
                    onPressed: busy ? null : onStart,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    // shrinks a little before it would ever clip
                    child: FittedBox(
                      fit: BoxFit.scaleDown,
                      child: Text(busy ? 'Starting…' : 'Start · ends ${_hm(ends)}', maxLines: 1, softWrap: false),
                    ),
                  ),
                ),
                if (suggestion != null) ...[
                  const SizedBox(height: 8),
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(
                      '✦ $suggestion min suggested',
                      maxLines: 1,
                      softWrap: false,
                      style: TextStyle(fontSize: 11, color: p.text3),
                    ),
                  ),
                ],
                // past one turn of the dial: say what a session this long means
                if (minutes > DurationDial.fullTurn) ...[
                  const SizedBox(height: 6),
                  Text(
                    minutes >= DurationDial.healthyMax
                        ? '4 h is the most for one session. Flow will suggest breaks along the way.'
                        : 'A long one. Flow will suggest breaks along the way.',
                    style: TextStyle(fontSize: 11, height: 1.35, color: p.amber),
                  ),
                ],
              ],
            );
            return Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                // controls keep a slim width so the dial sits near the middle of
                // the deck instead of being pushed to the far edge; they give way
                // first when the window narrows
                SizedBox(
                  width: (tight ? box.maxWidth - 204 - 24 : box.maxWidth - 204 - 32 - 28 - 240).clamp(160.0, 320.0),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 340),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Wrap(
                          spacing: 8,
                          children: [
                            for (final m in const [25, 50, 90])
                              Pressable(
                                selected: minutes == m,
                                onPressed: () => onMinutes(m),
                                semanticLabel: '$m minutes',
                                child: Text('$m'),
                              ),
                          ],
                        ),
                        _NextUp(onPick: onPickTask, current: task),
                        const SizedBox(height: 12),
                        FlowTextField(controller: task, hint: 'What are you working on?'),
                        const SizedBox(height: 14),
                        SnapSlider(
                          steps: 3,
                          index: demand.index,
                          width: 200,
                          labels: const ['light', 'moderate', 'heavy'],
                          semanticLabel: 'How demanding',
                          onChanged: (i) => onDemand(Demand.values[i]),
                        ),
                        if (llm) ...[
                          const SizedBox(height: 10),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              PillToggle(value: shareAi, onChanged: onShareAi, semanticLabel: 'Share task with the AI assistant'),
                              const SizedBox(width: 8),
                              Flexible(
                                child: Text('Let the AI assistant see this task', style: TextStyle(fontSize: 12, color: p.text2)),
                              ),
                            ],
                          ),
                        ],
                        if (tight) ...[const SizedBox(height: 14), start],
                      ],
                    ),
                  ),
                ),
                SizedBox(width: tight ? 24 : 32),
                CoachMark(
                  'dial',
                  child: DurationDial(minutes: minutes, suggestion: suggestion, size: 204, onChanged: onMinutes, onCenterTap: busy ? null : onStart),
                ),
                if (!tight) ...[const SizedBox(width: 28), Flexible(flex: 3, child: start)],
                const Spacer(),
              ],
            );
          },
        ),
      ],
    );
  }
}

/// Up to three open tasks; picking one fills the task and the dial (sized
/// by your own pace). Hidden when there are no tasks.
class _NextUp extends ConsumerWidget {
  const _NextUp({required this.onPick, required this.current});
  final void Function(FlowTask task, int minutes) onPick;
  final TextEditingController current;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final all = ref.watch(tasksProvider).value ?? const <FlowTask>[];
    final open = all.where((t) => !t.done).take(3).toList();
    if (open.isEmpty) return const SizedBox(height: 0);
    final cal = Calibration.of(all);
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: ListenableBuilder(
        listenable: current,
        builder: (context, _) => Wrap(
          spacing: 6,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(flowCaps('next up'), style: FlowType.label(p, size: 9, color: p.text3)),
            for (final t in open)
              Pressable(
                selected: current.text.trim() == t.title,
                semanticLabel: 'Work on ${t.title}',
                onPressed: () => onPick(t, suggestedFor(t.estimateMinutes, cal)),
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 150),
                  child: Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ── DECK: session group (replaces start, same width) ──────────────────────

class _SessionGroup extends ConsumerWidget {
  const _SessionGroup({required this.live, required this.onEnd});
  final LiveSession live;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = FlowPalette.of(context);
    final now = ref.watch(clockProvider).value ?? DateTime.now();
    final s = live.session;
    final elapsed = s.focusAt(now, ref.watch(pausedSinceProvider));
    final total = Duration(minutes: s.plannedMinutes);
    final left = total - elapsed;
    final frac = (elapsed.inSeconds / total.inSeconds).clamp(0.0, 1.0);
    // while paused the end slides with the clock
    final ends = now.add(left);
    String mmss(Duration d) => '${d.inMinutes.abs()}:${(d.inSeconds.abs() % 60).toString().padLeft(2, '0')}';
    final notifier = ref.read(liveSessionProvider.notifier);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionLabel('Session'),
        const SizedBox(height: 10),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            DurationDial(
              minutes: s.plannedMinutes,
              onChanged: null,
              mode: DialMode.progress,
              fraction: frac,
              size: 196,
              centerLabel: left.isNegative ? '+${mmss(left)}' : mmss(left),
            ),
            const SizedBox(width: 20),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(s.taskText?.isNotEmpty == true ? s.taskText! : 'Focus session', style: TextStyle(fontSize: 16, color: p.text1)),
                  const SizedBox(height: 4),
                  Text('ends ${_hm(ends)} · ${demandLabel(s.demand).toLowerCase()}', style: FlowType.label(p, size: 10.5)),
                  const SizedBox(height: 4),
                  Text(switch (live.connection) {
                    LiveConnection.live => '',
                    LiveConnection.polling => 'Updating every few seconds',
                    LiveConnection.offline => 'Offline: keeping time on this computer',
                  }, style: TextStyle(fontSize: 11, color: live.connection == LiveConnection.offline ? p.problem : p.text3)),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      Pressable(
                        onPressed: () => runGuarded(context, () => notifier.extend(15)),
                        tooltip: 'Extend by 15 minutes',
                        child: const Text('+15'),
                      ),
                      Pressable(
                        onPressed: () => runGuarded(context, () => s.paused ? notifier.resume() : notifier.pause()),
                        child: Text(s.paused ? 'Resume' : 'Pause'),
                      ),
                      // desktop only, and only during a session: shrink to the widget
                      if (ref.watch(desktopHostProvider).isDesktop)
                        ValueListenableBuilder(
                          valueListenable: ref.read(windowModeProvider.notifier).widgetUnavailable,
                          builder: (context, unavailable, _) => Pressable(
                            onPressed: unavailable ? null : ref.read(windowModeProvider.notifier).shrink,
                            tooltip: unavailable
                                ? "The small widget couldn't open on this computer, so Flow stays in its window"
                                : 'Pop the session out into a small always-on-top widget',
                            child: const Text('Pop out'),
                          ),
                        ),
                      Pressable(tone: PressableTone.primary, onPressed: onEnd, child: const Text('End')),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// Header action: "How to read this" toggles numbered captions over Home.
class _ExplainToggle extends StatelessWidget {
  const _ExplainToggle({required this.on, required this.onChanged});
  final bool on;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return Pressable(
      selected: on,
      onPressed: () => onChanged(!on),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      semanticLabel: on ? 'Hide explanations' : 'How to read this screen',
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 16,
            height: 16,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: on ? p.onSelected : p.text2, width: 1.2),
            ),
            child: Text(
              '?',
              style: TextStyle(fontSize: 10, color: on ? p.onSelected : p.text2, fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(width: 7),
          Text(on ? 'Hide' : 'How to read this', style: const TextStyle(fontSize: 12)),
        ],
      ),
    );
  }
}

/// A row of numbered captions that grows in (and out) above a section.
class _ExplainRow extends StatelessWidget {
  const _ExplainRow({required this.on, required this.notes});
  final bool on;
  final List<(int, String, String)> notes;

  @override
  Widget build(BuildContext context) => AnimatedSize(
    duration: const Duration(milliseconds: 280),
    curve: Curves.easeOutCubic,
    alignment: Alignment.topLeft,
    child: !on
        ? const SizedBox(width: double.infinity)
        : Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final (n, t, b) in notes)
                  Expanded(
                    child: ExplainCaption(number: n, title: t, body: b),
                  ),
              ],
            ),
          ),
  );
}

/// Turns a drag on Home's future into a schedule for that weekday, with Undo.
Future<void> _scheduleFromDraft(BuildContext context, DateTime a, DateTime b) async {
  final container = ProviderScope.containerOf(context);
  final hm = Schedule.hm;
  try {
    final saved = await container
        .read(schedulesProvider.notifier)
        .add(Schedule(name: 'Planned session', start: hm(a.hour * 60 + a.minute), end: hm(b.hour * 60 + b.minute), weekdays: [a.weekday]));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Planned ${saved.start}–${saved.end} every ${const ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][a.weekday - 1]}. Edit it in Settings.',
        ),
        action: SnackBarAction(label: 'Undo', onPressed: () => container.read(schedulesProvider.notifier).remove(saved.id!)),
      ),
    );
  } catch (e) {
    if (context.mounted) showError(context, e);
  }
}
