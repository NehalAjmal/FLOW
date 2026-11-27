import 'package:flow/api/mock/mock_backend.dart';
import 'package:flow/app.dart';
import 'package:flow/router/app_router.dart';
import 'package:flow/router/routes.dart';
import 'package:flow/state/auth_controller.dart';
import 'package:flow/tutorial/tour.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

Future<ProviderContainer> boot(WidgetTester t, {String? who}) async {
  await t.binding.setSurfaceSize(const Size(1440, 1000));
  final b = MockBackend(config: const MockConfig(latency: Duration.zero, tick: Duration(hours: 1)));
  final c = mockContainer(b);
  await t.pumpWidget(UncontrolledProviderScope(container: c, child: const FlowApp()));
  await t.pump(const Duration(seconds: 4));
  if (who != null) {
    await t.runAsync(() => c.read(authProvider.notifier).login(email: who, password: 'password'));
    for (var i = 0; i < 10; i++) {
      await t.pump(const Duration(milliseconds: 200));
    }
  }
  return c;
}

Future<void> frames(WidgetTester t, [int n = 12]) async {
  for (var i = 0; i < n; i++) {
    await t.pump(const Duration(milliseconds: 150));
  }
}

Future<void> shut(WidgetTester t, ProviderContainer c) async {
  await t.pumpWidget(const SizedBox());
  c.dispose();
  await t.pump(const Duration(seconds: 1));
}

void main() {
  testWidgets('Create an account opens the playable tutorial, and it can be skipped to Register', (t) async {
    final c = await boot(t);
    c.read(appRouterProvider).go(Routes.welcome);
    await frames(t);
    await t.tap(find.text('Create an account').first, warnIfMissed: false);
    await frames(t);
    expect(c.read(appRouterProvider).routeInformationProvider.value.uri.path, Routes.tutorial);
    // the sandbox signs in on its own mock, then lights the dial
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 600)));
    await frames(t, 20);
    expect(find.text('Pick a length'), findsOneWidget);
    await t.tap(find.text('Skip to Create account'));
    await frames(t);
    expect(c.read(appRouterProvider).routeInformationProvider.value.uri.path, Routes.register);
    await shut(t, c);
  });

  testWidgets('the Home tour walks its four parts and does not come back once done', (t) async {
    SharedPreferences.setMockInitialValues({});
    final c = await boot(t, who: 'solo@flow.dev');
    await t.runAsync(() => c.read(tourProvider.notifier).queueIfNew());
    await frames(t);
    expect(find.text('Your day'), findsOneWidget);
    for (final next in ['Look back', 'Start a block', 'Everything else']) {
      await t.tap(find.textContaining(RegExp(r'^Next  ')));
      await frames(t);
      expect(find.text(next), findsOneWidget);
    }
    await t.tap(find.text('Done'));
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await frames(t);
    expect(c.read(tourProvider), isFalse);
    await t.runAsync(() => c.read(tourProvider.notifier).queueIfNew());
    expect(c.read(tourProvider), isFalse);
    await shut(t, c);
  });
}
