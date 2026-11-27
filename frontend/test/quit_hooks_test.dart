import 'package:flow/desktop/quit_hooks.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('quit hooks all run, and a stuck or failing one cannot hold up quitting', () async {
    var ran = 0;
    Future<void> ok() async => ran++;
    Future<void> stuck() => Future<void>.delayed(const Duration(minutes: 1));
    Future<void> bad() async => throw StateError('agent gone');
    addQuitHook(ok);
    addQuitHook(stuck);
    addQuitHook(bad);
    final sw = Stopwatch()..start();
    await runQuitHooks(limit: const Duration(milliseconds: 200));
    expect(ran, 1);
    expect(sw.elapsed, lessThan(const Duration(seconds: 2)));
    removeQuitHook(ok);
    removeQuitHook(stuck);
    removeQuitHook(bad);
  });
  testWidgets('quitting runs every provider\'s own teardown', (tester) async {
    var disposed = false;
    final agent = Provider<int>((ref) {
      ref.onDispose(() => disposed = true);
      return 1;
    });
    final c = ProviderContainer();
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: c,
        child: Consumer(builder: (_, ref, _) => Text('${ref.watch(agent)}', textDirection: TextDirection.ltr)),
      ),
    );
    final hook = teardownOnQuit(c);
    addQuitHook(hook);
    final done = runQuitHooks(limit: const Duration(seconds: 1));
    await tester.pump();
    await tester.runAsync(() => done);
    removeQuitHook(hook);
    expect(disposed, isTrue);
    expect(find.text('1'), findsNothing);
  });
}
