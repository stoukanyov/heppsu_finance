import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_client.dart';
import '../core/network/api_exception.dart';
import '../core/notifications/reminder_service.dart';
import '../core/security/secure_store.dart';
import '../data/repositories.dart';
import '../domain/models.dart';

final secureStoreProvider = Provider<SecureStore>((ref) => SecureStore());

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient(ref.watch(secureStoreProvider));
  client.onUnauthorized = () => ref.read(sessionProvider.notifier).onUnauthorized();
  return client;
});

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(ref.watch(apiClientProvider), ref.watch(secureStoreProvider)),
);

final documentsRepositoryProvider = Provider<DocumentsRepository>(
  (ref) => DocumentsRepository(ref.watch(apiClientProvider)),
);

final accountsRepositoryProvider = Provider<AccountsRepository>(
  (ref) => AccountsRepository(ref.watch(apiClientProvider)),
);

/// Сметкопланът се сменя рядко — държим го кеширан за целия живот на сесията.
final accountsByIdProvider = FutureProvider<Map<String, Account>>((ref) {
  return ref.watch(accountsRepositoryProvider).byId();
});

final vatRepositoryProvider = Provider<VatRepository>(
  (ref) => VatRepository(ref.watch(apiClientProvider)),
);

final reportsRepositoryProvider = Provider<ReportsRepository>(
  (ref) => ReportsRepository(ref.watch(apiClientProvider)),
);

final deadlinesRepositoryProvider = Provider<DeadlinesRepository>(
  (ref) => DeadlinesRepository(ref.watch(apiClientProvider)),
);

final reminderServiceProvider = Provider<ReminderService>(
  (ref) => ReminderService(),
);

// ------------------------------------------------------- данни за екраните

/// Филтър по статус в екран „Документи" (null = всички).
final documentsFilterProvider = StateProvider<DocStatus?>((ref) => null);

final documentsListProvider = FutureProvider.autoDispose<List<Document>>((ref) {
  final filter = ref.watch(documentsFilterProvider);
  return ref.watch(documentsRepositoryProvider).list(status: filter);
});

final vatPeriodsProvider =
    FutureProvider.autoDispose<List<VatPeriodSummary>>((ref) {
  return ref.watch(vatRepositoryProvider).periods();
});

final vatDeclarationProvider =
    FutureProvider.autoDispose.family<VatDeclaration, String>((ref, periodId) {
  return ref.watch(vatRepositoryProvider).declaration(periodId);
});

/// Период за отчетите — текущата година до днес по подразбиране.
class ReportRange {
  const ReportRange(this.from, this.to);

  final DateTime from;
  final DateTime to;

  String get fromIso => _iso(from);
  String get toIso => _iso(to);

  static String _iso(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-'
      '${d.month.toString().padLeft(2, '0')}-'
      '${d.day.toString().padLeft(2, '0')}';
}

final reportRangeProvider = StateProvider<ReportRange>((ref) {
  final now = DateTime.now();
  return ReportRange(DateTime(now.year, 1, 1), now);
});

final kpisProvider = FutureProvider.autoDispose<KpiSummary>((ref) {
  final r = ref.watch(reportRangeProvider);
  return ref.watch(reportsRepositoryProvider).kpis(
        dateFrom: r.fromIso,
        dateTo: r.toIso,
      );
});

final pnlProvider = FutureProvider.autoDispose<ProfitAndLoss>((ref) {
  final r = ref.watch(reportRangeProvider);
  return ref.watch(reportsRepositoryProvider).profitAndLoss(
        dateFrom: r.fromIso,
        dateTo: r.toIso,
      );
});

final storeAnalyticsProvider = FutureProvider.autoDispose<StoreAnalytics>((ref) {
  final r = ref.watch(reportRangeProvider);
  return ref.watch(reportsRepositoryProvider).storeAnalytics(
        dateFrom: r.fromIso,
        dateTo: r.toIso,
      );
});

// ------------------------------------------------------------------ срокове

final deadlinesProvider = FutureProvider<List<Deadline>>((ref) async {
  final deadlines = await ref.watch(deadlinesRepositoryProvider).upcoming();
  // При всяко презареждане пренасрочваме напомнянията, за да отразят
  // променените или отпаднали срокове.
  if (ref.read(remindersEnabledProvider)) {
    await ref.read(reminderServiceProvider).reschedule(deadlines);
  }
  return deadlines;
});

/// Дали локалните напомняния са включени (пази се в secure storage).
final remindersEnabledProvider =
    StateNotifierProvider<RemindersEnabledController, bool>((ref) {
  return RemindersEnabledController(ref)..load();
});

class RemindersEnabledController extends StateNotifier<bool> {
  RemindersEnabledController(this._ref) : super(false);

  final Ref _ref;

  Future<void> load() async {
    state = await _ref.read(secureStoreProvider).remindersEnabled();
  }

  /// Включва/изключва напомнянията. При включване иска разрешение от системата
  /// и веднага насрочва известията за вече заредените срокове.
  Future<bool> toggle(bool enabled) async {
    final service = _ref.read(reminderServiceProvider);
    if (!enabled) {
      await service.cancelAll();
      await _ref.read(secureStoreProvider).setRemindersEnabled(false);
      state = false;
      return false;
    }

    final granted = await service.requestPermission();
    if (!granted) {
      state = false;
      return false;
    }
    await _ref.read(secureStoreProvider).setRemindersEnabled(true);
    state = true;

    final deadlines = _ref.read(deadlinesProvider).valueOrNull;
    if (deadlines != null) await service.reschedule(deadlines);
    return true;
  }
}

/// Състояние на сесията: зареждане → нужен login → нужен избор на компания → готово.
enum SessionStage { loading, unauthenticated, needsCompany, ready }

class SessionState {
  const SessionState({
    required this.stage,
    this.user,
    this.companies = const [],
    this.activeCompanyId,
    this.startupError,
  });

  final SessionStage stage;
  final AppUser? user;
  final List<Company> companies;
  final String? activeCompanyId;

  /// Съобщение, ако възстановяването на сесията при старт се е провалило —
  /// показва се на екрана за вход, за да не изглежда като „грешна парола".
  final String? startupError;

  Company? get activeCompany {
    for (final c in companies) {
      if (c.id == activeCompanyId) return c;
    }
    return null;
  }

  SessionState copyWith({
    SessionStage? stage,
    AppUser? user,
    List<Company>? companies,
    String? activeCompanyId,
  }) =>
      SessionState(
        stage: stage ?? this.stage,
        user: user ?? this.user,
        companies: companies ?? this.companies,
        activeCompanyId: activeCompanyId ?? this.activeCompanyId,
      );
}

final sessionProvider =
    StateNotifierProvider<SessionController, SessionState>((ref) {
  return SessionController(ref)..bootstrap();
});

class SessionController extends StateNotifier<SessionState> {
  SessionController(this._ref)
      : super(const SessionState(stage: SessionStage.loading));

  final Ref _ref;
  AuthRepository get _auth => _ref.read(authRepositoryProvider);

  /// При старт: ако има валиден токен → зареди профил и компании.
  ///
  /// Никога не оставя приложението на splash: при всяка грешка връща към Login
  /// с обяснение, вместо да увисне в `loading`.
  Future<void> bootstrap() async {
    try {
      final token = await _ref.read(secureStoreProvider).readToken();
      if (token == null) {
        state = const SessionState(stage: SessionStage.unauthenticated);
        return;
      }
      await _loadAfterAuth();
    } on ApiException catch (e) {
      // 401 вече е обработен от интерцептора; тук остават 5xx/403 и подобни.
      state = SessionState(
        stage: SessionStage.unauthenticated,
        startupError: e.isUnauthorized ? null : e.message,
      );
    } catch (_) {
      state = const SessionState(
        stage: SessionStage.unauthenticated,
        startupError: 'Няма връзка със сървъра. Влез отново, когато си онлайн.',
      );
    }
  }

  Future<void> login(String email, String password) async {
    await _auth.login(email, password);
    await _loadAfterAuth();
  }

  Future<void> _loadAfterAuth() async {
    final user = await _auth.me();
    final companies = await _auth.companies();
    final saved = await _auth.activeCompanyId();
    final validSaved =
        companies.any((c) => c.id == saved) ? saved : null;

    if (companies.length == 1 && validSaved == null) {
      await _auth.selectCompany(companies.first.id);
    }
    final active = validSaved ??
        (companies.length == 1 ? companies.first.id : null);

    state = SessionState(
      stage: active == null ? SessionStage.needsCompany : SessionStage.ready,
      user: user,
      companies: companies,
      activeCompanyId: active,
    );
  }

  Future<void> selectCompany(String companyId) async {
    await _auth.selectCompany(companyId);
    state = state.copyWith(
      stage: SessionStage.ready,
      activeCompanyId: companyId,
    );
  }

  void onUnauthorized() {
    _auth.logout();
    state = const SessionState(stage: SessionStage.unauthenticated);
  }

  Future<void> logout() async {
    await _auth.logout();
    state = const SessionState(stage: SessionStage.unauthenticated);
  }
}
