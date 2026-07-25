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
  static const _kReminders = 'reminders_enabled';

  Future<String?> readToken() => _storage.read(key: _kToken);
  Future<void> writeToken(String token) =>
      _storage.write(key: _kToken, value: token);

  Future<String?> readCompanyId() => _storage.read(key: _kCompanyId);
  Future<void> writeCompanyId(String id) =>
      _storage.write(key: _kCompanyId, value: id);

  /// Напомнянията за срокове са изключени, докато потребителят не ги включи.
  Future<bool> remindersEnabled() async =>
      await _storage.read(key: _kReminders) == '1';

  Future<void> setRemindersEnabled(bool enabled) =>
      _storage.write(key: _kReminders, value: enabled ? '1' : '0');

  /// Кеш на профила и компаниите — позволява вход без мрежа, за да работи
  /// сканирането офлайн. Пази се шифровано, като токена.
  Future<String?> readSessionCache() => _storage.read(key: _kSessionCache);

  Future<void> writeSessionCache(String json) =>
      _storage.write(key: _kSessionCache, value: json);

  static const _kSessionCache = 'session_cache';

  /// Пълно изчистване при logout (GDPR wipe на локалната сесия).
  Future<void> clear() async {
    await _storage.delete(key: _kToken);
    await _storage.delete(key: _kCompanyId);
    await _storage.delete(key: _kSessionCache);
  }
}
