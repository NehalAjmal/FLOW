import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Work that must finish before Flow quits, such as telling the local sensor
/// agent to stop. Quit ends the process outright (see NativeDesktopHost.quit),
/// so provider disposal does not run: anything that must happen on the way
/// out registers here. Each hook is bounded; a slow one never blocks quitting.
final _hooks = <Future<void> Function()>{};

void addQuitHook(Future<void> Function() hook) => _hooks.add(hook);

void removeQuitHook(Future<void> Function() hook) => _hooks.remove(hook);

/// Runs every hook at once and waits at most [limit] for all of them.
Future<void> runQuitHooks({Duration limit = const Duration(seconds: 1)}) async {
  final runs = [for (final h in _hooks.toList()) Future<void>.sync(h).catchError((Object _) {})];
  await Future.wait(runs).timeout(limit, onTimeout: () => const []);
}

/// The app's normal teardown, as a quit hook: unmount the app, then dispose
/// every provider, so each ref.onDispose (closing streams, disconnecting the
/// local sensor agent) runs before the process ends.
Future<void> Function() teardownOnQuit(ProviderContainer container) => () async {
  runApp(const SizedBox.shrink());
  await SchedulerBinding.instance.endOfFrame.timeout(const Duration(milliseconds: 300), onTimeout: () {});
  container.dispose();
};
