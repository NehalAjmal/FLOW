// Taps every control on every screen, each on a fresh app, and reports
// controls that throw or that change nothing on screen.
// Run: flutter test test/tap_everything_test.dart --dart-define=TAP_REPORT=1
import 'dart:io';

import 'package:flow/api/mock/mock_backend.dart';
import 'package:flow/api/models/session.dart';
import 'package:flow/app.dart';
import 'package:flow/router/app_router.dart';
import 'package:flow/router/routes.dart';
import 'package:flow/state/auth_controller.dart';
import 'package:flow/state/session_controller.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

typedef Setup = Future<void> Function(WidgetTester t, ProviderContainer c);

class Screen {
  const Screen(this.who, this.route, {this.session = false});
  final String? who;
  final String route;
  final bool session;
  String get name => '${who ?? 'signed-out'} $route';
}

const only = String.fromEnvironment('TAP_ONLY');
const screens = [
  Screen(null, Routes.welcome),
  Screen(null, Routes.login),
  Screen(null, Routes.register),
  Screen(null, Routes.forgotPassword),
  Screen('solo@flow.dev', Routes.home),
  Screen('solo@flow.dev', Routes.history),
  Screen('solo@flow.dev', Routes.patterns),
  Screen('solo@flow.dev', Routes.settings),
  Screen('solo@flow.dev', Routes.privacy),
  Screen('solo@flow.dev', Routes.feedback),
  Screen('solo@flow.dev', Routes.tasks),
  Screen('solo@flow.dev', Routes.export),
  Screen('solo@flow.dev', Routes.sessionActive, session: true),
  Screen('solo@flow.dev', Routes.sessionBreak, session: true),
  Screen('solo@flow.dev', '/session/end/s-demo'),
  Screen('employee@flow.dev', Routes.team),
  Screen('admin@flow.dev', Routes.admin),
  Screen('admin@flow.dev', Routes.adminPeople),
  Screen('admin@flow.dev', '/admin/people/m_ben'),
  Screen('new@flow.dev', Routes.guide),
];

final report = StringBuffer();

SemanticsOwner semantics() => RendererBinding.instance.renderViews.first.owner!.semanticsOwner!;

Future<ProviderContainer> open(WidgetTester t, Screen s) async {
  final b = MockBackend(config: const MockConfig(latency: Duration.zero, tick: Duration(hours: 1)));
  final c = mockContainer(b);
  await t.pumpWidget(UncontrolledProviderScope(container: c, child: const FlowApp()));
  await t.pump(const Duration(seconds: 4));
  if (s.who != null) {
    await t.runAsync(() => c.read(authProvider.notifier).login(email: s.who!, password: 'password'));
    if (c.read(authProvider) is MfaRequired) {
      await t.runAsync(() => c.read(authProvider.notifier).verifyMfa(MockBackend.mfaCode));
    }
    for (var i = 0; i < 10; i++) {
      await t.pump(const Duration(milliseconds: 200));
    }
  }
  if (s.session) {
    await t.runAsync(() => c.read(liveSessionProvider.notifier).start(const StartSessionRequest(demand: Demand.moderate, plannedMinutes: 50, taskText: 'Draft')));
    await t.pump(const Duration(milliseconds: 300));
  }
  c.read(appRouterProvider).go(s.route);
  for (var i = 0; i < 16; i++) {
    await t.pump(const Duration(milliseconds: 150));
  }
  return c;
}

Future<void> close(WidgetTester t, ProviderContainer c) async {
  await t.pumpWidget(const SizedBox());
  c.dispose();
  await t.pump(const Duration(seconds: 1));
}

List<SemanticsNode> tappables(WidgetTester t) {
  final out = <SemanticsNode>[];
  void walk(SemanticsNode n) {
    final d = n.getSemanticsData();
    if (d.hasAction(SemanticsAction.tap) && !d.flagsCollection.isHidden) out.add(n);
    n.visitChildren((c) {
      walk(c);
      return true;
    });
  }
  walk(semantics().rootSemanticsNode!);
  return out;
}

String label(SemanticsNode n) {
  final d = n.getSemanticsData();
  String l = [d.label, d.value, d.tooltip].where((e) => e.isNotEmpty).join(' / ');
  if (l.isEmpty) {
    final parts = <String>[];
    n.visitChildren((c) {
      final cd = c.getSemanticsData();
      if (cd.label.isNotEmpty) parts.add(cd.label);
      return true;
    });
    l = parts.join(' ');
  }
  return l.replaceAll('\n', ' ').trim();
}

String fingerprint(WidgetTester t, ProviderContainer c) {
  final b = StringBuffer(c.read(appRouterProvider).routeInformationProvider.value.uri.toString());
  void walk(SemanticsNode n) {
    final d = n.getSemanticsData();
    b.write('|${d.label}:${d.value}:${d.flagsCollection.isChecked}:${d.flagsCollection.isSelected}:${d.flagsCollection.isToggled}');
    n.visitChildren((x) {
      walk(x);
      return true;
    });
  }
  walk(semantics().rootSemanticsNode!);
  return b.toString();
}

void main() {
  tearDownAll(() => File('build/tap_report.txt')
    ..createSync(recursive: true)
    ..writeAsStringSync(report.toString()));

  for (final s in screens.where((s) => only.isEmpty || s.name.contains(only))) {
    testWidgets('tap everything: ${s.name}', (t) async {
      t.view.physicalSize = const Size(1440, 900);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      final h = t.ensureSemantics();
      var c = await open(t, s);
      final count = tappables(t).length;
      final loadErr = t.takeException();
      if (loadErr != null) report.writeln('${s.name} LOAD-ERROR $loadErr');
      report.writeln('== ${s.name}: $count controls');
      await close(t, c);
      for (var i = 0; i < count; i++) {
        c = await open(t, s);
        t.takeException();
        final nodes = tappables(t);
        if (i >= nodes.length) {
          await close(t, c);
          break;
        }
        final n = nodes[i];
        final name = label(n);
        final before = fingerprint(t, c);
        Object? err;
        try {
          semantics().performAction(n.id, SemanticsAction.tap);
          for (var k = 0; k < 10; k++) {
            await t.pump(const Duration(milliseconds: 150));
          }
          err = t.takeException();
        } catch (e) {
          err = e;
        }
        final after = fingerprint(t, c);
        final where = c.read(appRouterProvider).routeInformationProvider.value.uri.toString();
        if (err != null) {
          report.writeln('  ERROR  [$i] "$name": ${err.toString().split('\n').first}');
        } else if (before == after) {
          report.writeln('  NOOP   [$i] "$name"');
        } else {
          report.writeln('  ok     [$i] "$name" -> $where');
        }
        await close(t, c);
        t.takeException();
      }
      h.dispose();
    }, timeout: const Timeout(Duration(minutes: 20)));
  }
}
