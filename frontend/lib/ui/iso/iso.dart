// Isometric helpers. Ideas ported from Hairline (github.com/lucasmarkes/hairline,
// MIT, © 2026 Lucas Marques): a fixed 2:1 camera, solids built from rounded
// rings, painted back to front, hit-testing against the rest pose on the ground plane.
import 'dart:math' as math;
import 'dart:ui';

import '../../theme/palette.dart';
import '../blocks.dart' show LineInk;

/// Fixed 2:1 dimetric camera (Hairline's Cam(45, 0.5, S)). Parallel
/// projection: no perspective, so equal heights stay equal (spec: honesty).
class IsoCamera {
  const IsoCamera({required this.origin, required this.scale}) : recede = null;

  /// The projection Home's day blocks use: front faces flat to the screen,
  /// depth receding up and to the right by [recede] per world unit. World x
  /// runs left to right, world y comes toward you (larger y = nearer), z up.
  /// One projection across Home's score, Look back and Team.
  const IsoCamera.oblique({required this.origin, required this.scale, this.recede = const Offset(0.55, -0.5)});

  /// Screen position of world (0, 0, 0).
  final Offset origin;

  /// Screen px per world unit.
  final double scale;

  /// Oblique depth step per world unit of y (null: the 2:1 dimetric camera).
  final Offset? recede;

  bool get isOblique => recede != null;

  static const _c = 0.7071067811865476; // cos 45°

  Offset project(double x, double y, [double z = 0]) {
    final r = recede;
    if (r != null) return origin + Offset((x - y * r.dx) * scale, (-z - y * r.dy) * scale);
    return origin + Offset((x - y) * _c * scale, ((x + y) * _c * 0.5 - z) * scale);
  }

  /// Screen → ground plane (z = 0). Hit tests use this, never the drawn pose.
  (double, double) unproject(Offset s) {
    final r = recede;
    if (r != null) {
      final y = (s.dy - origin.dy) / (-r.dy * scale);
      return ((s.dx - origin.dx) / scale + y * r.dx, y);
    }
    final u = (s.dx - origin.dx) / (_c * scale); // x - y
    final v = (s.dy - origin.dy) / (_c * 0.5 * scale); // x + y
    return ((u + v) / 2, (v - u) / 2);
  }

  /// Painter's order for cells (row y, column x): far first.
  int compareCells((int, int) a, (int, int) b) =>
      isOblique ? (a.$1 != b.$1 ? a.$1.compareTo(b.$1) : a.$2.compareTo(b.$2)) : (a.$1 + a.$2).compareTo(b.$1 + b.$2);
}

/// A rounded-footprint pillar drawn as three shaded faces, one light
/// direction app-wide (top lightest, left as-is, right darkest).
void paintPillar(
  Canvas c,
  IsoCamera cam,
  double x,
  double y,
  double w,
  double h,
  Color fill, {
  double inset = 0.12,
  double ripple = 0,
  double phase = 0,
}) {
  final x0 = x + inset, y0 = y + inset, x1 = x + w - inset, y1 = y + w - inset;
  // [ripple] (in z units) tilts the top surface like liquid settling: each top
  // corner bobs out of phase, so the face sloshes and then calms.
  double zt(double a, double b) => h + ripple * math.sin(phase + (a - x0) * 4.1 + (b - y0) * 2.3);
  Offset p(double a, double b, double z) => cam.project(a, b, z == h ? zt(a, b) : z);
  final round = Paint()
    ..style = PaintingStyle.fill
    ..isAntiAlias = true;
  // left face (x0..x1 along y1 edge) and right face (y0..y1 along x1 edge)
  final left = Path()
    ..moveTo(p(x0, y1, 0).dx, p(x0, y1, 0).dy)
    ..lineTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy)
    ..lineTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
    ..lineTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
    ..close();
  final right = Path()
    ..moveTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy)
    ..lineTo(p(x1, y0, 0).dx, p(x1, y0, 0).dy)
    ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy)
    ..lineTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
    ..close();
  final top = Path()
    ..moveTo(p(x0, y0, h).dx, p(x0, y0, h).dy)
    ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy)
    ..lineTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
    ..lineTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
    ..close();
  if (LineInk.on) {
    // Line: plates (hide what is behind), bright silhouette, dim crease,
    // and a few hairlines on the shaded face so the one light still reads.
    final ink = LineInk.stroke(fill);
    final plate = Paint()..color = LineInk.plate;
    c.drawPath(left, plate);
    c.drawPath(right, plate);
    c.drawPath(top, plate);
    final pen = Paint()
      ..style = PaintingStyle.stroke
      ..strokeJoin = StrokeJoin.round
      ..strokeWidth = LineInk.width * 0.9
      ..color = ink.withValues(alpha: 0.4);
    const k = 4;
    for (var i = 1; i < k; i++) {
      final yy = y0 + (y1 - y0) * i / k;
      c.drawLine(p(x1, yy, 0), p(x1, yy, h), pen);
    }
    c.drawPath(
      Path()
        ..moveTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
        ..lineTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
        ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy)
        ..moveTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
        ..lineTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy),
      pen..color = ink.withValues(alpha: 0.5),
    );
    final sil = Path()
      ..moveTo(p(x0, y1, 0).dx, p(x0, y1, 0).dy)
      ..lineTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy)
      ..lineTo(p(x1, y0, 0).dx, p(x1, y0, 0).dy)
      ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy)
      ..lineTo(p(x0, y0, h).dx, p(x0, y0, h).dy)
      ..lineTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
      ..close();
    c.drawPath(
      sil,
      pen
        ..color = ink
        ..strokeWidth = LineInk.width,
    );
    return;
  }
  c.drawPath(left, round..color = fill);
  c.drawPath(right, round..color = Faces.side(fill));
  c.drawPath(top, round..color = Faces.top(fill));
  // one dim crease where the top meets the faces (bright outside, dim inside)
  c.drawPath(
    Path()
      ..moveTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
      ..lineTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
      ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy),
    Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.6
      ..strokeJoin = StrokeJoin.round
      ..color = Faces.top(Faces.top(fill)).withValues(alpha: 0.7),
  );
  // grounding edge where it meets the floor
  c.drawPath(
    Path()
      ..moveTo(p(x0, y1, 0).dx, p(x0, y1, 0).dy)
      ..lineTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy)
      ..lineTo(p(x1, y0, 0).dx, p(x1, y0, 0).dy),
    Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.8
      ..color = Faces.ground(fill),
  );
}

/// The pillar's silhouette as a dashed outline ("not yet"), used before the
/// liquid fill arrives (the wordmark's motion, applied to day pillars).
void paintPillarOutline(Canvas c, IsoCamera cam, double x, double y, double w, double h, Color color, {double inset = 0.12}) {
  final x0 = x + inset, y0 = y + inset, x1 = x + w - inset, y1 = y + w - inset;
  Offset p(double a, double b, double z) => cam.project(a, b, z);
  final path = Path()
    ..moveTo(p(x0, y1, 0).dx, p(x0, y1, 0).dy)
    ..lineTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy)
    ..lineTo(p(x1, y0, 0).dx, p(x1, y0, 0).dy)
    ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy)
    ..lineTo(p(x0, y0, h).dx, p(x0, y0, h).dy)
    ..lineTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
    ..close()
    ..moveTo(p(x0, y1, h).dx, p(x0, y1, h).dy)
    ..lineTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
    ..lineTo(p(x1, y0, h).dx, p(x1, y0, h).dy)
    ..moveTo(p(x1, y1, h).dx, p(x1, y1, h).dy)
    ..lineTo(p(x1, y1, 0).dx, p(x1, y1, 0).dy);
  final paint = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = 0.9
    ..color = color;
  for (final m in path.computeMetrics()) {
    for (var s = 0.0; s < m.length; s += 4.5) {
      c.drawPath(m.extractPath(s, math.min(s + 2.5, m.length)), paint);
    }
  }
}

/// Hairline floor cell (the line is the ground: no plinths).
void paintCell(Canvas c, IsoCamera cam, double x, double y, double w, Color line) {
  final path = Path()
    ..moveTo(cam.project(x, y).dx, cam.project(x, y).dy)
    ..lineTo(cam.project(x + w, y).dx, cam.project(x + w, y).dy)
    ..lineTo(cam.project(x + w, y + w).dx, cam.project(x + w, y + w).dy)
    ..lineTo(cam.project(x, y + w).dx, cam.project(x, y + w).dy)
    ..close();
  c.drawPath(
    path,
    Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.7
      ..color = line,
  );
}

/// Distance falloff with a floor (Hairline rule 03: clamp the reach).
double falloff(double d, double radius) {
  if (d >= radius) return 0;
  final t = d / radius;
  return math.max(0, 1 - t * t);
}
