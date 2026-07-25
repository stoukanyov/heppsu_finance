import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import '../../domain/models.dart';

/// Кога преди срока да звънне напомняне.
class ReminderOffset {
  const ReminderOffset(this.days, this.label);

  /// Дни преди крайния срок.
  final int days;

  /// Как да се спомене в текста на нотификацията.
  final String label;

  static const all = [
    ReminderOffset(7, 'след една седмица'),
    ReminderOffset(3, 'след 3 дни'),
    ReminderOffset(1, 'утре'),
  ];
}

/// Планира локални напомняния за сроковете към НАП.
///
/// Работи изцяло на телефона — без Firebase и без сървърни push нотификации.
/// За всеки срок се насрочват три известия: 7 дни, 3 дни и 24 часа преди.
class ReminderService {
  ReminderService([FlutterLocalNotificationsPlugin? plugin])
      : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;
  bool _ready = false;

  /// Часът, в който звъни напомнянето (местно време).
  static const _hour = 9;

  static const _channelId = 'nap_deadlines';
  static const _details = NotificationDetails(
    android: AndroidNotificationDetails(
      _channelId,
      'Срокове към НАП',
      channelDescription: 'Напомняния преди краен срок за подаване или плащане',
      importance: Importance.high,
      priority: Priority.high,
    ),
    iOS: DarwinNotificationDetails(),
  );

  Future<void> init() async {
    if (_ready) return;
    tzdata.initializeTimeZones();
    try {
      final info = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(info.identifier));
    } catch (_) {
      // Ако зоната на устройството не е разпозната — работим в софийско време,
      // защото сроковете са български.
      tz.setLocalLocation(tz.getLocation('Europe/Sofia'));
    }

    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(
          // Разрешенията се искат отделно, при включване на напомнянията.
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        ),
      ),
    );
    _ready = true;
  }

  /// Пита потребителя за разрешение. Връща `true`, ако е дадено.
  Future<bool> requestPermission() async {
    await init();
    final ios = _plugin.resolvePlatformSpecificImplementation<
        IOSFlutterLocalNotificationsPlugin>();
    if (ios != null) {
      return await ios.requestPermissions(alert: true, badge: true, sound: true) ??
          false;
    }
    final android = _plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    if (android != null) {
      // Известията се насрочват неточно (`inexactAllowWhileIdle`), затова не
      // искаме разрешение за точни аларми — за напомняне дни предварително
      // няколко часа отклонение е без значение.
      return await android.requestNotificationsPermission() ?? false;
    }
    return false;
  }

  /// Пренасрочва всички напомняния за подадения списък срокове.
  ///
  /// Първо изчиства старите, за да не остават известия за срокове, които вече
  /// са отпаднали или са се преместили.
  Future<int> reschedule(List<Deadline> deadlines) async {
    await init();
    await _plugin.cancelAll();

    var scheduled = 0;
    for (final deadline in deadlines) {
      for (final offset in ReminderOffset.all) {
        final when = _fireTime(deadline.dueDate, offset.days);
        if (when == null) continue; // моментът вече е минал

        try {
          await _plugin.zonedSchedule(
            id: _notificationId(deadline.key, offset.days),
            scheduledDate: when,
            notificationDetails: _details,
            androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
            title: _title(deadline, offset),
            body: _body(deadline),
            payload: deadline.key,
          );
          scheduled++;
        } catch (e) {
          // Едно неуспешно известие не бива да спира останалите.
          debugPrint('Напомнянето за ${deadline.key} не беше насрочено: $e');
        }
      }
    }
    return scheduled;
  }

  Future<void> cancelAll() async {
    await init();
    await _plugin.cancelAll();
  }

  /// Брой реално насрочени известия — за показване в настройките.
  Future<int> pendingCount() async {
    await init();
    return (await _plugin.pendingNotificationRequests()).length;
  }

  /// Моментът на известието: в 9:00 сутринта, N дни преди срока.
  /// Връща `null`, ако този момент вече е минал.
  tz.TZDateTime? _fireTime(DateTime dueDate, int daysBefore) {
    final target = dueDate.subtract(Duration(days: daysBefore));
    final when = tz.TZDateTime(
      tz.local,
      target.year,
      target.month,
      target.day,
      _hour,
    );
    return when.isAfter(tz.TZDateTime.now(tz.local)) ? when : null;
  }

  /// Стабилен идентификатор: един и същ срок + отместване → същото известие,
  /// така че пренасрочването не създава дубликати.
  int _notificationId(String key, int daysBefore) =>
      Object.hash(key, daysBefore) & 0x7fffffff;

  String _title(Deadline deadline, ReminderOffset offset) =>
      '${deadline.title} — ${offset.label}';

  String _body(Deadline deadline) {
    final date = '${deadline.dueDate.day.toString().padLeft(2, '0')}.'
        '${deadline.dueDate.month.toString().padLeft(2, '0')}.'
        '${deadline.dueDate.year}';
    final period =
        deadline.periodLabel.isEmpty ? '' : ' за ${deadline.periodLabel}';
    return 'Краен срок $date$period · ${deadline.authority}';
  }
}
