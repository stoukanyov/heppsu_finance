import 'package:dio/dio.dart';

import '../config/app_config.dart';
import '../security/secure_store.dart';
import 'api_exception.dart';

/// Тънка обвивка над `dio` с интерцептори за Bearer JWT и `X-Company-Id`.
///
/// При `401` извиква `onUnauthorized` (клиентът чисти сесията и връща към Login).
class ApiClient {
  ApiClient(this._store, {void Function()? onUnauthorized}) {
    _dio = Dio(
      BaseOptions(
        baseUrl: '${AppConfig.apiBaseUrl}/api/v1',
        connectTimeout: AppConfig.connectTimeout,
        receiveTimeout: AppConfig.receiveTimeout,
        // Не хвърляй сами на не-2xx — мапваме грешките в error_mapper.
        validateStatus: (_) => true,
      ),
    );
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _store.readToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          // company-scoped заявки: подай активната компания, ако е избрана.
          if (options.extra['requiresCompany'] != false) {
            final companyId = await _store.readCompanyId();
            if (companyId != null) {
              options.headers['X-Company-Id'] = companyId;
            }
          }
          handler.next(options);
        },
      ),
    );
  }

  final SecureStore _store;
  void Function()? onUnauthorized;
  late final Dio _dio;

  Dio get raw => _dio;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) async {
    final res = await _dio.get(path, queryParameters: query);
    return _unwrap(res);
  }

  Future<dynamic> post(
    String path, {
    Object? data,
    bool requiresCompany = true,
  }) async {
    final res = await _dio.post(
      path,
      data: data,
      options: Options(extra: {'requiresCompany': requiresCompany}),
    );
    return _unwrap(res);
  }

  Future<dynamic> patch(String path, {Object? data}) async {
    final res = await _dio.patch(path, data: data);
    return _unwrap(res);
  }

  dynamic _unwrap(Response res) {
    final code = res.statusCode ?? 0;
    if (code >= 200 && code < 300) return res.data;
    if (code == 401) onUnauthorized?.call();
    throw ApiException(code, _messageFrom(res.data, code), body: res.data);
  }

  String _messageFrom(dynamic data, int code) {
    if (data is Map && data['detail'] != null) {
      final d = data['detail'];
      if (d is String) return d;
      return d.toString();
    }
    return 'Грешка $code';
  }
}
