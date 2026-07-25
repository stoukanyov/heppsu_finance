import 'package:flutter_test/flutter_test.dart';
import 'package:heppsu_finance/domain/models.dart';

void main() {
  group('Document', () {
    test('парсва отговора на /documents/scan', () {
      final doc = Document.fromJson({
        'id': 'd1',
        'original_filename': 'scan.jpg',
        'content_type': 'image/jpeg',
        'size_bytes': 1024,
        'sha256': 'abc',
        'doc_type': 'INVOICE_PURCHASE',
        'source': 'MOBILE',
        'status': 'RECOGNIZED',
        'notes': null,
      });

      expect(doc.status, DocStatus.recognized);
      expect(doc.status.label, 'Разпознат');
      expect(doc.docType, 'INVOICE_PURCHASE');
    });

    test('непознат статус не хвърля', () {
      final doc = Document.fromJson({
        'id': 'd1',
        'status': 'SOMETHING_NEW',
      });
      expect(doc.status, DocStatus.unknown);
    });

    test('статусите се сериализират обратно за backend', () {
      expect(DocStatus.needsReview.wire, 'NEEDS_REVIEW');
      expect(DocStatus.posted.wire, 'POSTED');
    });
  });

  group('Extraction', () {
    test('чете вложената структура fields + field_confidence', () {
      final e = Extraction.fromJson({
        'id': 'e1',
        'document_id': 'd1',
        'model': 'stub',
        'data': {
          'fields': {
            'issuer': 'Клауд Сървисис ЕООД',
            'issuer_vat_number': 'BG203456789',
            'document_number': '0000004521',
            'document_date': '2026-07-20',
            'tax_base': 1000.0,
            'vat_amount': 200.0,
            'total': 1200.0,
            'currency': 'EUR',
            'recipient': null,
            'iban': null,
          },
          'field_confidence': {'total': 0.85, 'vat_amount': 0.6},
          'overall_confidence': 0.62,
          'notes': 'Разпознато от stub клиент.',
        },
      });

      final fields = e.displayFields;
      expect(e.confidence, 0.62);
      expect(e.notes, isNotNull);
      expect(fields.first.label, 'Доставчик');
      expect(fields.first.value, 'Клауд Сървисис ЕООД');

      // null полетата не се показват
      expect(fields.any((f) => f.label == 'IBAN'), isFalse);

      final vat = fields.firstWhere((f) => f.label == 'ДДС');
      expect(vat.confidence, 0.6);
      expect(vat.isUncertain, isTrue, reason: '0.6 < 0.75');

      final total = fields.firstWhere((f) => f.label == 'Общо');
      expect(total.isUncertain, isFalse, reason: '0.85 >= 0.75');
    });

    test('понася плосък отговор с алтернативни имена на полета', () {
      final e = Extraction.fromJson({
        'id': 'e1',
        'document_id': 'd1',
        'model': 'claude-opus-5',
        'data': {
          'supplier_name': 'Доставчик ЕООД',
          'invoice_number': 'F-1',
          'net_amount': '1000.00',
          'total_amount': '1200.00',
        },
      });

      final labels = e.displayFields.map((f) => f.label).toList();
      expect(labels, contains('Доставчик'));
      expect(labels, contains('Документ №'));
      expect(labels, contains('Данъчна основа'));
    });

    test('празни данни не хвърлят', () {
      final e = Extraction.fromJson({
        'id': 'e1',
        'document_id': 'd1',
        'model': 'stub',
        'data': {},
      });

      expect(e.displayFields, isEmpty);
      expect(e.confidence, isNull);
    });
  });

  group('PostingProposal', () {
    test('парсва предложена статия с редове', () {
      final scan = ScanResult.fromJson({
        'document': {'id': 'd1', 'status': 'PROPOSED'},
        'extraction': {
          'id': 'e1',
          'document_id': 'd1',
          'model': 'claude-opus-5',
          'data': {'total_amount': '1200.00', 'overall_confidence': 0.92},
        },
        'posting': {
          'confidence': 0.92,
          'rationale': 'Фактура за покупка.',
          'warnings': ['ДДС кодът е предположен'],
          'entry': {
            'id': 'je1',
            'status': 'DRAFT',
            'currency': 'EUR',
            'document_date': '2026-07-20',
            'total_debit': '1200.00',
            'total_credit': '1200.00',
            'lines': [
              {'line_no': 1, 'account_id': 'a1', 'debit': '1000.00', 'credit': '0.00'},
              {'line_no': 2, 'account_id': 'a2', 'debit': '200.00', 'credit': '0.00'},
              {'line_no': 3, 'account_id': 'a3', 'debit': '0.00', 'credit': '1200.00'},
            ],
          },
        },
      });

      final entry = scan.posting!.entry!;
      expect(entry.isDraft, isTrue);
      expect(entry.lines, hasLength(3));
      expect(entry.totalDebit, 1200.0);
      expect(entry.totalDebit, entry.totalCredit);
      expect(scan.posting!.warnings, hasLength(1));
      expect(scan.extraction.confidence, 0.92);
    });

    test('scan без предложение остава валиден', () {
      final scan = ScanResult.fromJson({
        'document': {'id': 'd1', 'status': 'NEEDS_REVIEW'},
        'extraction': {
          'id': 'e1',
          'document_id': 'd1',
          'model': 'stub',
          'data': {},
        },
      });

      expect(scan.posting, isNull);
      expect(scan.document.status, DocStatus.needsReview);
    });
  });

  group('VatPeriodSummary', () {
    test('парсва период и Decimal-и подадени като string', () {
      final p = VatPeriodSummary.fromJson({
        'period_id': 'p1',
        'code': '2026-07',
        'start_date': '2026-07-01',
        'end_date': '2026-07-31',
        'output_vat': '2000.00',
        'input_vat': '500.00',
        'net_payable': '1500.00',
        'status': 'READY',
        'closed_at': null,
      });

      expect(p.status, VatPeriodStatus.ready);
      expect(p.status.label, 'За одобрение');
      expect(p.netPayable, 1500.0);
    });
  });

  group('Отчети', () {
    test('P&L чете секциите и предпочита групите по НСС статии', () {
      final pnl = ProfitAndLoss.fromJson({
        'revenue': {
          'title': 'Приходи',
          'lines': [
            {'account_id': 'a1', 'code': '703', 'name': 'Приходи от услуги', 'amount': '70000.00'},
          ],
          'total': '70000.00',
        },
        'expenses': {
          'title': 'Разходи',
          'lines': [
            {'account_id': 'a2', 'code': '602', 'name': 'Външни услуги', 'amount': '24500.00'},
          ],
          'total': '24500.00',
        },
        'revenue_groups': [
          {'title': 'Нетни приходи от продажби', 'amount': '70000.00'},
        ],
        'expense_groups': [
          {'title': 'Разходи за външни услуги', 'amount': '24500.00'},
        ],
        'net_profit': '45500.00',
      });

      expect(pnl.revenue, 70000.0);
      expect(pnl.expenses, 24500.0);
      expect(pnl.profit, 45500.0);
      expect(pnl.revenueLines.single.label, 'Нетни приходи от продажби');
    });

    test('P&L пада към редовете по сметки, ако няма групи', () {
      final pnl = ProfitAndLoss.fromJson({
        'revenue': {
          'lines': [
            {'code': '703', 'name': 'Приходи от услуги', 'amount': '100.00'},
          ],
          'total': '100.00',
        },
        'expenses': {'lines': [], 'total': '0.00'},
      });

      expect(pnl.revenueLines.single.label, '703 · Приходи от услуги');
      expect(pnl.profit, 100.0, reason: 'резултатът се смята, ако липсва');
    });

    test('StoreAnalytics чете NamedTotal разбивките', () {
      final s = StoreAnalytics.fromJson({
        'total_units': 1200,
        'total_proceeds': '8000.00',
        'currency': 'EUR',
        'by_platform': [
          {'key': 'APP_STORE', 'units': 700, 'proceeds': '5000.00'},
          {'key': 'GOOGLE_PLAY', 'units': 500, 'proceeds': '3000.00'},
        ],
        'by_country': [
          {'key': 'BG', 'units': 300, 'proceeds': '2000.00'},
        ],
        'by_app': [],
        'by_month': [],
      });

      expect(s.totalProceeds, 8000.0);
      expect(s.byPlatform, hasLength(2));
      expect(s.byPlatform.first.label, 'APP_STORE');
      expect(s.byCountry.single.units, 300);
      expect(s.isEmpty, isFalse);
    });

    test('празна аналитика се разпознава', () {
      final s = StoreAnalytics.fromJson({
        'total_units': 0,
        'total_proceeds': '0.00',
        'currency': 'EUR',
        'by_app': [],
        'by_country': [],
        'by_platform': [],
        'by_month': [],
      });

      expect(s.isEmpty, isTrue);
    });

    test('KPI взима само числовите полета', () {
      final k = KpiSummary.fromJson({
        'revenue': '10000.00',
        'expenses': 4000,
        'currency': 'EUR',
      });

      expect(k.values['revenue'], 10000.0);
      expect(k.values['expenses'], 4000.0);
      expect(k.values.containsKey('currency'), isFalse);
    });
  });
}
