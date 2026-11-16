import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:material_ui/material_ui.dart';

import '../theme/motion.dart';
import '../theme/tokens.dart';

/// Light ⇄ dark as something that *spreads*: the new theme takes the page
/// over like ink soaking through paper.
///
/// How it works: when the brightness is about to change, the page as it looks
/// now is captured as one image. The app underneath switches at once; the
/// image is laid over it and eaten away from an origin outward. So every
/// element — text, blocks, charts, a half-open menu — changes at the exact
/// moment the front crosses it, pixel by pixel, with no element-by-element
/// bookkeeping.
///
/// What the front is made of (all deterministic per transition, from a seed):
///  - **the body**: a closed curve around the origin whose radius wobbles with
///    angle (three slow waves that drift as it grows), so it is never a circle;
///  - **tendrils**: a handful of directions in which it runs ahead, strongest
///    in the middle of the spread and absorbed by the end;
///  - **spores**: dozens of small colonies scattered over the page. Each
///    breaks out shortly *before* the front reaches it, swells with a little
///    overshoot, buds two or three satellites, and is swallowed;
///  - **the rim**: a thin accent line on the live edge (the accent means
///    "now"), with a soft halo, fading as the spread completes.
///
/// It starts where the pointer last went down (the control that asked for
/// the change) or, when Flow changes by itself, at the logo's o.
/// Reduced motion: a 150 ms cross-fade.
class ThemeSpread extends StatefulWidget {
  const ThemeSpread({super.key, required this.brightness, required this.child});

  /// The brightness the app should be showing.
  final Brightness brightness;

  /// Builds the app for the brightness currently *applied* (which lags
  /// [brightness] by the instant it takes to capture the old page).
  final Widget Function(BuildContext context, Brightness applied, Widget Function(Widget app) wrap) child;

  /// How long the spread takes.
  static const duration = Duration(milliseconds: 1250);

  @override
  State<ThemeSpread> createState() => ThemeSpreadState();
}

class ThemeSpreadState extends State<ThemeSpread> with SingleTickerProviderStateMixin {
  final _boundary = GlobalKey();
  late final _c = AnimationController(vsync: this, duration: ThemeSpread.duration);
  late Brightness _applied = widget.brightness;
  ui.Image? _old;
  Offset _origin = const Offset(40, 40);
  Offset? _lastDown;
  DateTime _lastDownAt = DateTime.fromMillisecondsSinceEpoch(0);
  int _seed = 1;
  bool _fadeOnly = false;

  /// True while a spread is on screen (for tests).
  bool get spreading => _old != null;

  @override
  void initState() {
    super.initState();
    _c.addStatusListener((s) {
      if (s == AnimationStatus.completed) _clear();
    });
  }

  @override
  void didUpdateWidget(ThemeSpread oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.brightness != _applied) _begin(widget.brightness);
  }

  void _clear() {
    if (_old == null) return;
    final img = _old;
    setState(() => _old = null);
    img?.dispose();
  }

  void _begin(Brightness target) {
    ui.Image? snap;
    // Nothing to spread over before the app is visible (the launch screen is
    // still up), or if the page has not been painted yet.
    final ro = _boundary.currentContext?.findRenderObject();
    // (toImageSync reads the layer from the last painted frame: the old theme.)
    if (LaunchGate.revealed.value && ro is RenderRepaintBoundary && ro.hasSize) {
      try {
        snap = ro.toImageSync(pixelRatio: View.of(context).devicePixelRatio);
      } catch (_) {
        snap = null; // no snapshot: the theme simply changes
      }
    }
    final size = ro is RenderBox && ro.hasSize ? ro.size : Size.zero;
    final recent = DateTime.now().difference(_lastDownAt) < const Duration(milliseconds: 1500);
    _old?.dispose();
    _old = snap;
    _applied = target;
    _fadeOnly = Motion.reduced(context);
    // from the control that asked for it, else from the logo's o (top left)
    _origin = recent && _lastDown != null ? _lastDown! : Offset(math.min(40, size.width / 2), math.min(40, size.height / 2));
    _seed = DateTime.now().microsecondsSinceEpoch & 0xFFFF;
    if (snap != null) {
      _c.duration = _fadeOnly ? Motion.fade : ThemeSpread.duration;
      _c.forward(from: 0);
    }
    // didUpdateWidget runs during build: this state is picked up by the same build
  }

  @override
  void dispose() {
    _c.dispose();
    _old?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child(context, _applied, (app) {
    final accent = (_applied == Brightness.dark ? FlowPalette.dark : FlowPalette.light).accent;
    return Listener(
      // remember where the change was asked for
      onPointerDown: (e) {
        _lastDown = e.position;
        _lastDownAt = DateTime.now();
      },
      behavior: HitTestBehavior.translucent,
      child: Stack(
        fit: StackFit.passthrough,
        children: [
          RepaintBoundary(key: _boundary, child: app),
          if (_old != null)
            Positioned.fill(
              child: IgnorePointer(
                child: RepaintBoundary(
                  child: CustomPaint(
                    painter: SpreadPainter(image: _old!, t: _c, origin: _origin, seed: _seed, rim: accent, fadeOnly: _fadeOnly),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  });
}

/// One small colony ahead of the front.
class _Spore {
  _Spore(this.at, this.lead, this.size, this.buds);
  final Offset at;

  /// How far ahead of the front (px) it breaks out.
  final double lead;
  final double size;
  final List<(Offset, double)> buds;
}

/// Paints the old page with the infected region eaten out of it.
class SpreadPainter extends CustomPainter {
  SpreadPainter({required this.image, required this.t, required this.origin, required this.seed, required this.rim, this.fadeOnly = false})
    : super(repaint: t);

  final ui.Image image;
  final Animation<double> t;
  final Offset origin;
  final int seed;
  final Color rim;
  final bool fadeOnly;

  static const _angles = 220;
  List<_Spore>? _spores;
  Size? _sporesFor;
  late final math.Random _r = math.Random(seed);
  late final List<double> _phase = [for (var i = 0; i < 6; i++) _r.nextDouble() * math.pi * 2];
  late final List<(double, double, double)> _tendrils = [
    // (angle, width in radians, reach)
    for (var i = 0; i < 9; i++) (_r.nextDouble() * math.pi * 2, 0.05 + _r.nextDouble() * 0.09, 0.10 + _r.nextDouble() * 0.16),
  ];

  /// The farthest corner from the origin: the spread must pass it.
  static double reach(Size s, Offset o) => [
    o.distance,
    (o - Offset(s.width, 0)).distance,
    (o - Offset(0, s.height)).distance,
    (o - Offset(s.width, s.height)).distance,
  ].reduce(math.max);

  /// Front radius in direction [a] at progress [p] (0..1), for a page whose
  /// farthest corner is [far] away. Public so the shape can be tested.
  double radius(double a, double p, double far) {
    // the body grows a little past the far corner so the wobble never leaves a sliver
    final grow = Curves.easeInOutCubic.transform(p);
    final base = far * 1.22 * grow;
    final wobble =
        0.085 * math.sin(3 * a + _phase[0] + p * 2.2) +
        0.055 * math.sin(7 * a + _phase[1] - p * 3.1) +
        0.03 * math.sin(13 * a + _phase[2] + p * 4.0) +
        0.015 * math.sin(29 * a + _phase[3]);
    // tendrils run ahead mid-spread and are absorbed by the end
    final env = math.sin(math.pi * p.clamp(0.0, 1.0));
    var run = 0.0;
    for (final (ta, tw, tr) in _tendrils) {
      var d = (a - ta).abs() % (math.pi * 2);
      if (d > math.pi) d = math.pi * 2 - d;
      run += tr * math.exp(-(d * d) / (2 * tw * tw));
    }
    return base * (1 + wobble * (0.4 + 0.6 * env) + run * env);
  }

  List<_Spore> _sporesOn(Size s) {
    if (_spores != null && _sporesFor == s) return _spores!;
    final r = math.Random(seed ^ 0x5eed);
    // density follows the page's area, within sane bounds
    final n = (s.width * s.height / 26000).round().clamp(18, 70);
    _sporesFor = s;
    return _spores = [
      for (var i = 0; i < n; i++)
        () {
          final at = Offset(r.nextDouble() * s.width, r.nextDouble() * s.height);
          final size = 10 + r.nextDouble() * r.nextDouble() * 54;
          return _Spore(at, 30 + r.nextDouble() * 150, size, [
            for (var k = 0; k < 2 + r.nextInt(3); k++)
              () {
                final ang = r.nextDouble() * math.pi * 2;
                return (Offset(math.cos(ang), math.sin(ang)) * (size * (0.9 + r.nextDouble() * 0.9)), 2.5 + r.nextDouble() * size * 0.22);
              }(),
          ]);
        }(),
    ];
  }

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final src = Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble());
    final p = t.value;
    if (fadeOnly) {
      canvas.drawImageRect(image, src, rect, Paint()..color = Color.fromRGBO(0, 0, 0, 1 - p));
      return;
    }
    final far = reach(size, origin);

    // the body of the spread
    final body = Path();
    for (var i = 0; i <= _angles; i++) {
      final a = i / _angles * math.pi * 2;
      final pt = origin + Offset(math.cos(a), math.sin(a)) * radius(a, p, far);
      i == 0 ? body.moveTo(pt.dx, pt.dy) : body.lineTo(pt.dx, pt.dy);
    }
    body.close();

    // spores: break out just ahead of the front, swell, bud, get swallowed
    final live = Path();
    for (final sp in _sporesOn(size)) {
      final d = sp.at - origin;
      final dist = d.distance;
      final front = radius(math.atan2(d.dy, d.dx), p, far);
      final ahead = dist - front; // > 0: the front has not reached it
      if (ahead > sp.lead || ahead < -sp.size * 2) continue; // not yet, or long swallowed
      final k = ((sp.lead - ahead) / sp.lead).clamp(0.0, 1.6);
      final swell = Curves.easeOutBack.transform(k.clamp(0.0, 1.0)) + (k > 1 ? (k - 1) * 0.9 : 0);
      live.addOval(Rect.fromCircle(center: sp.at, radius: sp.size * swell));
      for (final (off, r) in sp.buds) {
        final bk = ((k - 0.35) / 0.65).clamp(0.0, 1.0);
        if (bk > 0) live.addOval(Rect.fromCircle(center: sp.at + off * (0.7 + 0.3 * bk), radius: r * Curves.easeOutBack.transform(bk)));
      }
    }

    // the old page, with everything infected eaten out of it
    canvas.saveLayer(rect, Paint());
    canvas.drawImageRect(image, src, rect, Paint()..filterQuality = FilterQuality.medium);
    final eat = Paint()..blendMode = BlendMode.clear;
    canvas.drawPath(body, eat);
    canvas.drawPath(live, eat);
    canvas.restore();

    // the rim: the live edge, in the accent (= now). Fades as the spread ends.
    final alive = (1 - Curves.easeIn.transform(((p - 0.72) / 0.28).clamp(0.0, 1.0))) * (p < 0.04 ? p / 0.04 : 1);
    if (alive > 0) {
      final halo = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 7
        ..color = rim.withValues(alpha: 0.13 * alive)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5);
      final line = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6
        ..strokeJoin = StrokeJoin.round
        ..color = rim.withValues(alpha: 0.85 * alive);
      canvas.save();
      canvas.clipRect(rect);
      canvas.drawPath(body, halo);
      canvas.drawPath(body, line);
      // spores get the thin line only where they are still outside the body
      canvas.drawPath(Path.combine(PathOperation.difference, live, body), line..strokeWidth = 1.1);
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(SpreadPainter o) => o.image != image || o.origin != origin || o.seed != seed || o.rim != rim;
}
