import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../../core/endpoint_policy.dart';
import '../../core/json.dart';
import '../contracts/agent_api.dart';
import '../models/agent.dart';

class RealLocalAgentApi implements LocalAgentApi {
  RealLocalAgentApi(this.url);
  final String url;
  WebSocketChannel? _ch;
  Future<WebSocketChannel?>? _opening;
  final _events = StreamController<AgentEvent>.broadcast();
  Future<void> _queue = Future.value();
  Completer<AgentStatus>? _reply;
  int _generation = 0;

  Future<WebSocketChannel?> _connect() async {
    if (_ch != null) return _ch;
    final pending = _opening;
    if (pending != null) return pending;
    final opening = _open(_generation);
    _opening = opening;
    try {
      return await opening;
    } finally {
      if (identical(_opening, opening)) _opening = null;
    }
  }

  Future<WebSocketChannel?> _open(int generation) async {
    WebSocketChannel? candidate;
    try {
      final target = Uri.parse(url);
      if (EndpointPolicy.agentProblem(target) != null) return null;
      final ch = WebSocketChannel.connect(target);
      candidate = ch;
      await ch.ready.timeout(const Duration(seconds: 2));
      if (generation != _generation) {
        await ch.sink.close();
        return null;
      }
      // Consume the unsolicited initial status before sending any commands.
      final initial = Completer<AgentStatus>();
      _ch = ch;
      ch.stream.listen(
        (raw) {
          if (!identical(_ch, ch)) return;
          try {
            final event = AgentEvent.fromJson(
              asJson(jsonDecode(raw.toString())),
            );
            if (event is AgentStatusEvent) {
              if (!initial.isCompleted) {
                initial.complete(event.status);
              } else {
                final reply = _reply;
                if (reply != null && !reply.isCompleted) {
                  reply.complete(event.status);
                }
              }
            }
            if (event != null) _events.add(event);
          } on FormatException {
            /* Ignore malformed frames. */
          }
        },
        onDone: () => _closed(ch),
        onError: (Object _) => _closed(ch),
      );
      await initial.future.timeout(const Duration(seconds: 3));
      return identical(_ch, ch) ? ch : null;
    } catch (_) {
      if (candidate != null) {
        _closed(candidate);
        unawaited(candidate.sink.close());
      }
      return null;
    }
  }

  void _closed(WebSocketChannel ch) {
    if (!identical(_ch, ch)) return;
    _ch = null;
    final reply = _reply;
    if (reply != null && !reply.isCompleted) {
      reply.complete(AgentStatus.offline);
    }
    _events.add(const AgentStatusEvent(AgentStatus.offline));
  }

  Future<AgentStatus> _command(Json message) {
    final generation = _generation;
    final operation = _queue.then((_) async {
      if (generation != _generation) throw StateError('Agent disconnected.');
      final ch = await _connect();
      if (ch == null || generation != _generation) {
        throw StateError('Flow agent unavailable.');
      }
      final reply = Completer<AgentStatus>();
      _reply = reply;
      try {
        ch.sink.add(jsonEncode(message));
        final status = await reply.future.timeout(const Duration(seconds: 8));
        if (status.connection == AgentConnection.disconnected) {
          throw StateError('Agent rejected command or disconnected.');
        }
        return status;
      } catch (_) {
        _closed(ch);
        unawaited(ch.sink.close());
        rethrow;
      } finally {
        _reply = null;
      }
    });
    _queue = operation.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return operation;
  }

  @override
  Stream<AgentEvent> events() {
    unawaited(_connect());
    return _events.stream;
  }

  @override
  Future<AgentStatus> status() async {
    try {
      return await _command({'type': 'get_status'});
    } catch (_) {
      return AgentStatus.offline;
    }
  }

  @override
  Future<void> pair(String code) async {
    final status = await _command({'type': 'pair', 'code': code});
    if (status.connection != AgentConnection.connected) {
      throw StateError('Pairing failed.');
    }
  }

  @override
  Future<void> setCamera(bool on) async {
    final status = await _command({'type': 'set_camera', 'on': on});
    if (status.cameraOn != on) throw StateError('Camera command rejected.');
  }

  @override
  Future<void> watchResumption(String breakId) async {
    await _command({'type': 'watch_resumption', 'break_id': breakId});
  }

  Future<void> startSession(String sessionId) async {
    final status = await _command({
      'type': 'start_session',
      'session_id': sessionId,
    });
    if (!status.behaviorOn || status.sessionId != sessionId) {
      throw StateError('Session tracking rejected.');
    }
  }

  Future<void> stopSession() async {
    final status = await _command({'type': 'stop_session'});
    if (status.behaviorOn || status.cameraOn) {
      throw StateError('Sensor stop rejected.');
    }
  }

  Future<void> disconnect() async {
    _generation++;
    final ch = _ch;
    if (ch != null) {
      _closed(ch);
      await ch.sink.close();
    }
  }
}
