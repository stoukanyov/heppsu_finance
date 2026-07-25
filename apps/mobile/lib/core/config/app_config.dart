import 'package:flutter/foundation.dart';

/// Конфигурация на средата. Base URL се подава при билд през
/// `--dart-define=API_BASE_URL=...`; иначе разумни локални стойности.
class AppConfig {
  const AppConfig._();

  /// Базов URL на AI Finance OS API (без завършващ слаш).
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: _defaultBaseUrl,
  );

  /// Web/десктоп dev → localhost; Android емулатор ползва 10.0.2.2.
  static const String _defaultBaseUrl = kIsWeb
      ? 'http://localhost:8000'
      : 'http://10.0.2.2:8000';

  static const Duration connectTimeout = Duration(seconds: 15);
  static const Duration receiveTimeout = Duration(seconds: 60);

  /// Праг на увереност, под който документът иска ръчна проверка.
  static const double lowConfidenceThreshold = 0.75;
}
