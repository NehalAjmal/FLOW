import '../../core/json.dart';

/// Coarse app category. Window titles never leave the device (doc §2.4).
enum AppCategory implements WireEnum {
  editor('editor'),
  terminal('terminal'),
  browser('browser'),
  chat('chat'),
  docs('docs'),
  meeting('meeting'),
  other('other');

  const AppCategory(this.wire);
  @override
  final String wire;
}

enum AgentConnection { disconnected, unpaired, connected }

class AgentStatus {
  const AgentStatus({
    required this.connection,
    this.behaviorOn = false,
    this.cameraOn = false,
    this.category,
    this.agentVersion,
    this.sessionId,
  });

  final AgentConnection connection;
  final bool behaviorOn;
  final bool cameraOn;
  final AppCategory? category;
  final String? agentVersion;
  final String? sessionId;

  static const offline = AgentStatus(connection: AgentConnection.disconnected);

  factory AgentStatus.fromJson(Json j) => AgentStatus(
    connection: boolOr(j['paired'], false)
        ? AgentConnection.connected
        : AgentConnection.unpaired,
    behaviorOn: boolOr(j['behavior_on'], false),
    cameraOn: boolOr(j['camera_on'], false),
    category: enumFromWireOrNull(AppCategory.values, j['app_category']),
    agentVersion: str(j['version']),
    sessionId: str(j['session_id']),
  );
}

/// Live counts for the "expand live signals" panel. Local only.
class LiveSignals {
  const LiveSignals({
    required this.keysPerMin,
    required this.switchesPer5Min,
    required this.idleSec,
    this.eyeScore,
    this.measurement,
  });
  final int keysPerMin;
  final int switchesPer5Min;
  final int idleSec;
  final double? eyeScore;
  final Json? measurement;

  factory LiveSignals.fromJson(Json j) => LiveSignals(
    keysPerMin: intOrNull(j['keys_per_min']) ?? 0,
    switchesPer5Min: intOrNull(j['switches_per_5min']) ?? 0,
    idleSec: intOrNull(j['idle_sec']) ?? 0,
    eyeScore: dblOrNull(j['eye_score']),
    measurement: _measurement(j),
  );
}

sealed class AgentEvent {
  const AgentEvent();

  static AgentEvent? fromJson(Json j) => switch (str(j['type'])) {
    'status' => AgentStatusEvent(AgentStatus.fromJson(j)),
    'signals' => AgentSignalsEvent(LiveSignals.fromJson(j)),
    'resumption' => AgentResumptionEvent(
      breakId: reqStr(j, 'break_id'),
      secondsToFirstEdit: intOrNull(j['seconds_to_first_edit']) ?? 0,
    ),
    _ => null,
  };
}

class AgentStatusEvent extends AgentEvent {
  const AgentStatusEvent(this.status);
  final AgentStatus status;
}

class AgentSignalsEvent extends AgentEvent {
  const AgentSignalsEvent(this.signals);
  final LiveSignals signals;
}

class AgentResumptionEvent extends AgentEvent {
  const AgentResumptionEvent({
    required this.breakId,
    required this.secondsToFirstEdit,
  });
  final String breakId;
  final int secondsToFirstEdit;
}

// Only forward explicitly allowlisted, valid measurements from the agent.
Json? _measurement(Json j) {
  final session = j['session_id'];
  final timestamp = j['timestamp'];
  if (session is! String ||
      session.isEmpty ||
      timestamp is! String ||
      DateTime.tryParse(timestamp) == null) {
    return null;
  }
  final result = <String, dynamic>{
    'session_id': session,
    'timestamp': timestamp,
  };
  for (final key in ['keystroke_count', 'window_switches', 'idle_seconds']) {
    final value = j[key];
    if (value is! int || value < 0) return null;
    result[key] = value;
  }
  const categories = {
    'development',
    'terminal',
    'browser',
    'productivity',
    'communication',
    'entertainment',
    'design',
    'system',
    'unknown',
  };
  final category = j['app_category'];
  result['app_category'] = categories.contains(category) ? category : 'unknown';
  final camera = j['camera'];
  final clean = <String, dynamic>{};
  if (camera is Map) {
    for (final key in [
      'fatigue_score',
      'ear',
      'heart_rate_bpm',
      'hr_confidence',
    ]) {
      final value = camera[key];
      if (value is num &&
          value.isFinite &&
          value >= 0 &&
          value <= (key == 'heart_rate_bpm' ? 250 : 1) &&
          (key != 'heart_rate_bpm' || value > 0)) {
        clean[key] = value;
      }
    }
  }
  result['camera'] = clean.isEmpty ? null : clean;
  return result;
}
