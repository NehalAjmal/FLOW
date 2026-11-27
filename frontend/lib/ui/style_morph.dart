import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:material_ui/material_ui.dart';

/// Solid ⇄ Line as a transformation: every element changes in its own way,
/// in order of distance from the control that asked for it.
///
/// How it works: the page as it looked is captured as one image (as the
/// infection does). The app switches style underneath at once. Over it, each
/// marked element's piece of the old image is taken away by that element's
/// own mechanism, so the new element is revealed the way that kind of thing
/// would change:
///
/// | kind    | to Line                                   | to Solid                               |
/// |---------|-------------------------------------------|----------------------------------------|
/// | panel   | the wash recedes from the edge inward     | the wash floods out from the middle    |
/// | control | the face shrinks into its outline         | the face fills from the middle         |
/// | rise    | the solid drains down to a level line     | it fills up from the floor             |
/// | chart   | a pen re-plots it left to right           | the same pen, inking it in             |
/// | dial    | a hand sweeps it round from 12            | the same hand                          |
/// | text    | the old line lifts away                   | the old line lifts away                |
/// | ground  | everything unmarked: a clean circle from the press point |                         |
///
/// Each element starts when the ground's front reaches its centre, so the
/// change still reads as one cause (Rule A) with many effects. Reduced
/// motion: a 150 ms cross-fade.
enum MorphKind { panel, control, rise, chart, dial, text }

/// Names an element for the style change. Costs a set insert otherwise.
class MorphMark extends StatefulWidget {
  const MorphMark({super.key, required this.kind, this.radius = 0, required this.child});
  final MorphKind kind;
  final double radius;
  final Widget child;

  @override
  State<MorphMark> createState() => _MorphMarkState();

  /// The marks on screen, measured in [ancestor]'s coordinates.
  static List<MorphRegion> collect(RenderBox ancestor, Offset origin) {
    final size = ancestor.size;
    final screen = Offset.zero & size;
    final out = <MorphRegion>[];
    for (final m in _marks) {
      if (!m.mounted) continue;
      if (ModalRoute.of(m.context)?.isCurrent == false) continue;
      final box = m.context.findRenderObject();
      if (box is! RenderBox || !box.attached || !box.hasSize || box.size.isEmpty) continue;
      final Rect r;
      try {
        r = MatrixUtils.transformRect(box.getTransformTo(ancestor), Offset.zero & box.size);
      } catch (_) {
        continue;
      }
      if (!r.overlaps(screen) || r.width < 4 || r.height < 4) continue;
      // a title is set in a different face per style, so its old line can
      // run longer than the new one: take the room it may have used
      final area = m.widget.kind == MorphKind.text
          ? Rect.fromLTRB(r.left, r.top - 2, math.min(size.width, r.right + r.width * 0.45), r.bottom + 2)
          : r;
      out.add(MorphRegion(area, m.widget.kind, m.widget.radius));
      if (out.length >= 240) break;
    }
    // nesting: each region excludes its direct children, so every pixel
    // belongs to exactly one mechanism (the innermost)
    out.sort((a, b) => (b.rect.width * b.rect.height).compareTo(a.rect.width * a.rect.height));
    for (var i = 0; i < out.length; i++) {
      for (var j = i - 1; j >= 0; j--) {
        if (_inside(out[i].rect, out[j].rect)) {
          out[i].parent = out[j];
          out[j].children.add(out[i]);
          break;
        }
      }
    }
    final far = [screen.topLeft, screen.topRight, screen.bottomLeft, screen.bottomRight].map((c) => (c - origin).distance).reduce(math.max);
    for (final r in out) {
      r.delay = MorphPainter.wave * ((r.rect.center - origin).distance / far).clamp(0.0, 1.0);
    }
    // earliest / latest start in each subtree (children are smaller, so they
    // come later in [out]: walk it backwards)
    for (final r in out.reversed) {
      r.first = r.children.fold(r.delay, (m, c) => math.min(m, c.first));
      r.last = r.children.fold(r.delay, (m, c) => math.max(m, c.last));
    }
    return out;
  }

  static bool _inside(Rect a, Rect b) => a.left >= b.left - 1 && a.top >= b.top - 1 && a.right <= b.right + 1 && a.bottom <= b.bottom + 1 && a != b;
}

final _marks = <_MorphMarkState>{};

class _MorphMarkState extends State<MorphMark> {
  @override
  void initState() {
    super.initState();
    _marks.add(this);
  }

  @override
  void dispose() {
    _marks.remove(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

class MorphRegion {
  MorphRegion(this.rect, this.kind, this.radius);
  final Rect rect;
  final MorphKind kind;
  final double radius;
  MorphRegion? parent;
  final children = <MorphRegion>[];
  double delay = 0;

  /// Earliest and latest [delay] in this region's subtree.
  double first = 0, last = 0;

  RRect get rrect => RRect.fromRectAndRadius(rect, Radius.circular(math.min(radius, rect.shortestSide / 2)));
}

class MorphPainter extends CustomPainter {
  MorphPainter({
    required this.image,
    required this.t,
    required this.origin,
    required this.regions,
    required this.toLine,
    required this.ink,
    required this.lead,
    this.fadeOnly = false,
  }) : super(repaint: t);

  final ui.Image image;
  final Animation<double> t;
  final Offset origin;
  final List<MorphRegion> regions;
  final bool toLine;
  final Color ink, lead;
  final bool fadeOnly;

  /// Share of the run the front takes to cross the page; each element then
  /// changes over [span].
  static const wave = 0.5, span = 0.5;
  static const _ease = Cubic(0.32, 0.72, 0, 1);

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final src = Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble());
    final p = t.value;
    if (fadeOnly) {
      canvas.drawImageRect(image, src, rect, Paint()..color = Color.fromRGBO(0, 0, 0, 1 - p));
      return;
    }
    final img = Paint()..filterQuality = FilterQuality.medium;
    final sx = image.width / size.width, sy = image.height / size.height;
    final pen = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..strokeCap = StrokeCap.round;
    canvas.save();
    canvas.clipRect(rect);

    void old(Path area, {Offset shift = Offset.zero, double alpha = 1, Offset? about, double scale = 1}) {
      if (alpha <= 0.01) return;
      canvas.save();
      canvas.clipPath(area);
      if (shift != Offset.zero) canvas.translate(shift.dx, shift.dy);
      if (about != null && scale != 1) {
        canvas.translate(about.dx, about.dy);
        canvas.scale(scale);
        canvas.translate(-about.dx, -about.dy);
      }
      // only the pixels under the clip: a full-page image per region is the
      // cost that made dense pages drop frames on web
      final paint = alpha < 1 ? (Paint()..color = Color.fromRGBO(0, 0, 0, alpha)) : img;
      final transformed = shift != Offset.zero || (about != null && scale != 1);
      final dst = transformed ? rect : area.getBounds().intersect(rect);
      if (!dst.isEmpty) canvas.drawImageRect(image, Rect.fromLTRB(dst.left * sx, dst.top * sy, dst.right * sx, dst.bottom * sy), dst, paint);
      canvas.restore();
    }

    // a region minus its direct children (even-odd, which also works on web)
    Path own(Path outline, Iterable<MorphRegion> holes) {
      final path = Path()..fillType = PathFillType.evenOdd;
      path.addPath(outline, Offset.zero);
      for (final h in holes) {
        path.addRRect(h.rrect);
      }
      return path;
    }

    // ── ground: everything unmarked, a clean circle from the press point
    final far = [rect.topLeft, rect.topRight, rect.bottomLeft, rect.bottomRight].map((c) => (c - origin).distance).reduce(math.max);
    final g = _ease.transform((p / wave).clamp(0.0, 1.0));
    final radius = far * 1.02 * g;
    if (g < 1) {
      final outside = Path()
        ..fillType = PathFillType.evenOdd
        ..addRect(rect)
        ..addOval(Rect.fromCircle(center: origin, radius: radius));
      canvas.save();
      canvas.clipPath(outside);
      old(own(Path()..addRect(rect), regions.where((r) => r.parent == null)));
      canvas.restore();
      if (radius > 1) canvas.drawCircle(origin, radius, pen..color = lead.withValues(alpha: 0.55 * (1 - g)));
    }

    // Subtrees nothing in which has started are still wholly the old page:
    // one draw for all of them. Subtrees that have all finished draw nothing.
    final untouched = Path();
    void step(MorphRegion r) {
      final e = _ease.transform(((p - r.delay) / span).clamp(0.0, 1.0));
      if (e >= 1) return;
      final box = r.rect;
      final mine = own(Path()..addRRect(r.rrect), r.children);
      canvas.save();
      canvas.clipPath(mine);
      final edge = ink.withValues(alpha: 0.6 * math.sin(math.pi * e));
      switch (r.kind) {
        case MorphKind.panel:
          // to Line the wash recedes from the border; to Solid it floods out
          final inset = box.shortestSide / 2 * (toLine ? e : 1 - e);
          final inner = r.rrect.deflate(inset);
          // the old wash thins as it goes, so its text never sits doubled
          if (toLine) {
            old(Path()..addRRect(inner), alpha: 1 - e);
          } else {
            old(
              Path()
                ..fillType = PathFillType.evenOdd
                ..addRRect(r.rrect)
                ..addRRect(inner),
              alpha: 1 - e,
            );
          }
          if (e > 0) canvas.drawRRect(inner, pen..color = edge);
        case MorphKind.control:
          final k = toLine ? 1 - e : e;
          final s = RRect.fromRectAndRadius(
            Rect.fromCenter(center: box.center, width: box.width * k, height: box.height * k),
            Radius.circular(math.min(r.radius, box.shortestSide / 2) * k),
          );
          // to Line the old face, label and all, folds into the middle of
          // its pill; to Solid the old outline opens out from the middle
          if (toLine) {
            old(Path()..addRRect(s), about: box.center, scale: k, alpha: k);
          } else {
            old(
              Path()
                ..fillType = PathFillType.evenOdd
                ..addRRect(r.rrect)
                ..addRRect(s),
              alpha: 1 - e,
            );
          }
          if (e > 0 && k > 0.05) canvas.drawRRect(s, pen..color = edge);
        case MorphKind.rise:
          // a level line: drains to Line, fills up to Solid
          final y = toLine ? box.top + box.height * e : box.bottom - box.height * e;
          old(Path()..addRect(toLine ? Rect.fromLTRB(box.left, y, box.right, box.bottom) : Rect.fromLTRB(box.left, box.top, box.right, y)));
          if (e > 0) canvas.drawLine(Offset(box.left, y), Offset(box.right, y), pen..color = edge);
        case MorphKind.chart:
          // a pen re-plots it, left to right along time
          final x = box.left + box.width * e;
          old(Path()..addRect(Rect.fromLTRB(x, box.top, box.right, box.bottom)));
          if (e > 0) {
            canvas.drawLine(Offset(x, box.top), Offset(x, box.bottom), pen..color = edge);
            canvas.drawCircle(Offset(x, box.top + 2), 2, Paint()..color = lead.withValues(alpha: math.sin(math.pi * e)));
          }
        case MorphKind.dial:
          // a hand sweeps from 12 o'clock
          final a = -math.pi / 2 + 2 * math.pi * e;
          final rr = box.longestSide;
          final sector = Path()
            ..moveTo(box.center.dx, box.center.dy)
            ..arcTo(Rect.fromCircle(center: box.center, radius: rr), a, 2 * math.pi * (1 - e) - 1e-4, false)
            ..close();
          if (e == 0) {
            old(Path()..addRect(box));
          } else {
            old(sector);
          }
          if (e > 0) {
            final hand = box.center + Offset(math.cos(a), math.sin(a)) * (box.shortestSide / 2);
            canvas.drawLine(box.center, hand, pen..color = edge);
          }
        case MorphKind.text:
          // the old line lifts away as the new one is already in place
          old(Path()..addRect(box), shift: Offset(0, -10 * e), alpha: (1 - e) * (1 - e));
      }
      canvas.restore();
    }

    void walk(MorphRegion r) {
      if (p <= r.first) {
        untouched.addRRect(r.rrect);
        return;
      }
      if (p >= r.last + span) return;
      step(r);
      r.children.forEach(walk);
    }

    regions.where((r) => r.parent == null).forEach(walk);
    old(untouched);
    canvas.restore();
  }

  @override
  bool shouldRepaint(MorphPainter o) => o.image != image || o.origin != origin || o.regions != regions || o.toLine != toLine;
}
