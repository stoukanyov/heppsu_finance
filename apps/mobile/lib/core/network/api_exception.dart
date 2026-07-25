/// Нормализирана грешка от API слоя (HTTP статус + четимо съобщение).
class ApiException implements Exception {
  const ApiException(this.statusCode, this.message, {this.body});

  /// HTTP статус (0 при мрежова/таймаут грешка без отговор).
  final int statusCode;
  final String message;
  final Object? body;

  bool get isUnauthorized => statusCode == 401;
  bool get isDuplicate => statusCode == 409;
  bool get isRetryable => statusCode == 0 || statusCode >= 500 || statusCode == 429;

  @override
  String toString() => 'ApiException($statusCode): $message';
}
