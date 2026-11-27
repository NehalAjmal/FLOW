import 'dart:math' as math;

import 'package:flutter/rendering.dart';
import 'package:material_ui/material_ui.dart';

import '../theme/motion.dart';
import '../theme/tokens.dart';
import '../ui/pressable.dart';

/// Where coach marks register. The sandboxed tutorial app has its own scope,
/// so its marks never mix with the real app's.
class CoachRegistry {
  final _marks = <String, GlobalKey>{};

  /// The mark's box in [ancestor]'s coordinates, or null when it is not on
  /// screen right now.
  Rect? rectOf(String id, RenderBox ancestor) {
    final box = _marks[id]?.currentContext?.findRenderObject();
    if (box is! RenderBox || !box.attached || !box.hasSize) return null;
    final at = box.localToGlobal(Offset.zero, ancestor: ancestor);
    return at & box.size;
  }

  static final root = CoachRegistry();
}

class CoachScope extends InheritedWidget {
  const CoachScope({super.key, required this.registry, required super.child});
  final CoachRegistry registry;

  static CoachRegistry of(BuildContext context) => context.getInheritedWidgetOfExactType<CoachScope>()?.registry ?? CoachRegistry.root;

  @override
  bool updateShouldNotify(CoachScope old) => old.registry != registry;
}

/// Names a control so a tutorial step can light it. Costs nothing otherwise.
class CoachMark extends StatefulWidget {
  const CoachMark(this.id, {super.key, required this.child});
  final String id;
  final Widget child;
  @override
  State<CoachMark> createState() => _CoachMarkState();
}

class _CoachMarkState extends State<CoachMark> {
  final _key = GlobalKey();
  CoachRegistry? _reg;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reg = CoachScope.of(context);
    _reg!._marks[widget.id] = _key;
  }

  @override
  void dispose() {
    if (_reg?._marks[widget.id] == _key) _reg!._marks.remove(widget.id);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => KeyedSubtree(key: _key, child: widget.child);
}

/// One step's light: everything dims except [hole]; only the hole takes
/// input. A hairline ring marks the lit control and a card says one line.
/// The hole glides between steps (SETTLE), so the eye follows the cause.
class CoachLight extends StatefulWidget {
  const CoachLight({super.key, required this.hole, required this.title, this.body, this.actions = const [], this.passThrough = true});

  /// In this widget's coordinates; null = everything dims, the card centres.
  final Rect? hole;
  final String title;
  final String? body;
  final List<Widget> actions;

  /// Whether the lit control takes input (false for "look" steps).
  final bool passThrough;

  @override
  State<CoachLight> createState() => _CoachLightState();
}

class _CoachLightState extends State<CoachLight> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 520));
  Rect? _from, _to;

  @override
  void initState() {
    super.initState();
    _to = widget.hole;
    _c.value = 1;
  }

  @override
  void didUpdateWidget(CoachLight old) {
    super.didUpdateWidget(old);
    if (widget.hole != _to) {
      _from = _current;
      _to = widget.hole;
      if (Motion.reduced(context)) {
        _c.value = 1;
      } else {
        _c.forward(from: 0);
      }
    }
  }

  Rect? get _current {
    final t = const Cubic(0.32, 0.72, 0, 1).transform(_c.value);
    if (_to == null) return null;
    if (_from == null) return _to;
    return Rect.lerp(_from, _to, t);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final hole = _current?.inflate(8);
        return Stack(
          children: [
            Positioned.fill(
              child: _Barrier(
                hole: widget.passThrough ? hole : null,
                child: CustomPaint(
                  painter: _DimPainter(
                    hole: hole,
                    dim: p.bg.computeLuminance() < 0.2 ? const Color(0xD0000000) : const Color(0xB3141612),
                    ring: p.accent,
                  ),
                ),
              ),
            ),
            Positioned.fill(
              child: CustomSingleChildLayout(
                delegate: _CardPlace(hole),
                child: _CoachCard(title: widget.title, body: widget.body, actions: widget.actions),
              ),
            ),
          ],
        );
      },
    );
  }
}

/// Puts the card beside the hole using the card's real height: below, else
/// above, else to the side of a tall mark (the rail), never off screen.
class _CardPlace extends SingleChildLayoutDelegate {
  _CardPlace(this.hole);
  final Rect? hole;
  static const w = 340.0, gap = 18.0, edge = 16.0;

  @override
  BoxConstraints getConstraintsForChild(BoxConstraints c) => BoxConstraints(maxWidth: math.min(w, c.maxWidth - 2 * edge), maxHeight: c.maxHeight);

  @override
  Offset getPositionForChild(Size size, Size card) {
    double clampX(double x) => x.clamp(edge, math.max(edge, size.width - card.width - edge)).toDouble();
    double clampY(double y) => y.clamp(edge, math.max(edge, size.height - card.height - edge)).toDouble();
    final h = hole;
    if (h == null) return Offset(clampX((size.width - card.width) / 2), clampY((size.height - card.height) / 2));
    final x = clampX(h.center.dx - card.width / 2);
    final need = card.height + gap + edge;
    if (size.height - h.bottom >= need) return Offset(x, h.bottom + gap);
    if (h.top >= need) return Offset(x, h.top - gap - card.height);
    final y = clampY(h.center.dy - card.height / 2);
    if (size.width - h.right >= card.width + gap + edge) return Offset(h.right + gap, y);
    if (h.left >= card.width + gap + edge) return Offset(h.left - gap - card.width, y);
    return Offset(x, y);
  }

  @override
  bool shouldRelayout(_CardPlace o) => o.hole != hole;
}

class _CoachCard extends StatelessWidget {
  const _CoachCard({required this.title, this.body, required this.actions});
  final String title;
  final String? body;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      decoration: BoxDecoration(
        color: p.raised,
        borderRadius: BorderRadius.circular(p.line ? 14 : 12),
        border: Border.all(color: p.line ? p.text1 : p.hairline, width: p.line ? p.ink : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            title,
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: p.text1),
          ),
          if (body != null) ...[const SizedBox(height: 6), Text(body!, style: FlowType.note(p, size: 13.5))],
          if (actions.isNotEmpty) ...[const SizedBox(height: 14), Wrap(spacing: 8, runSpacing: 8, children: actions)],
        ],
      ),
    );
  }
}

class _DimPainter extends CustomPainter {
  _DimPainter({required this.hole, required this.dim, required this.ring});
  final Rect? hole;
  final Color dim, ring;
  @override
  void paint(Canvas c, Size s) {
    final all = Path()..addRect(Offset.zero & s);
    final h = hole;
    if (h == null) {
      c.drawPath(all, Paint()..color = dim);
      return;
    }
    final rr = RRect.fromRectAndRadius(h, const Radius.circular(14));
    // even-odd, not Path.combine: the boolean op leaves the hole filled on web
    c.drawPath(
      Path()
        ..fillType = PathFillType.evenOdd
        ..addRect(Offset.zero & s)
        ..addRRect(rr),
      Paint()..color = dim,
    );
    c.drawRRect(
      rr,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.4
        ..color = ring,
    );
    // an outer echo ring, the lit control's halo
    c.drawRRect(
      rr.inflate(6),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.8
        ..color = ring.withValues(alpha: 0.35),
    );
  }

  @override
  bool shouldRepaint(_DimPainter o) => o.hole != hole || o.dim != dim || o.ring != ring;
}

/// Absorbs every pointer outside [hole]; inside it, input reaches the app.
class _Barrier extends SingleChildRenderObjectWidget {
  const _Barrier({required this.hole, super.child});
  final Rect? hole;
  @override
  RenderObject createRenderObject(BuildContext context) => _RenderBarrier(hole);
  @override
  void updateRenderObject(BuildContext context, _RenderBarrier r) => r.hole = hole;
}

class _RenderBarrier extends RenderProxyBox {
  _RenderBarrier(this.hole);
  Rect? hole;
  @override
  bool hitTest(BoxHitTestResult result, {required Offset position}) {
    if (hole != null && hole!.contains(position)) return false;
    result.add(BoxHitTestEntry(this, position));
    return true;
  }
}

/// A quiet text button for coach cards (Skip, Back).
class CoachQuiet extends StatelessWidget {
  const CoachQuiet(this.label, this.onPressed, {super.key});
  final String label;
  final VoidCallback onPressed;
  @override
  Widget build(BuildContext context) => Pressable(
    onPressed: onPressed,
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    child: Text(label, style: const TextStyle(fontSize: 12.5)),
  );
}
