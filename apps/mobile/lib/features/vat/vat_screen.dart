import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';
import 'vat_period_detail_screen.dart';

/// Месечните ДДС отчети, готови за одобрение от телефона.
class VatScreen extends ConsumerWidget {
  const VatScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(vatPeriodsProvider);

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => ErrorView(
        message: 'Не успях да заредя ДДС периодите.\n$e',
        onRetry: () => ref.invalidate(vatPeriodsProvider),
      ),
      data: (all) {
        final periods = _ordered(all);
        if (periods.isEmpty) {
          return const EmptyView(
            message: 'Още няма ДДС периоди за преглед.',
            icon: Icons.request_quote_outlined,
          );
        }
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(vatPeriodsProvider),
          child: ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 110),
            itemCount: periods.length,
            separatorBuilder: (_, _) => const SizedBox(height: 10),
            itemBuilder: (context, i) => _VatPeriodTile(period: periods[i]),
          ),
        );
      },
    );
  }

  /// Отпред са периодите, които чакат решение; празните бъдещи месеци
  /// не се показват изобщо — само шум са в списък за одобрения.
  List<VatPeriodSummary> _ordered(List<VatPeriodSummary> all) {
    int rank(VatPeriodStatus s) => switch (s) {
          VatPeriodStatus.ready => 0,
          VatPeriodStatus.rejected => 1,
          VatPeriodStatus.approved => 2,
          VatPeriodStatus.open => 3,
        };

    final visible = all.where((p) {
      final isEmptyOpen = p.status == VatPeriodStatus.open &&
          p.outputVat == 0 &&
          p.inputVat == 0;
      return !isEmptyOpen;
    }).toList();

    visible.sort((a, b) {
      final byStatus = rank(a.status).compareTo(rank(b.status));
      if (byStatus != 0) return byStatus;
      return b.startDate.compareTo(a.startDate); // най-новите първи
    });
    return visible;
  }
}

class _VatPeriodTile extends StatelessWidget {
  const _VatPeriodTile({required this.period});

  final VatPeriodSummary period;

  Color get _statusColor {
    switch (period.status) {
      case VatPeriodStatus.approved:
        return const Color(0xFF12A150);
      case VatPeriodStatus.ready:
        return const Color(0xFFD97706);
      case VatPeriodStatus.rejected:
        return const Color(0xFFDC2626);
      case VatPeriodStatus.open:
        return const Color(0xFF6366F1);
    }
  }

  @override
  Widget build(BuildContext context) {
    final payable = period.netPayable;
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => VatPeriodDetailScreen(period: period),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      period.code,
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                  ),
                  StatusPill(period.status.label, color: _statusColor),
                ],
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  _Metric(
                    label: 'Начислен ДДС',
                    value: formatMoney(period.outputVat),
                  ),
                  _Metric(
                    label: 'ДДС кредит',
                    value: formatMoney(period.inputVat),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: (payable >= 0
                          ? const Color(0xFFDC2626)
                          : const Color(0xFF12A150))
                      .withValues(alpha: 0.07),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Text(
                      payable >= 0 ? 'За внасяне' : 'За възстановяване',
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.black.withValues(alpha: 0.6),
                      ),
                    ),
                    const Spacer(),
                    Text(
                      formatMoney(payable.abs()),
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                        color: payable >= 0
                            ? const Color(0xFFB91C1C)
                            : const Color(0xFF0E7A3D),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
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
          const SizedBox(height: 2),
          Text(
            value,
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}
