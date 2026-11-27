import 'dart:math' as math;

import 'package:flutter/painting.dart';

import '../theme/motion.dart';
import '../theme/palette.dart';

/// How a block arrives (rule L in motion, same as the wordmark): a dashed
/// outline first ("not yet"), then it fills bottom → top like liquid
/// ("happened"). The surface ripples in proportion to the fill spring's
/// velocity, so it calms as it settles. Used by every 3D block.
class LiquidFill {
  const LiquidFill(this.level, this.ripple, {this.phase = 0});

  /// 0..1 of the block (top face included).
  final double level;

  /// Ripple amplitude in px.
  final double ripple;
  final double phase;

  static const full = LiquidFill(1, 0);

  /// [t] seconds since this block's fill started (after its stagger).
  /// [outlineLead] seconds of dashed outline before the liquid starts.
  static LiquidFill at(double t, {double response = 0.7, double outlineLead = 0.18, double maxRipple = 3}) {
    if (t >= 1e8) return full;
    final ft = t - outlineLead;
    final level = Motion.settleAt(ft, response: response);
    final v = Motion.settleVelAt(ft, response: response) / Motion.settlePeakVel(response: response);
    return LiquidFill(level, maxRipple * v.clamp(0.0, 1.0), phase: t * 9);
  }

  /// Opacity of the dashed outline: draws in, then fades as the fill completes.
  double outlineAlpha(double t) {
    if (level >= 0.999) return 0;
    final drawIn = (t / 0.18).clamp(0.0, 1.0);
    final fade = level < 0.8 ? 1.0 : (1 - (level - 0.8) / 0.2);
    return drawIn * fade.clamp(0.0, 1.0);
  }
}

/// The Line style, for painters that only get a colour (blocks, pillars).
/// Set once per build from the applied palette (see app.dart); only one look
/// is ever painted live at a time (a transition's old look is a snapshot).
abstract final class LineInk {
  static bool on = false;
  static Color ink = const Color(0xFF1C1E1A);
  static Color plate = const Color(0xFFE8ECE3);
  static double width = 1;

  /// Data marks: ink, or slate blue with the Line colour option.
  static Color data = const Color(0xFF1C1E1A);

  static void use(FlowPalette p) {
    on = p.line;
    ink = p.text1;
    data = p.lineData;
    plate = p.bg;
    width = p.ink;
  }

  /// Meaning colours (verdigris, amber, ultramarine) survive as line colour;
  /// stones (what happened) become plain ink.
  static Color stroke(Color c) {
    final hsl = HSLColor.fromColor(c);
    return hsl.saturation > 0.38 && c.a > 0.5 ? c.withValues(alpha: 1) : data;
  }

  /// Comb spacing in px: dense enough to read as a mass, open enough to stay a line.
  static const comb = 3.5;
}

/// Line style block: the silhouette as a plate (hides what is behind it),
/// a bright outer edge, one dim crease, and a comb of hairlines on the front
/// whose height is the reading (Hairline rule: bright outside, dim inside).
void paintLineBlock(Canvas c, double x0, double x1, double base, double h, double depth, Color col) {
  final top = base - h;
  final d = math.min(depth, math.max(1.5, (x1 - x0) * 0.32));
  final ink = LineInk.stroke(col);
  final sil = Path()
    ..moveTo(x0, base)
    ..lineTo(x0, top)
    ..lineTo(x0 + d, top - d)
    ..lineTo(x1 + d, top - d)
    ..lineTo(x1 + d, base - d)
    ..lineTo(x1, base)
    ..close();
  c.drawPath(sil, Paint()..color = LineInk.plate);
  final pen = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = LineInk.width * 0.9
    ..strokeJoin = StrokeJoin.round
    ..color = ink;
  // comb on the front face
  final comb = Path();
  for (var x = x0 + 1.5; x <= x1 - 1; x += LineInk.comb) {
    comb
      ..moveTo(x, base)
      ..lineTo(x, top);
  }
  c.drawPath(comb, pen..color = ink.withValues(alpha: 0.78));
  c.drawPath(sil, pen..color = ink);
  // the crease where front meets top and side, dim
  c.drawPath(
    Path()
      ..moveTo(x0, top)
      ..lineTo(x1, top)
      ..lineTo(x1, base)
      ..moveTo(x1, top)
      ..lineTo(x1 + d, top - d),
    pen..color = ink.withValues(alpha: 0.45),
  );
}

/// A front-on block with a top and side face (the Score's block language).
void paintSolidBlock(Canvas c, double x0, double x1, double base, double h, double depth, Color col, {bool shade = true}) {
  if (LineInk.on) return paintLineBlock(c, x0, x1, base, h, depth, col);
  final top = base - h;
  final d = math.min(depth, math.max(1.5, (x1 - x0) * 0.32));
  c.drawPath(
    Path()
      ..moveTo(x0, top)
      ..lineTo(x0 + d, top - d)
      ..lineTo(x1 + d, top - d)
      ..lineTo(x1, top)
      ..close(),
    Paint()..color = Faces.top(col),
  );
  c.drawPath(
    Path()
      ..moveTo(x1, top)
      ..lineTo(x1 + d, top - d)
      ..lineTo(x1 + d, base - d)
      ..lineTo(x1, base)
      ..close(),
    Paint()..color = Faces.side(col),
  );
  final front = Rect.fromLTRB(x0, top, x1, base);
  c.drawRect(
    front,
    shade && h > 8
        ? (Paint()
            ..shader = LinearGradient(
              begin: const Alignment(0, -1),
              end: const Alignment(0, 1),
              colors: [Color.lerp(col, Faces.top(col), 0.35)!, col, Color.lerp(col, Faces.side(col), 0.25)!],
              stops: const [0, 0.45, 1],
            ).createShader(front))
        : (Paint()..color = col),
  );
}

/// The block's silhouette (front + top + side), for outlines and clipping.
Path blockOutline(double x0, double x1, double base, double h, double depth) {
  final top = base - h;
  final d = math.min(depth, math.max(1.5, (x1 - x0) * 0.32));
  return Path()
    ..moveTo(x0, base)
    ..lineTo(x0, top)
    ..lineTo(x0 + d, top - d)
    ..lineTo(x1 + d, top - d)
    ..lineTo(x1 + d, base - d)
    ..lineTo(x1, base)
    ..close()
    ..moveTo(x0, top)
    ..lineTo(x1, top)
    ..lineTo(x1, base)
    ..moveTo(x1, top)
    ..lineTo(x1 + d, top - d);
}

/// Paints a block arriving: dashed outline in [outline], liquid [fill] of [col].
void paintLiquidBlock(
  Canvas c,
  double x0,
  double x1,
  double base,
  double h,
  double depth,
  Color col, {
  required LiquidFill fill,
  required double t,
  required Color outline,
  bool shade = true,
}) {
  if (h <= 0.5 || x1 - x0 < 0.5) return;
  if (fill.level >= 0.999 && fill.ripple < 0.05) {
    paintSolidBlock(c, x0, x1, base, h, depth, col, shade: shade);
    return;
  }
  final a = fill.outlineAlpha(t);
  if (a > 0) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = outline.withValues(alpha: outline.a * a);
    for (final m in blockOutline(x0, x1, base, h, depth).computeMetrics()) {
      for (var s = 0.0; s < m.length; s += 5.5) {
        c.drawPath(m.extractPath(s, math.min(s + 3, m.length)), paint);
      }
    }
  }
  if (fill.level <= 0.001) return;
  // Line: the block rises as a comb, no liquid surface
  if (LineInk.on) return paintLineBlock(c, x0, x1, base, h * fill.level, depth, col);
  c.save();
  c.clipPath(liquidClip(x0, x1, base, h, depth, fill));
  paintSolidBlock(c, x0, x1, base, h, depth, col, shade: shade);
  c.restore();
}

/// The region below the liquid surface of a block filling (for painters that
/// draw blocks their own way and only need the clip).
Path liquidClip(double x0, double x1, double base, double h, double depth, LiquidFill fill) {
  final d = math.min(depth, math.max(1.5, (x1 - x0) * 0.32));
  final surface = base - (h + d) * fill.level;
  final liquid = Path()..moveTo(x0 - 1, base + 1);
  final w = x1 + d - x0;
  for (var x = x0 - 1; x <= x1 + d + 1; x += math.max(2.0, w / 16)) {
    liquid.lineTo(x, surface + fill.ripple * math.sin((x - x0) / math.max(6.0, w / 2.2) * math.pi + fill.phase));
  }
  return liquid
    ..lineTo(x1 + d + 1, surface)
    ..lineTo(x1 + d + 1, base + 1)
    ..close();
}

/// Line style bar: an outlined plate with a comb inside. [strong] closes the
/// comb up (today, the busiest hour) instead of switching to a heavier fill.
void paintLineBar(Canvas c, Rect r, Color col, {bool strong = false, double radius = 2}) {
  if (r.height < 1 || r.width < 1) return;
  final ink = LineInk.stroke(col);
  final rr = RRect.fromRectAndCorners(r, topLeft: Radius.circular(radius), topRight: Radius.circular(radius));
  c.drawRRect(rr, Paint()..color = LineInk.plate);
  final gap = strong ? LineInk.comb * 0.7 : LineInk.comb * 1.3;
  final comb = Paint()
    ..color = ink.withValues(alpha: strong ? 0.75 : 0.45)
    ..strokeWidth = LineInk.width * 0.7;
  c.save();
  c.clipRRect(rr);
  for (var x = r.left + gap / 2; x < r.right; x += gap) {
    c.drawLine(Offset(x, r.top + 1), Offset(x, r.bottom), comb);
  }
  c.restore();
  c.drawRRect(
    rr,
    Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = LineInk.width * 0.9
      ..color = ink,
  );
}

/// Line style area: a comb of hairlines under a curve, in place of a wash.
void paintLineArea(Canvas c, Path area, Rect bounds, Color col, {double opacity = 1}) {
  final comb = Paint()
    ..color = LineInk.stroke(col).withValues(alpha: 0.35 * opacity)
    ..strokeWidth = LineInk.width * 0.7;
  c.save();
  c.clipPath(area);
  for (var x = bounds.left; x < bounds.right; x += 5) {
    c.drawLine(Offset(x, bounds.top), Offset(x, bounds.bottom), comb);
  }
  c.restore();
}
