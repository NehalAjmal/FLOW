import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_connector.dart';
import '../api/models/agent.dart';
import '../api/models/consent.dart';
import '../api/real/real_agent.dart';
import '../api/real/real_session.dart';
import 'account_controllers.dart';
import 'auth_controller.dart';
import 'session_controller.dart';

final sensorBridgeProvider = Provider<void>((ref) {
  final agent = ref.watch(localAgentApiProvider);
  final api = ref.watch(sessionApiProvider);
  if (agent is! RealLocalAgentApi || api is! RealSessionApi) return;
  final user = ref.watch(currentUserIdProvider);
  if (user == null) return;
  var disposed = false;
  var status = AgentStatus.offline;
  var busy = false;
  var dirty = false;
  var sending = false;
  DateTime? lastTimestamp;
  String? lastSession;

  String? desiredSession() {
    if (disposed ||
        ref.read(currentUserIdProvider) != user ||
        ref.read(sensorLogoutProvider) ||
        ref.read(sensorPrivacyHoldProvider).contains(ConsentScope.behavior)) {
      return null;
    }
    final consent = ref.read(consentProvider);
    final live = ref.read(liveSessionProvider);
    if (consent.isLoading ||
        consent.hasError ||
        live.isLoading ||
        live.hasError) {
      return null;
    }
    if (consent.value?.granted(ConsentScope.behavior) != true) return null;
    final session = live.value?.session;
    return session == null || session.paused ? null : session.sessionId;
  }

  bool cameraAllowed() {
    if (desiredSession() == null ||
        ref.read(sensorPrivacyHoldProvider).contains(ConsentScope.camera)) {
      return false;
    }
    final settings = ref.read(settingsProvider);
    return !settings.isLoading &&
        !settings.hasError &&
        settings.value?.cameraEnabled == true &&
        ref.read(consentProvider).value?.granted(ConsentScope.camera) == true;
  }

  Future<void> reconcile() async {
    dirty = true;
    if (busy || disposed) return;
    busy = true;
    try {
      while (dirty && !disposed) {
        dirty = false;
        if (status.connection != AgentConnection.connected) continue;
        final id = desiredSession();
        if (id == null) {
          if (status.behaviorOn || status.cameraOn) await agent.stopSession();
        } else if (status.sessionId != id || !status.behaviorOn) {
          await agent.startSession(id);
        } else if (status.cameraOn != cameraAllowed()) {
          await agent.setCamera(cameraAllowed());
        }
      }
    } catch (_) {
      await agent.disconnect();
    } finally {
      busy = false;
    }
  }

  final sub = agent.events().listen((event) {
    if (disposed) return;
    if (event is AgentStatusEvent) {
      status = event.status;
      unawaited(reconcile());
    } else if (event is AgentSignalsEvent) {
      final id = desiredSession();
      final data = event.signals.measurement;
      if (id == null ||
          status.sessionId != id ||
          !status.behaviorOn ||
          status.connection != AgentConnection.connected ||
          sending ||
          data == null ||
          data['session_id'] != id) {
        return;
      }
      final timestamp = DateTime.parse(data['timestamp'] as String).toUtc();
      if (lastSession == id &&
          lastTimestamp != null &&
          !timestamp.isAfter(lastTimestamp!)) {
        return;
      }
      lastSession = id;
      lastTimestamp = timestamp;
      sending = true;
      unawaited(
        api
            .submitSignals(
              event.signals,
              sessionId: id,
              cameraAllowed: cameraAllowed() && status.cameraOn,
            )
            .then<void>((_) {}, onError: (Object _) {})
            .whenComplete(() => sending = false),
      );
    }
  });
  ref.listen(sensorLogoutProvider, (_, _) => unawaited(reconcile()));
  ref.listen(sensorPrivacyHoldProvider, (_, _) => unawaited(reconcile()));
  ref.listen(liveSessionProvider, (_, _) => unawaited(reconcile()));
  ref.listen(consentProvider, (_, _) => unawaited(reconcile()));
  ref.listen(settingsProvider, (_, _) => unawaited(reconcile()));
  ref.onDispose(() {
    disposed = true;
    unawaited(sub.cancel());
    unawaited(agent.disconnect());
  });
});
