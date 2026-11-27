import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/config.dart';
import 'desktop/compact_views.dart';
import 'desktop/window_controller.dart';
import 'dev/dev_panel.dart';
import 'router/app_router.dart';
import 'theme/input_kind.dart';
import 'theme/scrolling.dart';
import 'theme/style.dart';
import 'theme/tokens.dart';
import 'ui/blocks.dart' show LineInk;
import 'ui/brand/launch_overlay.dart';
import 'ui/theme_spread.dart';

class FlowApp extends ConsumerStatefulWidget {
  const FlowApp({super.key});

  @override
  ConsumerState<FlowApp> createState() => _FlowAppState();
}

class _FlowAppState extends ConsumerState<FlowApp> with WidgetsBindingObserver {
  late Brightness _platform = WidgetsBinding.instance.platformDispatcher.platformBrightness;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangePlatformBrightness() {
    final b = WidgetsBinding.instance.platformDispatcher.platformBrightness;
    if (b != _platform) setState(() => _platform = b);
  }

  @override
  Widget build(BuildContext context) {
    // Settings › Appearance, resolved to light or dark here (not left to
    // MaterialApp) so that every change, a system one included, goes through
    // ThemeSpread: it captures the old page first, then switches.
    final wanted = switch (ref.watch(themeModeProvider)) {
      ThemeMode.light => Brightness.light,
      ThemeMode.dark => Brightness.dark,
      ThemeMode.system => _platform,
    };
    final router = ref.watch(appRouterProvider);
    return ThemeSpread(
      brightness: wanted,
      style: ref.watch(flowStyleProvider),
      child: (context, applied, style, wrap) => MaterialApp.router(
        title: 'Flow',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(Brightness.light, line: style == FlowStyle.line),
        darkTheme: buildTheme(Brightness.dark, line: style == FlowStyle.line),
        themeMode: applied == Brightness.dark ? ThemeMode.dark : ThemeMode.light,
        // the spread is the animation: underneath, the theme changes at once
        themeAnimationDuration: Duration.zero,
        routerConfig: router,
        scrollBehavior: const FlowScrollBehavior(),
        // kDevBuild is const: in release this branch and DevShell are compiled out.
        builder: (context, child) {
          // painters that only receive a colour read the applied look from here
          LineInk.use(FlowPalette.of(context));
          // Flow's type runs one step larger than platform defaults; the
          // person's own OS text size still multiplies on top.
          final mq = MediaQuery.of(context);
          final app = MediaQuery(
            data: mq.copyWith(textScaler: FlowTextScaler(mq.textScaler)),
            child: LaunchOverlay(
              child: WindowFrame(child: InputKindListener(child: child ?? const SizedBox())),
            ),
          );
          return wrap(kDevBuild ? DevShell(child: app) : app);
        },
      ),
    );
  }
}
