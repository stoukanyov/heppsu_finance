import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../core/security/secure_store.dart';
import '../domain/models.dart';

/// Автентикация и избор на компания.
class AuthRepository {
  AuthRepository(this._api, this._store);

  final ApiClient _api;
  final SecureStore _store;

  /// Login → връща JWT и го записва в secure storage.
  Future<void> login(String email, String password) async {
    final data = await _api.post(
      '/auth/login',
      data: {'email': email, 'password': password},
      requiresCompany: false,
    );
    final token = (data as Map)['access_token'] as String;
    await _store.writeToken(token);
  }

  Future<AppUser> me() async {
    final data = await _api.get('/auth/me');
    return AppUser.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<List<Company>> companies() async {
    final data = await _api.get('/companies');
    return (data as List)
        .map((e) => Company.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }

  Future<void> selectCompany(String companyId) =>
      _store.writeCompanyId(companyId);

  Future<String?> activeCompanyId() => _store.readCompanyId();

  Future<void> logout() => _store.clear();
}

/// Документи: сканиране, списък, детайл, смяна на статус.
class DocumentsRepository {
  DocumentsRepository(this._api);

  final ApiClient _api;

  /// Комбиниран мобилен scan: качва байтовете и връща документ + extraction.
  ///
  /// `companyId` се подава от опашката: сканът трябва да стигне до компанията,
  /// в която е направен, дори ако потребителят е сменил активната междувременно.
  Future<ScanResult> submitScan({
    required Uint8List bytes,
    required String filename,
    required String contentType,
    String? note,
    String? companyId,
  }) async {
    final form = FormData.fromMap({
      'file': MultipartFile.fromBytes(
        bytes,
        filename: filename,
        contentType: DioMediaType.parse(contentType),
      ),
      if (note != null && note.isNotEmpty) 'note': note,
    });
    final data = await _api.post(
      '/documents/scan',
      data: form,
      companyId: companyId,
    );
    return ScanResult.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<List<Document>> list({DocStatus? status}) async {
    final data = await _api.get(
      '/documents',
      query: {if (status != null) 'status': status.wire},
    );
    return (data as List)
        .map((e) => Document.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }

  Future<Document> get(String id) async {
    final data = await _api.get('/documents/$id');
    return Document.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<Document> updateStatus(String id, DocStatus status) async {
    final data = await _api.patch(
      '/documents/$id/status',
      data: {'status': status.wire},
    );
    return Document.fromJson((data as Map).cast<String, dynamic>());
  }

  /// Поиска (или преизползва) предложение за осчетоводяване на документа.
  Future<PostingProposal> proposePosting(String docId) async {
    final data = await _api.post('/documents/$docId/propose-posting');
    return PostingProposal.fromJson((data as Map).cast<String, dynamic>());
  }

  /// Потвърждение от потребителя: осчетоводява статията и придвижва документа.
  /// Идемпотентно — повторно натискане връща същата статия.
  Future<({Document document, JournalEntry entry})> confirmPosting(
    String docId,
  ) async {
    final data = await _api.post('/documents/$docId/confirm-posting');
    final m = (data as Map).cast<String, dynamic>();
    return (
      document: Document.fromJson((m['document'] as Map).cast<String, dynamic>()),
      entry: JournalEntry.fromJson((m['entry'] as Map).cast<String, dynamic>()),
    );
  }

  /// Тегли оригиналното изображение/PDF (заявката носи Bearer + X-Company-Id).
  Future<Uint8List> fileBytes(String docId) async {
    final res = await _api.raw.get<List<int>>(
      '/documents/$docId/file',
      options: Options(responseType: ResponseType.bytes),
    );
    final code = res.statusCode ?? 0;
    if (code < 200 || code >= 300) {
      throw ApiException(code, 'Файлът не може да бъде зареден');
    }
    return Uint8List.fromList(res.data ?? const []);
  }
}

/// Сметкоплан — нужен, за да покажем кодове и имена в статията
/// (`JournalLineOut` носи само `account_id`).
class AccountsRepository {
  AccountsRepository(this._api);

  final ApiClient _api;

  Future<Map<String, Account>> byId() async {
    final data = await _api.get('/accounting/accounts');
    final map = <String, Account>{};
    for (final e in (data as List)) {
      final a = Account.fromJson((e as Map).cast<String, dynamic>());
      map[a.id] = a;
    }
    return map;
  }
}

/// ДДС: месечни периоди, справка-декларация, одобрение/отказ.
class VatRepository {
  VatRepository(this._api);

  final ApiClient _api;

  Future<List<VatPeriodSummary>> periods() async {
    final data = await _api.get('/vat/periods');
    return (data as List)
        .map((e) => VatPeriodSummary.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }

  Future<VatDeclaration> declaration(String periodId) async {
    final data = await _api.get('/vat/returns/$periodId/declaration');
    return VatDeclaration.fromJson((data as Map).cast<String, dynamic>());
  }

  /// Одобрение = приключване на ДДС периода.
  Future<void> approve(String periodId) =>
      _api.post('/vat/periods/$periodId/close');

  /// Отказ → връща периода за корекция.
  Future<void> reject(String periodId, {String? reason}) => _api.post(
        '/vat/periods/$periodId/reject',
        data: {if (reason != null && reason.isNotEmpty) 'reason': reason},
      );
}

/// Срокове за подаване/плащане към НАП, НСИ и Търговския регистър.
class DeadlinesRepository {
  DeadlinesRepository(this._api);

  final ApiClient _api;

  Future<List<Deadline>> upcoming({int daysAhead = 90}) async {
    final data = await _api.get(
      '/deadlines/upcoming',
      query: {'days_ahead': daysAhead},
    );
    return (data as List)
        .map((e) => Deadline.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }
}

/// Отчети: KPI, ОПР и продажби от магазините.
class ReportsRepository {
  ReportsRepository(this._api);

  final ApiClient _api;

  Future<KpiSummary> kpis({String? dateFrom, String? dateTo}) async {
    final data = await _api.get('/reports/kpis', query: {
      'date_from': ?dateFrom,
      'date_to': ?dateTo,
    });
    return KpiSummary.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<ProfitAndLoss> profitAndLoss({String? dateFrom, String? dateTo}) async {
    final data = await _api.get('/reports/profit-and-loss', query: {
      'date_from': ?dateFrom,
      'date_to': ?dateTo,
    });
    return ProfitAndLoss.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<StoreAnalytics> storeAnalytics({
    String? dateFrom,
    String? dateTo,
    String? platform,
  }) async {
    final data = await _api.get('/stores/analytics', query: {
      'date_from': ?dateFrom,
      'date_to': ?dateTo,
      'platform': ?platform,
    });
    return StoreAnalytics.fromJson((data as Map).cast<String, dynamic>());
  }
}
