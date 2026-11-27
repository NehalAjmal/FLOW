import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../state/session_controller.dart';
import '../core/session_clock.dart';

/// A to-do item with a time estimate. Sessions started from a task log their
/// focus minutes against it, so Flow can show how your estimates compare
/// with what actually happens ("calibrated to you", never graded).
class FlowTask {
  const FlowTask({
    required this.id,
    required this.title,
    required this.estimateMinutes,
    required this.createdAt,
    this.actualMinutes = 0,
    this.sessions = 0,
    this.doneAt,
    this.updatedAt,
  });

  final String id;
  final String title;
  final int estimateMinutes;
  final int actualMinutes;
  final int sessions;
  final DateTime createdAt;
  final DateTime? doneAt;

  /// Last local change; a future sync resolves conflicts by this.
  final DateTime? updatedAt;

  bool get done => doneAt != null;

  FlowTask copyWith({String? title, int? estimateMinutes, int? actualMinutes, int? sessions, DateTime? doneAt, bool clearDone = false}) => FlowTask(
    id: id,
    title: title ?? this.title,
    estimateMinutes: estimateMinutes ?? this.estimateMinutes,
    actualMinutes: actualMinutes ?? this.actualMinutes,
    sessions: sessions ?? this.sessions,
    createdAt: createdAt,
    doneAt: clearDone ? null : (doneAt ?? this.doneAt),
    updatedAt: DateTime.now(),
  );

  Map<String, Object?> toJson() => {
    'id': id,
    'title': title,
    'estimate_minutes': estimateMinutes,
    'actual_minutes': actualMinutes,
    'sessions': sessions,
    'created_at': createdAt.toIso8601String(),
    if (doneAt != null) 'done_at': doneAt!.toIso8601String(),
    if (updatedAt != null) 'updated_at': updatedAt!.toIso8601String(),
  };

  static FlowTask? fromJson(Object? j) {
    if (j is! Map) return null;
    final id = j['id'], title = j['title'];
    if (id is! String || title is! String) return null;
    int n(Object? v, int d) => v is num ? v.toInt() : d;
    DateTime? t(Object? v) => v is String ? DateTime.tryParse(v) : null;
    return FlowTask(
      id: id,
      title: title,
      estimateMinutes: n(j['estimate_minutes'], 30).clamp(5, 480),
      actualMinutes: n(j['actual_minutes'], 0).clamp(0, 100000),
      sessions: n(j['sessions'], 0).clamp(0, 10000),
      createdAt: t(j['created_at']) ?? DateTime.now(),
      doneAt: t(j['done_at']),
      updatedAt: t(j['updated_at']),
    );
  }
}

/// Where tasks are kept. Local for now; a server-backed store can replace
/// this (same interface) once the backend has a tasks API.
abstract class TasksStore {
  Future<List<FlowTask>> load();
  Future<void> save(List<FlowTask> tasks);
}

class MemoryTasksStore implements TasksStore {
  MemoryTasksStore([List<FlowTask>? seed]) : _tasks = [...?seed];
  List<FlowTask> _tasks;
  @override
  Future<List<FlowTask>> load() async => [..._tasks];
  @override
  Future<void> save(List<FlowTask> tasks) async => _tasks = [...tasks];
}

class PrefsTasksStore implements TasksStore {
  static const key = 'flow.tasks.v1';
  final _fallback = MemoryTasksStore();
  bool _usable = true;

  @override
  Future<List<FlowTask>> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(key);
      if (raw == null) return [];
      final list = jsonDecode(raw);
      if (list is! List) return [];
      return [for (final j in list) ?FlowTask.fromJson(j)];
    } catch (_) {
      // no plugin (tests) or corrupt data: keep working in memory
      _usable = false;
      return _fallback.load();
    }
  }

  @override
  Future<void> save(List<FlowTask> tasks) async {
    if (!_usable) return _fallback.save(tasks);
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(key, jsonEncode([for (final t in tasks) t.toJson()]));
    } catch (_) {
      _usable = false;
      await _fallback.save(tasks);
    }
  }
}

final tasksStoreProvider = Provider<TasksStore>((ref) => PrefsTasksStore());

/// The task the running session was started for, if any.
final activeTaskIdProvider = NotifierProvider<_ActiveTask, String?>(_ActiveTask.new);

class _ActiveTask extends Notifier<String?> {
  @override
  String? build() => null;
  void set(String? id) => state = id;
}

final tasksProvider = AsyncNotifierProvider<TasksController, List<FlowTask>>(TasksController.new);

class TasksController extends AsyncNotifier<List<FlowTask>> {
  int _seq = 0;

  @override
  Future<List<FlowTask>> build() async {
    // When a session that was started from a task ends, log its focus time.
    ref.listen(liveSessionProvider, (prev, next) {
      final was = prev?.value?.session;
      final now = next.value?.session;
      if (was != null && now == null) {
        final id = ref.read(activeTaskIdProvider);
        if (id != null) {
          final mins = (was.focusAt(DateTime.now(), ref.read(pausedSinceProvider)).inSeconds / 60).round();
          logSession(id, mins);
          ref.read(activeTaskIdProvider.notifier).set(null);
        }
      }
    });
    return ref.read(tasksStoreProvider).load();
  }

  List<FlowTask> get _list => state.value ?? const [];

  Future<void> _commit(List<FlowTask> next) async {
    state = AsyncData(next);
    await ref.read(tasksStoreProvider).save(next);
  }

  Future<FlowTask?> add(String title, int estimateMinutes) async {
    final t = title.trim();
    if (t.isEmpty) return null;
    final task = FlowTask(
      id: 't${DateTime.now().microsecondsSinceEpoch}-${_seq++}',
      title: t.length > 140 ? t.substring(0, 140) : t,
      estimateMinutes: estimateMinutes.clamp(5, 480),
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );
    await _commit([..._list, task]);
    return task;
  }

  Future<void> _edit(String id, FlowTask Function(FlowTask) f) =>
      _commit([for (final t in _list) t.id == id ? f(t) : t]);

  Future<void> setDone(String id, bool done) =>
      _edit(id, (t) => done ? t.copyWith(doneAt: DateTime.now()) : t.copyWith(clearDone: true));
  Future<void> rename(String id, String title) =>
      title.trim().isEmpty ? Future.value() : _edit(id, (t) => t.copyWith(title: title.trim()));
  Future<void> setEstimate(String id, int minutes) => _edit(id, (t) => t.copyWith(estimateMinutes: minutes.clamp(5, 480)));
  Future<void> logSession(String id, int minutes) =>
      _edit(id, (t) => t.copyWith(actualMinutes: t.actualMinutes + minutes.clamp(0, 600), sessions: t.sessions + 1));

  /// Removes a task; returns it with its index so the caller can offer undo.
  Future<(FlowTask, int)?> remove(String id) async {
    final i = _list.indexWhere((t) => t.id == id);
    if (i < 0) return null;
    final t = _list[i];
    await _commit([..._list]..removeAt(i));
    return (t, i);
  }

  Future<void> restore(FlowTask t, int index) async {
    final l = [..._list];
    l.insert(index.clamp(0, l.length), t);
    await _commit(l);
  }

  Future<void> move(int from, int to) async {
    final open = _list.where((t) => !t.done).toList();
    if (from < 0 || from >= open.length) return;
    final t = open.removeAt(from);
    open.insert(to.clamp(0, open.length), t);
    await _commit([...open, ..._list.where((t) => t.done)]);
  }
}

/// How your estimates compare with the focus time actually logged, from
/// finished tasks that have at least one session. Null until there are 3.
class Calibration {
  const Calibration(this.ratio, this.count);
  final double ratio;
  final int count;

  static Calibration? of(List<FlowTask> tasks) {
    final timed = tasks.where((t) => t.done && t.sessions > 0 && t.actualMinutes > 0).toList();
    if (timed.length < 3) return null;
    final est = timed.fold<int>(0, (a, t) => a + t.estimateMinutes);
    final act = timed.fold<int>(0, (a, t) => a + t.actualMinutes);
    return Calibration(act / est, timed.length);
  }

  /// Plain words: "on your estimates", "1.4× your estimates", "0.8× ...".
  String get words {
    if ((ratio - 1).abs() < 0.1) return 'Your tasks take about what you estimate';
    return 'Your tasks take ${ratio.toStringAsFixed(1)}× your estimate';
  }
}

/// The estimate a task should start with, scaled by your own calibration.
int suggestedFor(int estimate, Calibration? c) {
  if (c == null) return estimate.clamp(15, 180);
  final m = (estimate * c.ratio / 5).round() * 5;
  return m.clamp(15, 180);
}
