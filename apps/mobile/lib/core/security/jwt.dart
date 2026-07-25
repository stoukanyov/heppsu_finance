import 'dart:convert';

/// Чете `exp` от JWT **без да проверява подписа**.
///
/// Използва се само за да решим дали изобщо си струва да пуснем потребителя
/// в приложението офлайн. Истинската проверка винаги е на сървъра — тук
/// подписът не може да се валидира и не бива да се разчита на него.
DateTime? jwtExpiry(String token) {
  try {
    final parts = token.split('.');
    if (parts.length != 3) return null;

    final payload = json.decode(
      utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
    );
    final exp = payload is Map ? payload['exp'] : null;
    if (exp is! num) return null;

    return DateTime.fromMillisecondsSinceEpoch(exp.toInt() * 1000, isUtc: true);
  } catch (_) {
    return null;
  }
}

/// Изтекъл ли е токенът (с малък запас, за да не тръгнем със заявка,
/// която ще върне 401 след секунда).
bool isJwtExpired(String token, {Duration leeway = const Duration(minutes: 1)}) {
  final exp = jwtExpiry(token);
  if (exp == null) return false; // не можем да преценим — оставяме на сървъра
  return DateTime.now().toUtc().add(leeway).isAfter(exp);
}
