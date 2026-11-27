import 'package:material_ui/material_ui.dart';

/// "Stone & Verdigris, ink drying". DESIGN_SPEC §16.
///
/// Colour carries meaning, never decoration:
/// - warm stone = the past, cool verdigris line-work = the future
/// - [accent] = NOW / active only (never "selected"; that is [selected])
/// - [ultra] (mist, a grey-green) = planned / not yet: schedules,
///   projections, the next block. Quiet line-work and faint washes only;
///   colour in Flow is atmosphere, never a loud second accent.
///   [ultraDeep] is the warm-stone brand field.
/// - [amber] = break soon / due
/// - [problem] = system problems only, never a person's state
@immutable
class FlowPalette extends ThemeExtension<FlowPalette> {
  const FlowPalette({
    required this.bg,
    required this.raised,
    required this.recess,
    required this.hairline,
    required this.text1,
    required this.text2,
    required this.text3,
    required this.selected,
    required this.pastLight,
    required this.pastModerate,
    required this.pastHeavy,
    required this.accent,
    required this.accentTint,
    required this.accentDeep,
    required this.future,
    required this.ultra,
    required this.ultraTint,
    required this.ultraDeep,
    required this.amber,
    required this.amberTint,
    required this.problem,
    this.line = false,
  });

  /// The Line style: the same readings drawn as hairlines on a sage ground,
  /// no filled solids. Painters branch on this; meaning colours are shared.
  final bool line;

  final Color bg;
  final Color raised;
  final Color recess;
  final Color hairline;
  final Color text1;
  final Color text2;
  final Color text3;

  /// Dark neutral: active nav pill, lit pillar, segmented choice, Start button.
  final Color selected;

  /// Finished session blocks, by declared demand.
  final Color pastLight;
  final Color pastModerate;
  final Color pastHeavy;

  final Color accent;
  final Color accentTint;
  final Color accentDeep;

  /// Line-work for everything that has not happened yet (= [ultra]).
  final Color future;

  /// Mist: the quiet hue for planned / not yet.
  final Color ultra;
  final Color ultraTint;

  /// Brand field (sign-in stage): a deeper warm stone; normal ink on it.
  final Color ultraDeep;

  /// Paper-white text/strokes drawn on [ultraDeep].
  Color get onField => const Color(0xFFF4F2EC);

  /// Line "colour" option (preview): what happened is drawn in slate blue
  /// instead of ink, so Line reads blue = past, green = now, amber = strain.
  static const lineColour = bool.fromEnvironment('LINE_COLOUR');

  /// The colour of Line's data marks (combs, bars, blocks): ink, or slate
  /// blue with the colour option.
  Color get lineData => !line || !lineColour ? text1 : (bg.computeLuminance() < 0.2 ? const Color(0xFF8FA8D6) : const Color(0xFF34527F));

  final Color amber;
  final Color amberTint;
  final Color problem;

  List<Color> get pastByDemand => [pastLight, pastModerate, pastHeavy];

  /// Text/icons drawn on [selected].
  Color get onSelected => bg;

  static const light = FlowPalette(
    bg: Color(0xFFEFEEE9),
    raised: Color(0xFFFAF9F6),
    recess: Color(0xFFE4E2DB),
    hairline: Color(0xFFC9C5BB),
    text1: Color(0xFF1C1D1A),
    text2: Color(0xFF4F514B),
    text3: Color(0xFF5F6058),
    selected: Color(0xFF23241F),
    pastLight: Color(0xFFCBBFA8),
    pastModerate: Color(0xFFA8967A),
    pastHeavy: Color(0xFF76654E),
    accent: Color(0xFF06705B),
    accentTint: Color(0xFFD6EDE6),
    accentDeep: Color(0xFF055A48),
    future: Color(0xFF53675F),
    ultra: Color(0xFF53675F),
    ultraTint: Color(0xFFE6E9E6),
    ultraDeep: Color(0xFFE6E3DC),
    amber: Color(0xFF955C00),
    amberTint: Color(0xFFF3E6CB),
    problem: Color(0xFF9A4436),
  );

  static const dark = FlowPalette(
    bg: Color(0xFF161816),
    raised: Color(0xFF1F221F),
    recess: Color(0xFF0F110F),
    hairline: Color(0xFF343833),
    text1: Color(0xFFE9ECE6),
    text2: Color(0xFFA6ABA2),
    text3: Color(0xFF8A8F86),
    selected: Color(0xFFE4E8E0),
    pastLight: Color(0xFF463E32),
    pastModerate: Color(0xFF655846),
    pastHeavy: Color(0xFF8F7E64),
    accent: Color(0xFF45C4A2),
    accentTint: Color(0xFF143B32),
    accentDeep: Color(0xFF8AE6CF),
    future: Color(0xFF7F9590),
    ultra: Color(0xFF7F9590),
    ultraTint: Color(0xFF1C211F),
    ultraDeep: Color(0xFF1F221E),
    amber: Color(0xFFE3A53F),
    amberTint: Color(0xFF3A2C12),
    problem: Color(0xFFDB7E69),
  );

  /// Line style, light: ink on sage. Same meaning colours as Solid.
  static const lineLight = FlowPalette(
    bg: Color(0xFFE8ECE3),
    raised: Color(0xFFEEF1EA),
    recess: Color(0xFFDFE4D9),
    hairline: Color(0xFFBCC2B6),
    text1: Color(0xFF1C1E1A),
    text2: Color(0xFF4E534A),
    text3: Color(0xFF5C6158),
    selected: Color(0xFF1C1E1A),
    pastLight: Color(0xFFC6CCC0),
    pastModerate: Color(0xFF959C90),
    pastHeavy: Color(0xFF5A6156),
    accent: Color(0xFF06705B),
    accentTint: Color(0xFFD3E6DD),
    accentDeep: Color(0xFF055A48),
    future: Color(0xFF53675F),
    ultra: Color(0xFF53675F),
    ultraTint: Color(0xFFE2E7DE),
    ultraDeep: Color(0xFFE2E6DC),
    amber: Color(0xFF955C00),
    amberTint: Color(0xFFF0E4C8),
    problem: Color(0xFF9A4436),
    line: true,
  );

  /// Line style, dark: pale ink on near-black.
  static const lineDark = FlowPalette(
    bg: Color(0xFF121412),
    raised: Color(0xFF171A17),
    recess: Color(0xFF0D0F0D),
    hairline: Color(0xFF3A403A),
    text1: Color(0xFFE2E7DC),
    text2: Color(0xFFA0A69B),
    text3: Color(0xFF8A9086),
    selected: Color(0xFFE2E7DC),
    pastLight: Color(0xFF3A4038),
    pastModerate: Color(0xFF6A7166),
    pastHeavy: Color(0xFFA3AA9E),
    accent: Color(0xFF45C4A2),
    accentTint: Color(0xFF12352C),
    accentDeep: Color(0xFF8AE6CF),
    future: Color(0xFF7F9590),
    ultra: Color(0xFF7F9590),
    ultraTint: Color(0xFF1A1E1B),
    ultraDeep: Color(0xFF1C201C),
    amber: Color(0xFFE3A53F),
    amberTint: Color(0xFF36290F),
    problem: Color(0xFFDB7E69),
    line: true,
  );

  static FlowPalette pick(Brightness b, {bool line = false}) =>
      line ? (b == Brightness.dark ? lineDark : lineLight) : (b == Brightness.dark ? dark : light);

  /// Stroke width for line-style marks: dark grounds get a heavier hairline
  /// so 1 px ink does not break up on 1x screens.
  double get ink => bg.computeLuminance() < 0.2 ? 1.25 : 1.0;

  static FlowPalette of(BuildContext context) => Theme.of(context).extension<FlowPalette>() ?? light;

  /// "Ink drying": a finished block drifts from accent to its stone shade
  /// over [dryingTime] after it ends.
  static const dryingTime = Duration(minutes: 10);

  Color drying(Color stone, Duration sinceEnd) {
    final t = (sinceEnd.inMilliseconds / dryingTime.inMilliseconds).clamp(0.0, 1.0);
    return Color.lerp(accent, stone, Curves.easeOut.transform(t))!;
  }

  @override
  FlowPalette copyWith() => this;

  @override
  FlowPalette lerp(FlowPalette? other, double t) {
    if (other == null) return this;
    Color l(Color a, Color b) => Color.lerp(a, b, t)!;
    return FlowPalette(
      bg: l(bg, other.bg),
      raised: l(raised, other.raised),
      recess: l(recess, other.recess),
      hairline: l(hairline, other.hairline),
      text1: l(text1, other.text1),
      text2: l(text2, other.text2),
      text3: l(text3, other.text3),
      selected: l(selected, other.selected),
      pastLight: l(pastLight, other.pastLight),
      pastModerate: l(pastModerate, other.pastModerate),
      pastHeavy: l(pastHeavy, other.pastHeavy),
      accent: l(accent, other.accent),
      accentTint: l(accentTint, other.accentTint),
      accentDeep: l(accentDeep, other.accentDeep),
      future: l(future, other.future),
      ultra: l(ultra, other.ultra),
      ultraTint: l(ultraTint, other.ultraTint),
      ultraDeep: l(ultraDeep, other.ultraDeep),
      amber: l(amber, other.amber),
      amberTint: l(amberTint, other.amberTint),
      problem: l(problem, other.problem),
      line: t < 0.5 ? line : other.line,
    );
  }
}

/// 3D face shading, one light direction app-wide (top-left).
/// Values from the spec: top +22% toward white, side −18%, grounding edge −35%.
abstract final class Faces {
  static Color top(Color c) => Color.lerp(c, const Color(0xFFFFFFFF), 0.22)!;
  static Color side(Color c) => Color.lerp(c, const Color(0xFF000000), 0.18)!;
  static Color ground(Color c) => Color.lerp(c, const Color(0xFF000000), 0.35)!;
}
