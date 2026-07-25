import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../common/widgets.dart';
import 'bar_list.dart';

/// Отчети: KPI, ОПР и продажби от App Store / Google Play.
class ReportsScreen extends ConsumerWidget {
  const ReportsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(kpisProvider);
        ref.invalidate(pnlProvider);
        ref.invalidate(storeAnalyticsProvider);
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 110),
        children: const [
          _RangeSelector(),
          SizedBox(height: 16),
          _KpiGrid(),
          SizedBox(height: 26),
          _PnlSection(),
          SizedBox(height: 26),
          _StoresSection(),
        ],
      ),
    );
  }
}

/// Бърз избор на период за всички отчети на екрана.
class _RangeSelector extends ConsumerWidget {
  const _RangeSelector();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final now = DateTime.now();
    final options = <(String, ReportRange)>[
      ('Този месец', ReportRange(DateTime(now.year, now.month, 1), now)),
      (
        'Миналият месец',
        ReportRange(
          DateTime(now.year, now.month - 1, 1),
          DateTime(now.year, now.month, 0),
        )
      ),
      ('Тази година', ReportRange(DateTime(now.year, 1, 1), now)),
    ];
    final active = ref.watch(reportRangeProvider);

    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: options.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final (label, range) = options[i];
          final selected = active.fromIso == range.fromIso &&
              active.toIso == range.toIso;
          return ChoiceChip(
            label: Text(label),
            selected: selected,
            onSelected: (_) =>
                ref.read(reportRangeProvider.notifier).state = range,
          );
        },
      ),
    );
  }
}

class _KpiGrid extends ConsumerWidget {
  const _KpiGrid();

  /// Показваме само тези метрики и в този ред, с български етикети.
  static const _wanted = <String, (String, IconData, Color)>{
    'revenue': ('Приходи', Icons.trending_up_rounded, Color(0xFF12A150)),
    'expenses': ('Разходи', Icons.trending_down_rounded, Color(0xFFDC2626)),
    'profit': ('Печалба', Icons.savings_rounded, Color(0xFF3B5BFE)),
    'cash': ('Налични пари', Icons.account_balance_rounded, Color(0xFF7C3AED)),
    'receivables': ('Вземания', Icons.call_received_rounded, Color(0xFF0891B2)),
    'payables': ('Задължения', Icons.call_made_rounded, Color(0xFFD97706)),
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(kpisProvider);
    return async.when(
      loading: () => const SizedBox(
        height: 140,
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => ErrorView(
        message: 'Няма KPI данни.',
        onRetry: () => ref.invalidate(kpisProvider),
      ),
      data: (kpi) {
        final cards = <Widget>[];
        _wanted.forEach((key, meta) {
          final value = kpi.values[key];
          if (value == null) return;
          final (label, icon, color) = meta;
          cards.add(KpiCard(
            title: label,
            value: formatMoney(value),
            icon: icon,
            color: color,
          ));
        });
        if (cards.isEmpty) {
          return const EmptyView(message: 'Няма данни за периода.');
        }
        return GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          childAspectRatio: 1.28,
          children: cards,
        );
      },
    );
  }
}

class _PnlSection extends ConsumerWidget {
  const _PnlSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(pnlProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Приходи и разходи'),
        async.when(
          loading: () => const Card(
            child: Padding(
              padding: EdgeInsets.all(28),
              child: Center(
                child: SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.4),
                ),
              ),
            ),
          ),
          error: (e, _) => Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Text('ОПР не можа да се зареди.\n$e',
                  style: const TextStyle(fontSize: 13)),
            ),
          ),
          data: (pnl) => Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      _PnlTotal(
                        label: 'Приходи',
                        value: pnl.revenue,
                        currency: pnl.currency,
                        color: const Color(0xFF12A150),
                      ),
                      _PnlTotal(
                        label: 'Разходи',
                        value: pnl.expenses,
                        currency: pnl.currency,
                        color: const Color(0xFFDC2626),
                      ),
                      _PnlTotal(
                        label: 'Резултат',
                        value: pnl.profit,
                        currency: pnl.currency,
                        last: true,
                        color: pnl.profit >= 0
                            ? const Color(0xFF3B5BFE)
                            : const Color(0xFFDC2626),
                      ),
                    ],
                  ),
                  if (pnl.revenueLines.isNotEmpty) ...[
                    const Divider(height: 28),
                    BarList(
                      title: 'Приходи по статии',
                      color: const Color(0xFF12A150),
                      currency: pnl.currency,
                      items: [
                        for (final l in pnl.revenueLines)
                          (label: l.label, value: l.amount),
                      ],
                    ),
                  ],
                  if (pnl.expenseLines.isNotEmpty) ...[
                    const SizedBox(height: 18),
                    BarList(
                      title: 'Разходи по статии',
                      color: const Color(0xFFDC2626),
                      currency: pnl.currency,
                      items: [
                        for (final l in pnl.expenseLines)
                          (label: l.label, value: l.amount),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _PnlTotal extends StatelessWidget {
  const _PnlTotal({
    required this.label,
    required this.value,
    required this.currency,
    required this.color,
    this.last = false,
  });

  final String label;
  final double value;
  final String currency;
  final Color color;

  /// Последната колона няма нужда от отстояние вдясно.
  final bool last;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Padding(
        padding: EdgeInsets.only(right: last ? 0 : 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: TextStyle(
                fontSize: 12,
                color: Colors.black.withValues(alpha: 0.5),
              ),
            ),
            const SizedBox(height: 3),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(
                formatMoney(value, currency),
                style: TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w800,
                  color: color,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Продажби от App Store и Google Play.
class _StoresSection extends ConsumerWidget {
  const _StoresSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(storeAnalyticsProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SectionTitle('Продажби от магазините'),
        async.when(
          loading: () => const Card(
            child: Padding(
              padding: EdgeInsets.all(28),
              child: Center(
                child: SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.4),
                ),
              ),
            ),
          ),
          error: (e, _) => const Card(
            child: Padding(
              padding: EdgeInsets.all(20),
              child: Text(
                'Няма данни от App Store / Google Play за този период.',
                style: TextStyle(fontSize: 13),
              ),
            ),
          ),
          data: (s) {
            if (s.isEmpty) {
              return const Card(
                child: Padding(
                  padding: EdgeInsets.all(20),
                  child: Text(
                    'Няма синхронизирани продажби за този период.',
                    style: TextStyle(fontSize: 13),
                  ),
                ),
              );
            }
            return Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Общо приходи',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: Colors.black.withValues(alpha: 0.5),
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                formatMoney(s.totalProceeds, s.currency),
                                style: const TextStyle(
                                    fontSize: 19, fontWeight: FontWeight.w800),
                              ),
                            ],
                          ),
                        ),
                        if (s.totalUnits > 0)
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text(
                                'Бройки',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: Colors.black.withValues(alpha: 0.5),
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                formatNumber(s.totalUnits),
                                style: const TextStyle(
                                    fontSize: 19, fontWeight: FontWeight.w800),
                              ),
                            ],
                          ),
                      ],
                    ),
                    if (s.byPlatform.isNotEmpty) ...[
                      const Divider(height: 28),
                      BarList(
                        title: 'По магазин',
                        color: const Color(0xFF3B5BFE),
                        currency: s.currency,
                        items: [
                          for (final p in s.byPlatform)
                            (label: _platformLabel(p.label), value: p.amount),
                        ],
                      ),
                    ],
                    if (s.byApp.isNotEmpty) ...[
                      const SizedBox(height: 18),
                      BarList(
                        title: 'Топ приложения',
                        color: const Color(0xFF7C3AED),
                        currency: s.currency,
                        maxItems: 5,
                        items: [
                          for (final a in s.byApp)
                            (label: a.label, value: a.amount),
                        ],
                      ),
                    ],
                    if (s.byCountry.isNotEmpty) ...[
                      const SizedBox(height: 18),
                      BarList(
                        title: 'По държави',
                        color: const Color(0xFF0891B2),
                        currency: s.currency,
                        maxItems: 5,
                        items: [
                          for (final c in s.byCountry)
                            (label: c.label, value: c.amount),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            );
          },
        ),
      ],
    );
  }

  String _platformLabel(String raw) {
    switch (raw.toUpperCase()) {
      case 'APPLE':
      case 'APP_STORE':
        return 'App Store';
      case 'GOOGLE':
      case 'GOOGLE_PLAY':
        return 'Google Play';
      default:
        return raw;
    }
  }
}
