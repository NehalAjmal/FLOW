import 'package:flutter_test/flutter_test.dart';

import 'package:flow/api/models/agent.dart';

Map<String, dynamic> validSignal() => {
  'type': 'signals',
  'session_id': 'session-123',
  'timestamp': DateTime.now().toUtc().toIso8601String(),
  'keystroke_count': 25,
  'window_switches': 3,
  'idle_seconds': 4,
  'app_category': 'development',
  'camera': null,
};

void main() {
  group('Local sensor measurements', () {
    test('accepts valid behavioral measurements', () {
      final data = LiveSignals.fromJson(validSignal()).measurement!;

      expect(data['session_id'], 'session-123');
      expect(data['keystroke_count'], 25);
      expect(data['window_switches'], 3);
      expect(data['idle_seconds'], 4);
      expect(data['app_category'], 'development');
    });

    test('missing camera remains null', () {
      final data = LiveSignals.fromJson(validSignal()).measurement!;
      expect(data['camera'], isNull);
    });

    test('rejects missing session identifier', () {
      final input = validSignal()..remove('session_id');
      expect(LiveSignals.fromJson(input).measurement, isNull);
    });

    test('rejects empty session identifier', () {
      final input = validSignal()..['session_id'] = '';
      expect(LiveSignals.fromJson(input).measurement, isNull);
    });

    test('rejects invalid timestamp', () {
      final input = validSignal()..['timestamp'] = 'invalid';
      expect(LiveSignals.fromJson(input).measurement, isNull);
    });

    for (final field in [
      'keystroke_count',
      'window_switches',
      'idle_seconds',
    ]) {
      test('rejects negative $field', () {
        final input = validSignal()..[field] = -1;
        expect(LiveSignals.fromJson(input).measurement, isNull);
      });

      test('rejects missing $field', () {
        final input = validSignal()..remove(field);
        expect(LiveSignals.fromJson(input).measurement, isNull);
      });

      test('rejects non-integer $field', () {
        final input = validSignal()..[field] = 1.5;
        expect(LiveSignals.fromJson(input).measurement, isNull);
      });
    }

    test('preserves genuine zero measurements', () {
      final input = validSignal()
        ..['keystroke_count'] = 0
        ..['window_switches'] = 0
        ..['idle_seconds'] = 0;

      final data = LiveSignals.fromJson(input).measurement!;
      expect(data['keystroke_count'], 0);
      expect(data['window_switches'], 0);
      expect(data['idle_seconds'], 0);
    });

    test('normalizes unknown application categories', () {
      final input = validSignal()..['app_category'] = 'private document title';

      final data = LiveSignals.fromJson(input).measurement!;
      expect(data['app_category'], 'unknown');
    });

    test('excludes private raw activity information', () {
      final input = validSignal()
        ..['window_title'] = 'Private document'
        ..['raw_keys'] = 'password'
        ..['process_name'] = 'private.exe';

      final data = LiveSignals.fromJson(input).measurement!;

      expect(data.containsKey('window_title'), isFalse);
      expect(data.containsKey('raw_keys'), isFalse);
      expect(data.containsKey('process_name'), isFalse);
    });

    test('accepts valid camera measurements', () {
      final input = validSignal()
        ..['camera'] = {
          'fatigue_score': 0.42,
          'ear': 0.28,
          'heart_rate_bpm': 76.0,
          'hr_confidence': 0.81,
        };

      final data = LiveSignals.fromJson(input).measurement!;
      final camera = data['camera'] as Map;

      expect(camera['fatigue_score'], 0.42);
      expect(camera['ear'], 0.28);
      expect(camera['heart_rate_bpm'], 76.0);
      expect(camera['hr_confidence'], 0.81);
    });

    test('rejects invalid camera measurements', () {
      final input = validSignal()
        ..['camera'] = {
          'fatigue_score': double.nan,
          'ear': -0.5,
          'heart_rate_bpm': 300,
          'hr_confidence': double.infinity,
        };

      expect(LiveSignals.fromJson(input).measurement!['camera'], isNull);
    });

    test('excludes raw camera information', () {
      final input = validSignal()
        ..['camera'] = {
          'fatigue_score': 0.4,
          'frame': 'raw image',
          'landmarks': [1, 2, 3],
        };

      final camera = LiveSignals.fromJson(input).measurement!['camera'] as Map;

      expect(camera.length, 1);
      expect(camera['fatigue_score'], 0.4);
    });
  });

  group('Agent protocol', () {
    test('recognizes paired agent and active session', () {
      final event = AgentEvent.fromJson({
        'type': 'status',
        'paired': true,
        'behavior_on': true,
        'camera_on': false,
        'session_id': 'session-123',
      }) as AgentStatusEvent;

      expect(event.status.connection, AgentConnection.connected);
      expect(event.status.behaviorOn, isTrue);
      expect(event.status.cameraOn, isFalse);
      expect(event.status.sessionId, 'session-123');
    });

    test('recognizes unpaired agent', () {
      final status = AgentStatus.fromJson({'paired': false});
      expect(status.connection, AgentConnection.unpaired);
    });

    test('offline agent has disabled sensors', () {
      expect(AgentStatus.offline.behaviorOn, isFalse);
      expect(AgentStatus.offline.cameraOn, isFalse);
      expect(AgentStatus.offline.sessionId, isNull);
    });

    test('recognizes signal events', () {
      expect(AgentEvent.fromJson(validSignal()), isA<AgentSignalsEvent>());
    });

    test('ignores unknown protocol events', () {
      expect(AgentEvent.fromJson({'type': 'unknown'}), isNull);
    });

    test('preserves break resumption event parsing', () {
      final event = AgentEvent.fromJson({
        'type': 'resumption',
        'break_id': 'break-123',
        'seconds_to_first_edit': 12,
      }) as AgentResumptionEvent;

      expect(event.breakId, 'break-123');
      expect(event.secondsToFirstEdit, 12);
    });
  });
}
