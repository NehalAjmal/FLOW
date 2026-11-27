import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/models/session.dart';
import '../router/routes.dart';
import '../state/session_controller.dart';
import '../tasks/tasks.dart';
import '../theme/motion.dart';
import '../theme/tokens.dart';
import '../ui/appear.dart';
import '../ui/feature_note.dart';
import '../ui/kit.dart';
import '../widgets/common.dart' show runGuarded;
import 'shell.dart' show FlowHeader;

const _estimates = [15, 30, 60, 90];

/// Tasks: a to-do list where every item carries a time estimate. Starting a
/// session from a task logs its real focus time against it, and the pace
/// gauge shows how your estimates compare: calibrated to you, never graded.
class TasksScreen extends ConsumerStatefulWidget {
  const TasksScreen({super.key});
  @override
  ConsumerState<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends ConsumerState<TasksScreen> {
  final _title = TextEditingController();
  int _estimate = 30;
  bool _showDone = true;

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final t = await ref.read(tasksProvider.notifier).add(_title.text, _estimate);
    if (t != null) setState(_title.clear);
  }

  Future<void> _remove(FlowTask t) async {
    final removed = await ref.read(tasksProvider.notifier).remove(t.id);
    if (removed == null || !mounted) return;
    final (task, index) = removed;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text('Removed "${task.title}"'),
          action: SnackBarAction(label: 'Undo', onPressed: () => ref.read(tasksProvider.notifier).restore(task, index)),
        ),
      );
  }

  Future<void> _start(FlowTask t, Calibration? cal) async {
    final minutes = suggestedFor(t.estimateMinutes, cal);
    final ok = await runGuarded(
      context,
      () => ref.read(liveSessionProvider.notifier).start(StartSessionRequest(taskText: t.title, demand: Demand.moderate, plannedMinutes: minutes)),
    );
    if (!ok || !mounted) return;
    ref.read(activeTaskIdProvider.notifier).set(t.id);
    context.go(Routes.home);
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final tasks = ref.watch(tasksProvider);
    final live = ref.watch(liveSessionProvider).value;
    final activeId = ref.watch(activeTaskIdProvider);
    final list = tasks.value ?? const <FlowTask>[];
    final open = list.where((t) => !t.done).toList();
    final today = DateTime.now();
    final doneToday = list.where((t) => t.done && DateUtils.isSameDay(t.doneAt, today)).toList();
    final doneEarlier = list.where((t) => t.done && !DateUtils.isSameDay(t.doneAt, today)).length;
    final cal = Calibration.of(list);
    final openMinutes = open.fold<int>(0, (a, t) => a + t.estimateMinutes);

    final addBar = ColorField(
      tone: FieldTone.planned,
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionLabel('Add a task'),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Semantics(
                  label: 'New task',
                  child: FlowTextField(controller: _title, hint: 'What needs doing?', maxLength: 140, onSubmitted: (_) => _add()),
                ),
              ),
              const SizedBox(width: 12),
              Wrap(
                spacing: 6,
                children: [
                  for (final m in _estimates)
                    Pressable(
                      selected: _estimate == m,
                      semanticLabel: 'Estimate $m minutes',
                      onPressed: () => setState(() => _estimate = m),
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      child: Text('$m'),
                    ),
                ],
              ),
              const SizedBox(width: 12),
              ListenableBuilder(
                listenable: _title,
                builder: (context, _) => Pressable(
                  tone: PressableTone.primary,
                  onPressed: _title.text.trim().isEmpty ? null : _add,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: const Text('Add'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            cal == null
                ? 'A rough guess is fine. Flow compares it with the focus time you actually spend.'
                : 'Starting from a task books ${suggestedFor(_estimate, cal)} min for a $_estimate min guess, at your usual pace.',
            style: FlowType.note(p, size: 12.5),
          ),
        ],
      ),
    );

    final listColumn = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        addBar,
        const SizedBox(height: 18),
        Row(
          children: [
            SectionLabel('Open · ${open.length}'),
            const Spacer(),
            if (openMinutes > 0) Text(flowCaps('${flowDuration(openMinutes)} estimated'), style: FlowType.label(p, size: 9.5, color: p.text3)),
          ],
        ),
        const SizedBox(height: 8),
        if (tasks.isLoading && list.isEmpty)
          const Padding(
            padding: EdgeInsets.all(24),
            child: Center(child: CircularProgressIndicator(strokeWidth: 1.5)),
          )
        else if (open.isEmpty)
          _Empty(anyDone: list.isNotEmpty)
        else
          for (final (i, t) in open.indexed)
            Appear(
              key: ValueKey('a-${t.id}'),
              index: i,
              child: _TaskRow(
                key: ValueKey(t.id),
                task: t,
                running: activeId == t.id && live != null,
                canStart: live == null,
                onDone: (v) => ref.read(tasksProvider.notifier).setDone(t.id, v),
                onEstimate: (m) => ref.read(tasksProvider.notifier).setEstimate(t.id, m),
                onRename: (s) => ref.read(tasksProvider.notifier).rename(t.id, s),
                onStart: () => _start(t, cal),
                onRemove: () => _remove(t),
              ),
            ),
        if (doneToday.isNotEmpty) ...[
          const SizedBox(height: 22),
          Row(
            children: [
              SectionLabel('Done today · ${doneToday.length}'),
              const Spacer(),
              Pressable(
                onPressed: () => setState(() => _showDone = !_showDone),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                child: Text(_showDone ? 'Hide' : 'Show', style: const TextStyle(fontSize: 12)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          AnimatedSize(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            alignment: Alignment.topCenter,
            child: _showDone
                ? Column(
                    children: [
                      for (final t in doneToday)
                        _TaskRow(
                          key: ValueKey(t.id),
                          task: t,
                          running: false,
                          canStart: false,
                          onDone: (v) => ref.read(tasksProvider.notifier).setDone(t.id, v),
                          onEstimate: null,
                          onRename: null,
                          onStart: null,
                          onRemove: () => _remove(t),
                        ),
                    ],
                  )
                : const SizedBox(width: double.infinity),
          ),
        ],
        if (doneEarlier > 0) ...[
          const SizedBox(height: 12),
          Text('$doneEarlier finished earlier', style: FlowType.label(p, size: 9.5, color: p.text3)),
        ],
      ],
    );

    final side = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ColorField(
          tone: FieldTone.past,
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
          child: _PaceCard(cal: cal, tasks: list),
        ),
      ],
    );

    return LayoutBuilder(
      builder: (context, box) {
        final wide = box.maxWidth >= 980;
        return ListView(
          padding: const EdgeInsets.only(bottom: 32, right: 24),
          children: [
            FlowHeader(title: 'Tasks', subtitle: '${open.length} open · ${doneToday.length} done today'),
            const SizedBox(height: 8),
            if (wide)
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 7, child: listColumn),
                  const SizedBox(width: 24),
                  Expanded(flex: 4, child: side),
                ],
              )
            else ...[
              side,
              const SizedBox(height: 18),
              listColumn,
            ],
          ],
        );
      },
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.anyDone});
  final bool anyDone;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: p.hairline),
      ),
      child: Column(
        children: [
          Text(anyDone ? 'Nothing open.' : 'No tasks yet.', style: FlowType.headline(p, size: 20, bold: false)),
          const SizedBox(height: 6),
          Text(
            anyDone
                ? 'Everything on the list is done. Add the next thing when you know it.'
                : 'Add something you want to get done, with a rough time. Start a session from it and Flow learns your pace.',
            textAlign: TextAlign.center,
            style: FlowType.note(p, size: 13),
          ),
        ],
      ),
    );
  }
}

class _TaskRow extends StatefulWidget {
  const _TaskRow({
    super.key,
    required this.task,
    required this.running,
    required this.canStart,
    required this.onDone,
    required this.onEstimate,
    required this.onRename,
    required this.onStart,
    required this.onRemove,
  });
  final FlowTask task;
  final bool running;
  final bool canStart;
  final ValueChanged<bool> onDone;
  final ValueChanged<int>? onEstimate;
  final ValueChanged<String>? onRename;
  final VoidCallback? onStart;
  final VoidCallback onRemove;

  @override
  State<_TaskRow> createState() => _TaskRowState();
}

class _TaskRowState extends State<_TaskRow> with SingleTickerProviderStateMixin {
  bool _hover = false;
  bool _editing = false;
  late final _edit = TextEditingController(text: widget.task.title);

  /// Leaving the list: the strike draws through the title (what happened),
  /// then the row folds away (where it went). 0 = here, 1 = gone.
  late final _out = AnimationController(vsync: this, duration: const Duration(milliseconds: 620));
  late final _strike = CurvedAnimation(
    parent: _out,
    curve: const Interval(0, 0.45, curve: Cubic(0.32, 0.72, 0, 1)),
  );
  late final _fold = CurvedAnimation(
    parent: _out,
    curve: const Interval(0.4, 1, curve: Cubic(0.32, 0.72, 0, 1)),
  );
  bool _leaving = false;

  @override
  void dispose() {
    _out.dispose();
    _edit.dispose();
    super.dispose();
  }

  /// Plays the leave, then reports. Reduced motion reports at once.
  Future<void> _leave(VoidCallback then, {bool strike = true}) async {
    if (_leaving) return;
    if (Motion.reduced(context)) return then();
    setState(() => _leaving = true);
    if (!strike) _out.value = 0.4;
    await _out.forward();
    if (mounted) then();
  }

  void _commit() {
    widget.onRename?.call(_edit.text);
    setState(() => _editing = false);
  }

  int _nextEstimate(int m) {
    final i = _estimates.indexWhere((e) => e > m);
    return i < 0 ? _estimates.first : _estimates[i];
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final t = widget.task;
    final done = t.done;
    final row = MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
        decoration: BoxDecoration(
          color: _hover && !p.line ? p.raised : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: widget.running ? p.accent : (_hover ? p.text3.withValues(alpha: 0.5) : p.hairline.withValues(alpha: p.line ? 1 : 0.7)),
            width: widget.running ? 1.4 : 1,
          ),
        ),
        child: Row(
          children: [
            Semantics(
              checked: done,
              label: done ? 'Mark "${t.title}" as not done' : 'Mark "${t.title}" as done',
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => done ? widget.onDone(false) : _leave(() => widget.onDone(true)),
                child: MouseRegion(
                  cursor: SystemMouseCursors.click,
                  child: Padding(
                    padding: const EdgeInsets.all(4),
                    child: PressedDot(on: done, size: 16),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _editing
                  ? FlowTextField(controller: _edit, maxLength: 140, onSubmitted: (_) => _commit())
                  : GestureDetector(
                      onDoubleTap: widget.onRename == null ? null : () => setState(() => _editing = true),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          AnimatedBuilder(
                            animation: _strike,
                            builder: (context, child) =>
                                CustomPaint(foregroundPainter: _leaving ? _StrikePainter(_strike.value, p.text2, p.ink) : null, child: child),
                            child: Text(
                              t.title,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 14,
                                color: done ? p.text3 : p.text1,
                                decoration: done ? TextDecoration.lineThrough : null,
                                decorationColor: p.text3,
                              ),
                            ),
                          ),
                          if (t.sessions > 0 || widget.running) ...[const SizedBox(height: 6), _EstimateBar(task: t, running: widget.running)],
                        ],
                      ),
                    ),
            ),
            const SizedBox(width: 10),
            if (_editing)
              Pressable(onPressed: _commit, padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5), child: const Text('Save'))
            else ...[
              Pressable(
                onPressed: widget.onEstimate == null ? null : () => widget.onEstimate!(_nextEstimate(t.estimateMinutes)),
                tooltip: widget.onEstimate == null ? null : 'Change the estimate',
                semanticLabel: 'Estimate ${t.estimateMinutes} minutes',
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                child: AnimatedSwitcher(
                  duration: Motion.fade,
                  child: Text(flowDuration(t.estimateMinutes), key: ValueKey(t.estimateMinutes), style: const TextStyle(fontSize: 12)),
                ),
              ),
              if (widget.onStart != null) ...[
                const SizedBox(width: 6),
                Pressable(
                  tone: widget.running ? PressableTone.raised : PressableTone.primary,
                  onPressed: widget.canStart ? widget.onStart : null,
                  tooltip: widget.running ? 'Running now' : (widget.canStart ? null : 'A session is already running'),
                  semanticLabel: 'Start a session on ${t.title}',
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  child: Text(widget.running ? 'Running' : 'Start', style: const TextStyle(fontSize: 12)),
                ),
              ],
              const SizedBox(width: 2),
              const SizedBox(width: 4),
              AnimatedOpacity(
                duration: Motion.fade,
                opacity: _hover ? 1 : 0.4,
                child: Pressable(
                  onPressed: () => _leave(widget.onRemove, strike: false),
                  tooltip: 'Remove',
                  semanticLabel: 'Remove ${t.title}',
                  padding: const EdgeInsets.all(5),
                  child: Icon(Icons.close, size: 14, color: p.text2),
                ),
              ),
            ],
          ],
        ),
      ),
    );
    if (!_leaving) return row;
    return AnimatedBuilder(
      animation: _fold,
      builder: (context, child) => Opacity(
        opacity: 1 - _fold.value,
        child: Align(alignment: Alignment.topCenter, heightFactor: 1 - _fold.value, child: child),
      ),
      child: IgnorePointer(child: row),
    );
  }
}

/// The strike through a finished title, drawn left to right.
class _StrikePainter extends CustomPainter {
  _StrikePainter(this.t, this.color, this.width);
  final double t;
  final Color color;
  final double width;
  @override
  void paint(Canvas c, Size s) {
    if (t <= 0) return;
    final y = 10.5; // the first line's middle at 14 px
    c.drawLine(
      Offset(0, y),
      Offset(math.min(s.width, s.width * t), y),
      Paint()
        ..color = color
        ..strokeWidth = width * 1.1
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(_StrikePainter o) => o.t != t || o.color != color;
}

/// Estimate vs logged focus time, as a ruler: the estimate is the track,
/// focus so far is the ink line; past the estimate it runs on in amber.
class _EstimateBar extends StatelessWidget {
  const _EstimateBar({required this.task, required this.running});
  final FlowTask task;
  final bool running;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final a = task.actualMinutes, e = task.estimateMinutes;
    return Row(
      children: [
        SizedBox(width: 140, height: 8, child: CustomPaint(painter: _BarPainter(p, a / e))),
        const SizedBox(width: 8),
        Text(
          running && a == 0 ? 'in progress' : '${flowDuration(a)} of ${flowDuration(e)}${task.sessions > 1 ? ' · ${task.sessions} sessions' : ''}',
          style: FlowType.chart(p, size: 10, color: a > e ? p.amber : p.text3),
        ),
      ],
    );
  }
}

class _BarPainter extends CustomPainter {
  _BarPainter(this.p, this.f);
  final FlowPalette p;
  final double f;

  @override
  void paint(Canvas c, Size s) {
    final y = s.height / 2;
    // the estimate fills 80% of the width, so an overrun has room to show
    final est = s.width * 0.8;
    c.drawLine(
      Offset(0, y),
      Offset(est, y),
      Paint()
        ..color = p.hairline
        ..strokeWidth = 1,
    );
    c.drawLine(
      Offset(est, 1),
      Offset(est, s.height - 1),
      Paint()
        ..color = p.text3
        ..strokeWidth = 1,
    );
    final within = est * math.min(1.0, f);
    c.drawLine(
      Offset(0, y),
      Offset(within, y),
      Paint()
        ..color = p.text1
        ..strokeWidth = 2.2
        ..strokeCap = StrokeCap.round,
    );
    if (f > 1) {
      c.drawLine(
        Offset(est, y),
        Offset(math.min(s.width, est * f), y),
        Paint()
          ..color = p.amber
          ..strokeWidth = 2.2
          ..strokeCap = StrokeCap.round,
      );
    }
  }

  @override
  bool shouldRepaint(_BarPainter o) => o.f != f || o.p != p;
}

/// Your pace: how long tasks really take against your guesses, on a ruler
/// from ½× to 2× with "as estimated" in the middle. A reading, not a grade.
class _PaceCard extends StatelessWidget {
  const _PaceCard({required this.cal, required this.tasks});
  final Calibration? cal;
  final List<FlowTask> tasks;

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final timed = tasks.where((t) => t.done && t.sessions > 0).length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionLabel('Your pace'),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            TabularNumeral(cal == null ? '—' : '${cal!.ratio.toStringAsFixed(1)}×', style: FlowType.numeral(p, 34)),
            const SizedBox(width: 10),
            Flexible(
              child: Text(flowCaps('of your estimate'), style: FlowType.label(p, size: 9.5, color: p.text3)),
            ),
          ],
        ),
        const SizedBox(height: 14),
        SizedBox(
          height: 34,
          width: double.infinity,
          child: CustomPaint(painter: _PacePainter(p, cal?.ratio)),
        ),
        const SizedBox(height: 12),
        Text(
          cal == null
              ? 'Finish ${3 - timed.clamp(0, 3)} more task${3 - timed.clamp(0, 3) == 1 ? '' : 's'} you started a session from, and Flow will show how your estimates compare.'
              : '${cal!.words}, from ${cal!.count} finished tasks. Sessions started from a task are sized to match.',
          style: FlowType.note(p, size: 13),
        ),
      ],
    );
  }
}

class _PacePainter extends CustomPainter {
  _PacePainter(this.p, this.ratio);
  final FlowPalette p;
  final double? ratio;

  // log scale: ½× … 1× … 2×, so faster and slower are the same distance
  double _x(double r, double w) => (math.log(r.clamp(0.5, 2.0)) / math.ln2 + 1) / 2 * w;

  @override
  void paint(Canvas c, Size s) {
    final base = s.height - 12;
    final tick = Paint()
      ..color = p.text3
      ..strokeWidth = 1;
    c.drawLine(Offset(0, base), Offset(s.width, base), tick..color = p.hairline);
    for (var i = 0; i <= 20; i++) {
      final r = math.pow(2, -1 + i / 10).toDouble();
      final x = _x(r, s.width);
      final major = i % 10 == 0;
      c.drawLine(Offset(x, base), Offset(x, base - (major ? 10 : 5)), tick..color = major ? p.text2 : p.text3.withValues(alpha: 0.6));
    }
    for (final (r, label) in const [(0.5, '½×'), (1.0, 'as estimated'), (2.0, '2×')]) {
      final tp = TextPainter(
        text: TextSpan(text: label, style: FlowType.chart(p, size: 9)),
        textDirection: TextDirection.ltr,
      )..layout();
      final x = _x(r, s.width);
      tp.paint(c, Offset((x - tp.width / 2).clamp(0.0, s.width - tp.width), base + 2));
    }
    if (ratio != null) {
      final x = _x(ratio!, s.width);
      c.drawLine(
        Offset(x, base - 18),
        Offset(x, base),
        Paint()
          ..color = p.accent
          ..strokeWidth = 1.6,
      );
      c.drawCircle(Offset(x, base - 20), 4, Paint()..color = p.accent);
    }
  }

  @override
  bool shouldRepaint(_PacePainter o) => o.ratio != ratio || o.p != p;
}
