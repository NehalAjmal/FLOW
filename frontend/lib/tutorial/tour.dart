import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../ui/pressable.dart';
import 'coach.dart';

/// Whether the in-app tour is on screen. It is queued once, when the first
/// welcome guide (after sign-up) hands over to Home; Settings › Help can
/// replay it. Signing in to an existing account never shows it.
final tourProvider = NotifierProvider<TourController, bool>(TourController.new);

class TourController extends Notifier<bool> {
  static const key = 'flow.tour.v1';

  @override
  bool build() => false;

  /// Shows the tour unless this computer has already finished it.
  Future<void> queueIfNew() async {
    try {
      final sp = await SharedPreferences.getInstance();
      if (!(sp.getBool(key) ?? false)) state = true;
    } catch (_) {}
  }

  Future<void> finish() async {
    state = false;
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setBool(key, true);
    } catch (_) {}
  }

  void replay() => state = true;
}

/// The tour over Home: one part lit at a time with what it is and what it
/// does. Look-only (the lit part doesn't take input); Next and Skip.
class TourOverlay extends ConsumerStatefulWidget {
  const TourOverlay({super.key});
  @override
  ConsumerState<TourOverlay> createState() => _TourOverlayState();
}

class _TourOverlayState extends ConsumerState<TourOverlay> {
  int _i = 0;
  final _box = GlobalKey();
  Rect? _seen;
  int _still = 0;

  static const _steps = [
    (
      'day',
      'Your day',
      'Each block is a stretch of focus; its height is how demanding it was. The curve below is pressure, and the dashed line is where Flow suggests a break.',
    ),
    ('lookback', 'Look back', 'One pillar per day. Roll the wheel to move through weeks; press a pillar to open that day above.'),
    ('deck', 'Start a block', 'Turn the dial or pick 25, 50 or 90. Next up offers your open tasks, sized to your own pace.'),
    ('rail', 'Everything else', 'Insights, Tasks and Settings live here. Ctrl+2, Ctrl+3 and Ctrl+, jump straight to them; Ctrl+1 comes home.'),
  ];

  @override
  Widget build(BuildContext context) {
    if (!ref.watch(tourProvider)) return const SizedBox.shrink();
    // never inside the sign-up sandbox, which has its own coach
    if (CoachScope.of(context) != CoachRegistry.root) return const SizedBox.shrink();
    MediaQuery.sizeOf(context); // a resized window re-measures
    final (mark, title, body) = _steps[_i];
    final last = _i == _steps.length - 1;
    final me = _box.currentContext?.findRenderObject();
    final hole = me is RenderBox && me.hasSize ? CoachRegistry.root.rectOf(mark, me) : null;
    // re-measure on the next frames while the page settles (appear motion,
    // data arriving), then stop: no frame loop once the mark holds still
    _still = hole == _seen ? _still + 1 : 0;
    _seen = hole;
    if (_still < 3) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) setState(() {});
      });
    }
    return Positioned.fill(
      key: _box,
      child: hole == null
          ? const SizedBox.shrink()
          : CoachLight(
              hole: hole,
              passThrough: false,
              title: title,
              body: body,
              actions: [
                Pressable(
                  tone: PressableTone.primary,
                  onPressed: () => last ? ref.read(tourProvider.notifier).finish() : setState(() => (_i++, _still = 0)),
                  child: Text(last ? 'Done' : 'Next  ${_i + 1}/${_steps.length}'),
                ),
                if (!last) CoachQuiet('Skip the tour', () => ref.read(tourProvider.notifier).finish()),
              ],
            ),
    );
  }
}
