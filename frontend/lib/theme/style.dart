/// Flow's two looks. Both read the same data in the same places with the same
/// meaning colours; only the material differs.
enum FlowStyle {
  /// Pressed, filled solids (the original Flow).
  solid,

  /// Hairlines and isometric wireframes on a sage ground. No filled solids.
  line;

  String get label => switch (this) {
    solid => 'Solid',
    line => 'Line',
  };
}
