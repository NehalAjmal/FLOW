import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/models/auth.dart';

/// Where access/refresh tokens live. Never SharedPreferences: on Windows that
/// is a plaintext JSON file in AppData.
abstract interface class TokenStore {
  Future<TokenPair?> read();
  Future<void> write(TokenPair tokens);
  Future<void> clear();
}

/// OS keychain (macOS Keychain, Windows Credential Manager / DPAPI).
class SecureTokenStore implements TokenStore {
  /// macOS: the legacy keychain, not the data-protection one. The
  /// data-protection keychain needs the `keychain-access-groups` entitlement
  /// (Keychain Sharing), which demands a development certificate and a
  /// provisioning profile: without one the app does not even build
  /// ("Runner has entitlements that require signing with a development
  /// certificate"). The legacy keychain is still the user's encrypted login
  /// keychain; Flow shares nothing with other apps, so nothing is lost.
  /// The option is ignored on other platforms.
  SecureTokenStore([FlutterSecureStorage? storage])
    : _s = storage ?? const FlutterSecureStorage(mOptions: MacOsOptions(usesDataProtectionKeychain: false));

  final FlutterSecureStorage _s;
  static const _access = 'flow.access_token';
  static const _refresh = 'flow.refresh_token';

  @override
  Future<TokenPair?> read() async {
    final a = await _s.read(key: _access);
    final r = await _s.read(key: _refresh);
    if (a == null || r == null) return null;
    return TokenPair(accessToken: a, refreshToken: r);
  }

  @override
  Future<void> write(TokenPair tokens) async {
    await _s.write(key: _access, value: tokens.accessToken);
    await _s.write(key: _refresh, value: tokens.refreshToken);
  }

  @override
  Future<void> clear() async {
    await _s.delete(key: _access);
    await _s.delete(key: _refresh);
  }
}

/// Tests and mock mode.
class MemoryTokenStore implements TokenStore {
  MemoryTokenStore([this._tokens]);
  TokenPair? _tokens;

  @override
  Future<TokenPair?> read() async => _tokens;

  @override
  Future<void> write(TokenPair tokens) async => _tokens = tokens;

  @override
  Future<void> clear() async => _tokens = null;
}
