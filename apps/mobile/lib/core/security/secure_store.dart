import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Сигурно съхранение на JWT и избраната компания (Keychain / Keystore).
class SecureStore {
  SecureStore([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;

  static const _kToken = 'jwt_access_token';
  static const _kCompanyId = 'active_company_id';

  Future<String?> readToken() => _storage.read(key: _kToken);
  Future<void> writeToken(String token) =>
      _storage.write(key: _kToken, value: token);

  Future<String?> readCompanyId() => _storage.read(key: _kCompanyId);
  Future<void> writeCompanyId(String id) =>
      _storage.write(key: _kCompanyId, value: id);

  /// Пълно изчистване при logout (GDPR wipe на локалната сесия).
  Future<void> clear() async {
    await _storage.delete(key: _kToken);
    await _storage.delete(key: _kCompanyId);
  }
}
