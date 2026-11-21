import 'package:flow/api/mock/mock_backend.dart';
import 'package:flow/app.dart';
import 'package:flow/router/app_router.dart';
import 'package:flow/router/routes.dart';
import 'package:flow/state/auth_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'helpers.dart';

/// go_router builds Material pages only when it finds *its* MaterialApp (the
/// one from package:material_ui) above it. While the app imported the old
/// package:flutter/material.dart, it found none and fell back to its own
/// plain page, so Flow's page transition was never used.
void main() {
  testWidgets("pages use Flow's own transition (go_router sees the app's MaterialApp)", (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final c = mockContainer(MockBackend(config: const MockConfig(latency: Duration.zero, tick: Duration(hours: 1))));
    await tester.pumpWidget(UncontrolledProviderScope(container: c, child: const FlowApp()));
    await tester.pump(const Duration(seconds: 4));
    await tester.runAsync(() => c.read(authProvider.notifier).login(email: 'solo@flow.dev', password: 'password'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 200));
    }
    c.read(appRouterProvider).go(Routes.settings);
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    final route = ModalRoute.of(tester.element(find.text('Changes save as you make them'.toUpperCase())));
    expect(route?.settings, isA<MaterialPage<void>>(), reason: 'a Material page, so the theme decides its transition (it was NoTransitionPage)');
    expect((route! as TransitionRoute<void>).transitionDuration, const Duration(milliseconds: 180), reason: "Flow's 180 ms fade + rise");
    await tester.pumpWidget(const SizedBox());
    c.dispose();
    await tester.pump(const Duration(seconds: 1));
  });
}
