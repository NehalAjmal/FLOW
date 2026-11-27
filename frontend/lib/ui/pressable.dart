import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';

import '../theme/motion.dart';
import '../theme/palette.dart';
import 'style_morph.dart';

enum PressableTone {
  /// Neutral raised (chips, presets, secondary buttons).
  raised,

  /// The one filled action per view (dark neutral, never the accent).
  primary,
}

/// A tiny front-on solid with a 2 px lip (spec §2, control language).
///
/// Hover lifts 1 px (SNAP) · press sinks 2 px into the lip (FOLLOW) ·
/// release springs back (SNAP). No drop shadow: the lip is the depth.
/// Keyboard: focusable, Enter/Space activate; screen readers get a button.
class Pressable extends StatefulWidget {
  const Pressable({
    super.key,
    required this.child,
    required this.onPressed,
    this.tone = PressableTone.raised,
    this.selected = false,
    this.radius = 8,
    this.padding = const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
    this.semanticLabel,
    this.tooltip,
  });

  final Widget child;
  final VoidCallback? onPressed;
  final PressableTone tone;

  /// Chosen state for chips/presets: dark neutral face, pressed in by 1 px.
  final bool selected;
  final double radius;
  final EdgeInsets padding;
  final String? semanticLabel;
  final String? tooltip;

  static const lip = 2.0;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> with SingleTickerProviderStateMixin {
  late final _y = SpringValue(vsync: this, initial: 0);
  bool _hover = false;
  bool _down = false;
  bool _focused = false;

  bool get _enabled => widget.onPressed != null;

  double get _rest => widget.selected ? 1 : 0;

  void _to(double v, {bool press = false}) {
    if (!mounted) return;
    _y.animateTo(v, spring: press ? Motion.follow : Motion.snap, reduced: Motion.reduced(context));
  }

  void _sync() {
    if (!_enabled) return _to(_rest);
    if (_down) return _to(Pressable.lip, press: true);
    if (_hover) return _to(widget.selected ? _rest : -1);
    _to(_rest);
  }

  @override
  void didUpdateWidget(Pressable old) {
    super.didUpdateWidget(old);
    if (old.selected != widget.selected) _sync();
  }

  @override
  void dispose() {
    _y.dispose();
    super.dispose();
  }

  void _press(bool down) {
    _down = down;
    _sync();
  }

  void _activate() {
    if (!_enabled) return;
    HapticFeedback.selectionClick();
    widget.onPressed!();
  }

  /// Line: the same physics as Solid, drawn in hairlines. The lip becomes an
  /// echo outline 2 px under the pill; hover lifts the pill off it (1 px),
  /// press sinks the pill onto it, so a Line button feels like a Solid one.
  /// Fills change with the hover spring's timing, never instantly.
  Widget _lineBody(FlowPalette p, bool primary, Color fg) {
    final r = BorderRadius.circular(widget.radius * 2 + 6);
    final edge = !_enabled ? p.text3.withValues(alpha: 0.45) : p.text1;
    final fill = primary && _enabled ? p.selected : (_hover && _enabled ? p.text1.withValues(alpha: 0.06) : p.bg.withValues(alpha: 0));
    return AnimatedBuilder(
      animation: _y.animation,
      builder: (context, child) {
        final dy = _y.value.clamp(-1.0, Pressable.lip);
        // how far the pill sits above its echo: 0 when pressed fully in
        final gap = (Pressable.lip - dy).clamp(0.0, Pressable.lip + 1);
        return Padding(
          padding: const EdgeInsets.only(top: 1),
          child: Stack(
            children: [
              Positioned.fill(
                top: Pressable.lip,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    borderRadius: r,
                    border: Border.all(
                      color: edge.withValues(alpha: 0.28 * (gap / Pressable.lip).clamp(0.0, 1.0)),
                      width: p.ink * 0.8,
                    ),
                  ),
                ),
              ),
              Transform.translate(
                offset: Offset(0, dy),
                child: Padding(
                  padding: const EdgeInsets.only(bottom: Pressable.lip),
                  child: TweenAnimationBuilder<Color?>(
                    tween: ColorTween(end: fill),
                    duration: Motion.reduced(context) ? Duration.zero : const Duration(milliseconds: 180),
                    curve: const Cubic(0.32, 0.72, 0, 1),
                    builder: (context, c, inner) => DecoratedBox(
                      decoration: BoxDecoration(
                        color: c,
                        borderRadius: r,
                        border: Border.all(color: edge, width: p.ink),
                      ),
                      child: inner,
                    ),
                    child: Padding(padding: widget.padding, child: child),
                  ),
                ),
              ),
            ],
          ),
        );
      },
      child: DefaultTextStyle.merge(
        style: TextStyle(color: fg, fontSize: 13, fontWeight: FontWeight.w500),
        child: IconTheme.merge(
          data: IconThemeData(color: fg, size: 16),
          child: Center(widthFactor: 1, child: widget.child),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = FlowPalette.of(context);
    final primary = widget.tone == PressableTone.primary || widget.selected;
    final face = !_enabled ? p.recess : (primary ? p.selected : p.raised);
    final lip = primary ? Faces.ground(face) : Color.lerp(p.hairline, p.text3, 0.25)!;
    final fg = !_enabled ? p.text3 : (primary ? p.onSelected : p.text1);
    final r = BorderRadius.circular(widget.radius);

    Widget body = p.line
        ? _lineBody(p, primary, fg)
        : AnimatedBuilder(
            animation: _y.animation,
            builder: (context, child) {
              final dy = _y.value.clamp(-1.0, Pressable.lip);
              return Padding(
                padding: const EdgeInsets.only(top: 1), // room for the hover lift
                child: Stack(
                  children: [
                    // the lip: what remains visible under the face
                    Positioned.fill(
                      top: Pressable.lip,
                      child: DecoratedBox(
                        decoration: BoxDecoration(color: lip, borderRadius: r),
                      ),
                    ),
                    Transform.translate(
                      offset: Offset(0, dy),
                      child: Padding(
                        padding: EdgeInsets.only(bottom: Pressable.lip),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: face,
                            borderRadius: r,
                            border: primary ? null : Border.all(color: p.hairline, width: 1),
                          ),
                          child: Padding(padding: widget.padding, child: child),
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
            child: DefaultTextStyle.merge(
              style: TextStyle(color: fg, fontSize: 13, fontWeight: FontWeight.w500),
              child: IconTheme.merge(
                data: IconThemeData(color: fg, size: 16),
                child: Center(widthFactor: 1, child: widget.child),
              ),
            ),
          );

    body = FocusableActionDetector(
      enabled: _enabled,
      mouseCursor: _enabled ? SystemMouseCursors.click : SystemMouseCursors.basic,
      onShowHoverHighlight: (h) {
        _hover = h;
        _sync();
      },
      onShowFocusHighlight: (f) => setState(() => _focused = f),
      actions: {ActivateIntent: CallbackAction<ActivateIntent>(onInvoke: (_) => _activate())},
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: _enabled ? (_) => _press(true) : null,
        onTapCancel: () => _press(false),
        onTapUp: _enabled ? (_) => _press(false) : null,
        // null when disabled, so assistive tech doesn't offer a tap that does nothing
        onTap: _enabled ? _activate : null,
        child: DecoratedBox(
          position: DecorationPosition.foreground,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(widget.radius + 2),
            border: _focused ? Border.all(color: p.accent, width: 1.5) : null,
          ),
          child: body,
        ),
      ),
    );

    body = Semantics(button: true, enabled: _enabled, selected: widget.selected, label: widget.semanticLabel, child: body);
    if (widget.tooltip != null) body = Tooltip(message: widget.tooltip!, child: body);
    return MorphMark(kind: MorphKind.control, radius: widget.radius, child: body);
  }
}
