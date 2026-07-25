/// Плоски domain модели, огледални на Pydantic схемите в backend
/// (`apps/api/app/modules/*`). Без codegen — ръчни `fromJson`.
library;

class Company {
  const Company({
    required this.id,
    required this.name,
    required this.baseCurrency,
    required this.country,
    this.vatNumber,
    this.role,
  });

  final String id;
  final String name;
  final String baseCurrency;
  final String country;
  final String? vatNumber;
  final String? role;

  factory Company.fromJson(Map<String, dynamic> j) => Company(
        id: j['id'] as String,
        name: j['name'] as String,
        baseCurrency: (j['base_currency'] ?? 'EUR') as String,
        country: (j['country'] ?? 'BG') as String,
        vatNumber: j['vat_number'] as String?,
        role: j['role'] as String?,
      );
}

class AppUser {
  const AppUser({required this.id, required this.email, this.fullName});

  final String id;
  final String email;
  final String? fullName;

  factory AppUser.fromJson(Map<String, dynamic> j) => AppUser(
        id: j['id'] as String,
        email: j['email'] as String,
        fullName: j['full_name'] as String?,
      );
}

/// Жизнен цикъл (огледало на `DocumentStatus` в backend).
enum DocStatus {
  received,
  ocrProcessing,
  recognized,
  needsReview,
  missingData,
  potentialDuplicate,
  proposed,
  returned,
  approved,
  posted,
  archived,
  cancelled,
  unknown;

  static DocStatus parse(String? raw) {
    switch (raw) {
      case 'RECEIVED':
        return DocStatus.received;
      case 'OCR_PROCESSING':
        return DocStatus.ocrProcessing;
      case 'RECOGNIZED':
        return DocStatus.recognized;
      case 'NEEDS_REVIEW':
        return DocStatus.needsReview;
      case 'MISSING_DATA':
        return DocStatus.missingData;
      case 'POTENTIAL_DUPLICATE':
        return DocStatus.potentialDuplicate;
      case 'PROPOSED':
        return DocStatus.proposed;
      case 'RETURNED':
        return DocStatus.returned;
      case 'APPROVED':
        return DocStatus.approved;
      case 'POSTED':
        return DocStatus.posted;
      case 'ARCHIVED':
        return DocStatus.archived;
      case 'CANCELLED':
        return DocStatus.cancelled;
      default:
        return DocStatus.unknown;
    }
  }

  /// Стойността, която backend очаква обратно (PATCH /status).
  String get wire {
    switch (this) {
      case DocStatus.received:
        return 'RECEIVED';
      case DocStatus.ocrProcessing:
        return 'OCR_PROCESSING';
      case DocStatus.recognized:
        return 'RECOGNIZED';
      case DocStatus.needsReview:
        return 'NEEDS_REVIEW';
      case DocStatus.missingData:
        return 'MISSING_DATA';
      case DocStatus.potentialDuplicate:
        return 'POTENTIAL_DUPLICATE';
      case DocStatus.proposed:
        return 'PROPOSED';
      case DocStatus.returned:
        return 'RETURNED';
      case DocStatus.approved:
        return 'APPROVED';
      case DocStatus.posted:
        return 'POSTED';
      case DocStatus.archived:
        return 'ARCHIVED';
      case DocStatus.cancelled:
        return 'CANCELLED';
      case DocStatus.unknown:
        return 'RECEIVED';
    }
  }

  String get label {
    switch (this) {
      case DocStatus.received:
        return 'Получен';
      case DocStatus.ocrProcessing:
        return 'Разпознаване…';
      case DocStatus.recognized:
        return 'Разпознат';
      case DocStatus.needsReview:
        return 'Нужна проверка';
      case DocStatus.missingData:
        return 'Липсват данни';
      case DocStatus.potentialDuplicate:
        return 'Възможен дубликат';
      case DocStatus.proposed:
        return 'Предложен';
      case DocStatus.returned:
        return 'Върнат';
      case DocStatus.approved:
        return 'Одобрен';
      case DocStatus.posted:
        return 'Осчетоводен';
      case DocStatus.archived:
        return 'Архивиран';
      case DocStatus.cancelled:
        return 'Отказан';
      case DocStatus.unknown:
        return '—';
    }
  }
}

class Document {
  const Document({
    required this.id,
    required this.originalFilename,
    required this.contentType,
    required this.sizeBytes,
    required this.sha256,
    required this.docType,
    required this.source,
    required this.status,
    this.notes,
  });

  final String id;
  final String originalFilename;
  final String contentType;
  final int sizeBytes;
  final String sha256;
  final String docType;
  final String source;
  final DocStatus status;
  final String? notes;

  factory Document.fromJson(Map<String, dynamic> j) => Document(
        id: j['id'] as String,
        originalFilename: (j['original_filename'] ?? '') as String,
        contentType: (j['content_type'] ?? '') as String,
        sizeBytes: (j['size_bytes'] ?? 0) as int,
        sha256: (j['sha256'] ?? '') as String,
        docType: (j['doc_type'] ?? 'UNKNOWN') as String,
        source: (j['source'] ?? 'UPLOAD') as String,
        status: DocStatus.parse(j['status'] as String?),
        notes: j['notes'] as String?,
      );
}

/// Едно разпознато поле — стойност плюс увереността за нея.
class ExtractedField {
  const ExtractedField({
    required this.key,
    required this.label,
    required this.value,
    this.confidence,
  });

  final String key;
  final String label;
  final String value;
  final double? confidence;

  /// Под този праг полето се маркира визуално за ръчна проверка.
  bool get isUncertain => confidence != null && confidence! < 0.75;
}

/// Извлечените от AI структурирани данни (`DocumentExtraction.data`).
///
/// Реалната структура е `{fields: {...}, field_confidence: {...},
/// overall_confidence: 0.62, notes: "..."}`.
class Extraction {
  const Extraction({
    required this.id,
    required this.documentId,
    required this.model,
    required this.data,
  });

  final String id;
  final String documentId;
  final String model;
  final Map<String, dynamic> data;

  Map<String, dynamic> get fields {
    final f = data['fields'];
    if (f is Map) return f.cast<String, dynamic>();
    return data; // толерантност към плосък отговор
  }

  Map<String, dynamic> get _fieldConfidence {
    final c = data['field_confidence'];
    if (c is Map) return c.cast<String, dynamic>();
    return const {};
  }

  double? get confidence => _toDoubleOrNull(data['overall_confidence']);

  String? get notes {
    final n = data['notes'];
    return n is String && n.isNotEmpty ? n : null;
  }

  /// Полетата, които показваме в детайла — подредени и с български етикети.
  /// Всяко има по няколко възможни имена, защото различните AI клиенти
  /// (stub / Anthropic) ползват леко различни ключове.
  static const _display = <(String label, List<String> keys)>[
    ('Доставчик', ['issuer', 'supplier_name']),
    ('ЕИК', ['issuer_eik', 'supplier_eik']),
    ('ДДС номер', ['issuer_vat_number', 'supplier_vat']),
    ('Вид документ', ['document_type']),
    ('Документ №', ['document_number', 'invoice_number']),
    ('Дата', ['document_date', 'invoice_date']),
    ('Падеж', ['due_date']),
    ('Данъчна основа', ['tax_base', 'net_amount']),
    ('ДДС ставка', ['vat_rate']),
    ('ДДС', ['vat_amount']),
    ('Общо', ['total', 'total_amount']),
    ('Валута', ['currency']),
    ('IBAN', ['iban']),
  ];

  List<ExtractedField> get displayFields {
    final f = fields;
    final conf = _fieldConfidence;
    final out = <ExtractedField>[];
    for (final (label, keys) in _display) {
      for (final key in keys) {
        final v = f[key];
        if (v == null || v.toString().isEmpty) continue;
        out.add(ExtractedField(
          key: key,
          label: label,
          value: v.toString(),
          confidence: _toDoubleOrNull(conf[key]),
        ));
        break;
      }
    }
    return out;
  }

  factory Extraction.fromJson(Map<String, dynamic> j) => Extraction(
        id: j['id'] as String,
        documentId: j['document_id'] as String,
        model: (j['model'] ?? '') as String,
        data: (j['data'] as Map?)?.cast<String, dynamic>() ?? const {},
      );
}

// ---------------------------------------------------------------- счетоводство

/// Сметка от индивидуалния сметкоплан на компанията.
class Account {
  const Account({required this.id, required this.code, required this.name});

  final String id;
  final String code;
  final String name;

  factory Account.fromJson(Map<String, dynamic> j) => Account(
        id: j['id'] as String,
        code: (j['code'] ?? '') as String,
        name: (j['name'] ?? '') as String,
      );
}

/// Ред от предложената счетоводна статия.
class JournalLine {
  const JournalLine({
    required this.lineNo,
    required this.accountId,
    required this.debit,
    required this.credit,
    this.accountCode,
    this.accountName,
    this.description,
  });

  final int lineNo;
  final String accountId;
  final double debit;
  final double credit;
  final String? accountCode;
  final String? accountName;
  final String? description;

  factory JournalLine.fromJson(Map<String, dynamic> j) => JournalLine(
        lineNo: (j['line_no'] ?? 0) as int,
        accountId: (j['account_id'] ?? '') as String,
        debit: _toDouble(j['debit']),
        credit: _toDouble(j['credit']),
        accountCode: j['account_code'] as String?,
        accountName: j['account_name'] as String?,
        description: j['description'] as String?,
      );
}

/// Счетоводна статия (DRAFT преди потвърждение, POSTED след това).
class JournalEntry {
  const JournalEntry({
    required this.id,
    required this.status,
    required this.currency,
    required this.documentDate,
    required this.totalDebit,
    required this.totalCredit,
    required this.lines,
    this.entryNumber,
    this.description,
    this.documentNumber,
  });

  final String id;
  final String status;
  final String currency;
  final String documentDate;
  final double totalDebit;
  final double totalCredit;
  final List<JournalLine> lines;
  final int? entryNumber;
  final String? description;
  final String? documentNumber;

  bool get isPosted => status == 'POSTED';
  bool get isDraft => status == 'DRAFT';

  factory JournalEntry.fromJson(Map<String, dynamic> j) => JournalEntry(
        id: j['id'] as String,
        status: (j['status'] ?? 'DRAFT') as String,
        currency: (j['currency'] ?? 'EUR') as String,
        documentDate: (j['document_date'] ?? '') as String,
        totalDebit: _toDouble(j['total_debit']),
        totalCredit: _toDouble(j['total_credit']),
        lines: ((j['lines'] as List?) ?? const [])
            .map((e) => JournalLine.fromJson((e as Map).cast<String, dynamic>()))
            .toList(),
        entryNumber: j['entry_number'] as int?,
        description: j['description'] as String?,
        documentNumber: j['document_number'] as String?,
      );
}

/// Предложение за осчетоводяване, генерирано от AI („предлага, не осчетоводява").
class PostingProposal {
  const PostingProposal({
    required this.confidence,
    required this.rationale,
    required this.warnings,
    this.entry,
  });

  final double confidence;
  final String rationale;
  final List<String> warnings;
  final JournalEntry? entry;

  factory PostingProposal.fromJson(Map<String, dynamic> j) => PostingProposal(
        confidence: _toDouble(j['confidence']),
        rationale: (j['rationale'] ?? '') as String,
        warnings: ((j['warnings'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        entry: j['entry'] == null
            ? null
            : JournalEntry.fromJson((j['entry'] as Map).cast<String, dynamic>()),
      );
}

/// Резултат от `POST /documents/scan` — изображение + данни + предложена статия.
class ScanResult {
  const ScanResult({
    required this.document,
    required this.extraction,
    this.posting,
  });

  final Document document;
  final Extraction extraction;
  final PostingProposal? posting;

  factory ScanResult.fromJson(Map<String, dynamic> j) => ScanResult(
        document: Document.fromJson((j['document'] as Map).cast<String, dynamic>()),
        extraction:
            Extraction.fromJson((j['extraction'] as Map).cast<String, dynamic>()),
        posting: j['posting'] == null
            ? null
            : PostingProposal.fromJson(
                (j['posting'] as Map).cast<String, dynamic>()),
      );
}

// ------------------------------------------------------------------------ ДДС

enum VatPeriodStatus {
  open,
  ready,
  approved,
  rejected;

  static VatPeriodStatus parse(String? raw) {
    switch (raw) {
      case 'READY':
        return VatPeriodStatus.ready;
      case 'APPROVED':
        return VatPeriodStatus.approved;
      case 'REJECTED':
        return VatPeriodStatus.rejected;
      default:
        return VatPeriodStatus.open;
    }
  }

  String get label {
    switch (this) {
      case VatPeriodStatus.open:
        return 'Отворен';
      case VatPeriodStatus.ready:
        return 'За одобрение';
      case VatPeriodStatus.approved:
        return 'Одобрен';
      case VatPeriodStatus.rejected:
        return 'Отказан';
    }
  }
}

/// Обобщение на месечен ДДС период (`GET /vat/periods`).
class VatPeriodSummary {
  const VatPeriodSummary({
    required this.periodId,
    required this.code,
    required this.startDate,
    required this.endDate,
    required this.outputVat,
    required this.inputVat,
    required this.netPayable,
    required this.status,
    this.closedAt,
    this.rejectionReason,
  });

  final String periodId;
  final String code;
  final String startDate;
  final String endDate;
  final double outputVat;
  final double inputVat;
  final double netPayable;
  final VatPeriodStatus status;
  final String? closedAt;

  /// Причината от последния отказ (когато статусът е REJECTED).
  final String? rejectionReason;

  factory VatPeriodSummary.fromJson(Map<String, dynamic> j) => VatPeriodSummary(
        periodId: j['period_id'] as String,
        code: (j['code'] ?? '') as String,
        startDate: (j['start_date'] ?? '') as String,
        endDate: (j['end_date'] ?? '') as String,
        outputVat: _toDouble(j['output_vat']),
        inputVat: _toDouble(j['input_vat']),
        netPayable: _toDouble(j['net_payable']),
        status: VatPeriodStatus.parse(j['status'] as String?),
        closedAt: j['closed_at'] as String?,
        rejectionReason: j['rejection_reason'] as String?,
      );
}

/// Клетките на справка-декларацията по ЗДДС.
class VatDeclaration {
  const VatDeclaration({required this.cells, required this.raw});

  /// Наредени клетки за показване: (номер, наименование, стойност).
  final List<({String cell, String label, double value})> cells;
  final Map<String, dynamic> raw;

  factory VatDeclaration.fromJson(Map<String, dynamic> j) {
    final cells = <({String cell, String label, double value})>[];
    final rawCells = j['cells'];
    if (rawCells is List) {
      for (final c in rawCells) {
        if (c is Map) {
          cells.add((
            cell: (c['cell'] ?? c['code'] ?? '').toString(),
            label: (c['label'] ?? c['name'] ?? '').toString(),
            value: _toDouble(c['value'] ?? c['amount']),
          ));
        }
      }
    } else if (rawCells is Map) {
      rawCells.forEach((k, v) {
        cells.add((cell: k.toString(), label: '', value: _toDouble(v)));
      });
    }
    return VatDeclaration(cells: cells, raw: j.cast<String, dynamic>());
  }
}

// -------------------------------------------------------------------- отчети

/// KPI обобщение за дашборда (`GET /reports/kpis`).
class KpiSummary {
  const KpiSummary({required this.values, required this.raw});

  final Map<String, double> values;
  final Map<String, dynamic> raw;

  factory KpiSummary.fromJson(Map<String, dynamic> j) {
    final values = <String, double>{};
    j.forEach((k, v) {
      if (v is num || (v is String && double.tryParse(v) != null)) {
        values[k] = _toDouble(v);
      }
    });
    return KpiSummary(values: values, raw: j);
  }
}

/// Ред от ОПР (приход или разход).
class PnlLine {
  const PnlLine({required this.label, required this.amount});

  final String label;
  final double amount;
}

/// Отчет за приходите и разходите (`GET /reports/profit-and-loss`).
///
/// Backend връща `revenue`/`expenses` като секции (`PnlSection`) с редове по
/// сметки, плюс групи по НСС статии (`revenue_groups`/`expense_groups`).
/// За мобилния екран предпочитаме групите — по-малко и по-смислени редове.
class ProfitAndLoss {
  const ProfitAndLoss({
    required this.revenue,
    required this.expenses,
    required this.profit,
    required this.revenueLines,
    required this.expenseLines,
    required this.currency,
  });

  final double revenue;
  final double expenses;
  final double profit;
  final List<PnlLine> revenueLines;
  final List<PnlLine> expenseLines;
  final String currency;

  static List<PnlLine> _lines(dynamic raw) {
    if (raw is! List) return const [];
    return raw.map((e) {
      final m = (e as Map).cast<String, dynamic>();
      // Групите носят `title`, редовете по сметки — `code` + `name`.
      final title = m['title'];
      final label = title != null
          ? title.toString()
          : [m['code'], m['name']]
              .where((v) => v != null && v.toString().isNotEmpty)
              .join(' · ');
      return PnlLine(
        label: label.isEmpty ? '—' : label,
        amount: _toDouble(m['amount']),
      );
    }).toList();
  }

  /// Секцията е обект `{title, lines, total}`.
  static (double total, List<PnlLine> lines) _section(dynamic raw) {
    if (raw is Map) {
      final m = raw.cast<String, dynamic>();
      return (_toDouble(m['total']), _lines(m['lines']));
    }
    return (_toDouble(raw), const []);
  }

  factory ProfitAndLoss.fromJson(Map<String, dynamic> j) {
    final (revenue, revenueBySection) = _section(j['revenue']);
    final (expenses, expensesBySection) = _section(j['expenses']);

    final revenueGroups = _lines(j['revenue_groups']);
    final expenseGroups = _lines(j['expense_groups']);

    return ProfitAndLoss(
      revenue: revenue,
      expenses: expenses,
      profit: _toDouble(j['net_profit'] ?? (revenue - expenses)),
      revenueLines: revenueGroups.isNotEmpty ? revenueGroups : revenueBySection,
      expenseLines: expenseGroups.isNotEmpty ? expenseGroups : expensesBySection,
      currency: (j['currency'] ?? 'EUR') as String,
    );
  }
}

/// Продажби от App Store / Google Play (`GET /stores/analytics`).
///
/// Разбивките са `NamedTotal` — `{key, units, proceeds}`.
class StoreAnalytics {
  const StoreAnalytics({
    required this.totalProceeds,
    required this.totalUnits,
    required this.currency,
    required this.byApp,
    required this.byPlatform,
    required this.byCountry,
    required this.byMonth,
  });

  final double totalProceeds;
  final int totalUnits;
  final String currency;
  final List<({String label, double amount, int units})> byApp;
  final List<({String label, double amount, int units})> byPlatform;
  final List<({String label, double amount, int units})> byCountry;
  final List<({String label, double amount, int units})> byMonth;

  bool get isEmpty =>
      totalProceeds == 0 && totalUnits == 0 && byApp.isEmpty && byPlatform.isEmpty;

  static List<({String label, double amount, int units})> _breakdown(dynamic raw) {
    if (raw is! List) return const [];
    return raw.map((e) {
      final m = (e as Map).cast<String, dynamic>();
      final units = m['units'];
      return (
        label: (m['key'] ?? '—').toString(),
        amount: _toDouble(m['proceeds']),
        units: units is int ? units : _toDouble(units).round(),
      );
    }).toList();
  }

  factory StoreAnalytics.fromJson(Map<String, dynamic> j) {
    final units = j['total_units'];
    return StoreAnalytics(
      totalProceeds: _toDouble(j['total_proceeds']),
      totalUnits: units is int ? units : _toDouble(units).round(),
      currency: (j['currency'] ?? 'EUR') as String,
      byApp: _breakdown(j['by_app']),
      byPlatform: _breakdown(j['by_platform']),
      byCountry: _breakdown(j['by_country']),
      byMonth: _breakdown(j['by_month']),
    );
  }
}

/// Толерантен парсър — backend праща Decimal като string в JSON.
double _toDouble(dynamic v) => _toDoubleOrNull(v) ?? 0;

double? _toDoubleOrNull(dynamic v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}
