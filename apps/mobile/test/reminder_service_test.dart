import 'package:flutter_test/flutter_test.dart';
import 'package:heppsu_finance/core/notifications/reminder_service.dart';
import 'package:heppsu_finance/domain/models.dart';

void main() {
  group('ReminderOffset', () {
    test('напомня 7 дни, 3 дни и 24 часа преди срока', () {
      expect(ReminderOffset.all.map((o) => o.days).toList(), [7, 3, 1]);
    });

    test('всяко отместване има текст за нотификацията', () {
      for (final o in ReminderOffset.all) {
        expect(o.label, isNotEmpty);
      }
    });
  });

  group('Deadline', () {
    Deadline make({required int daysRemaining}) => Deadline.fromJson({
          'key': 'vat-return:2026-07',
          'title': 'Справка-декларация по ЗДДС',
          'description': 'Подаване на декларацията и дневниците.',
          'due_date': '2026-08-14',
          'original_due_date': '2026-08-14',
          'moved_for_holiday': false,
          'period_label': 'юли 2026',
          'category': 'VAT',
          'authority': 'НАП',
          'conditional': false,
          'conditional_note': null,
          'days_remaining': daysRemaining,
        });

    test('парсва отговора на /deadlines/upcoming', () {
      final d = make(daysRemaining: 20);
      expect(d.key, 'vat-return:2026-07');
      expect(d.dueDate, DateTime(2026, 8, 14));
      expect(d.authority, 'НАП');
      expect(d.conditional, isFalse);
    });

    test('разпознава спешност по оставащи дни', () {
      expect(make(daysRemaining: -1).isOverdue, isTrue);
      expect(make(daysRemaining: 0).isUrgent, isTrue);
      expect(make(daysRemaining: 3).isUrgent, isTrue);
      expect(make(daysRemaining: 4).isUrgent, isFalse);
      expect(make(daysRemaining: 7).isSoon, isTrue);
      expect(make(daysRemaining: 30).isSoon, isFalse);
      expect(make(daysRemaining: 30).isOverdue, isFalse);
    });

    test('условен срок носи пояснението си', () {
      final d = Deadline.fromJson({
        'key': 'vies:2026-07',
        'title': 'VIES декларация',
        'description': 'Подаване при вътреобщностни доставки.',
        'due_date': '2026-08-14',
        'period_label': 'юли 2026',
        'category': 'VAT',
        'authority': 'НАП',
        'conditional': true,
        'conditional_note': 'ако има ВОД за периода',
        'days_remaining': 20,
      });

      expect(d.conditional, isTrue);
      expect(d.conditionalNote, 'ако има ВОД за периода');
    });

    test('срокът е реалната дата, а не календарната', () {
      // 25.07.2026 е събота → реалният срок е понеделник 27.07.
      final d = Deadline.fromJson({
        'key': 'payroll-declarations:2026-06',
        'title': 'Декларации образец 1 и образец 6',
        'description': '',
        'due_date': '2026-07-27',
        'original_due_date': '2026-07-25',
        'moved_for_holiday': true,
        'period_label': 'юни 2026',
        'category': 'PAYROLL',
        'authority': 'НАП',
        'conditional': true,
        'days_remaining': 2,
      });

      expect(d.dueDate, DateTime(2026, 7, 27), reason: 'реалната дата');
      expect(d.originalDueDate, DateTime(2026, 7, 25), reason: 'календарната');
      expect(d.movedForHoliday, isTrue);

      // Трите напомняния се броят от преместената дата, не от календарната.
      for (final o in ReminderOffset.all) {
        final fires = d.dueDate.subtract(Duration(days: o.days));
        final wrong = d.originalDueDate!.subtract(Duration(days: o.days));
        expect(fires.isAfter(wrong), isTrue);
      }
      expect(
        d.dueDate.subtract(const Duration(days: 1)),
        DateTime(2026, 7, 26),
        reason: 'напомнянето „утре" е в деня преди реалния срок',
      );
    });

    test('липсващи незадължителни полета не чупят парсването', () {
      final d = Deadline.fromJson({
        'key': 'x',
        'title': 'Нещо',
        'description': '',
        'due_date': '2026-09-30',
        'period_label': '',
        'category': 'ANNUAL_REPORT',
        'days_remaining': 60,
      });

      expect(d.authority, 'НАП', reason: 'разумно подразбиране');
      expect(d.conditional, isFalse);
      expect(d.movedForHoliday, isFalse);
    });
  });
}
