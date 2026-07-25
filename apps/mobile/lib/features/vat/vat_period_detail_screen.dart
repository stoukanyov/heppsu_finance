import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/network/api_exception.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';

/// Детайл на ДДС период: клетките на справка-декларацията + Одобри / Откажи.
class VatPeriodDetailScreen extends ConsumerStatefulWidget {
  const VatPeriodDetailScreen({super.key, required this.period});

  final VatPeriodSummary period;

  @override
  ConsumerState<VatPeriodDetailScreen> createState() =>
      _VatPeriodDetailScreenState();
}

class _VatPeriodDetailScreenState extends ConsumerState<VatPeriodDetailScreen> {
  bool _busy = false;
  VatPeriodStatus? _newStatus;
  String? _error;

  VatPeriodStatus get _status => _newStatus ?? widget.period.status;

  Future<void> _approve() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Одобри ДДС периода'),
        content: Text(
          'Периодът ${widget.period.code} ще бъде приключен. '
          'След това записите в него не могат да се променят.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отказ'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Одобри'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await _run(
      () => ref.read(vatRepositoryProvider).approve(widget.period.periodId),
      VatPeriodStatus.approved,
      'Периодът е одобрен и приключен.',
    );
  }

  Future<void> _reject() async {
    final controller = TextEditingController();
    final reason = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Откажи периода'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Периодът се връща за корекция. Опиши накратко какво не е наред.',
              style: TextStyle(fontSize: 13.5),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              maxLines: 3,
              maxLength: 500,
              decoration: const InputDecoration(hintText: 'Причина (по избор)'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Назад'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFDC2626)),
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Откажи'),
          ),
        ],
      ),
    );
    if (reason == null) return;
    await _run(
      () => ref
          .read(vatRepositoryProvider)
          .reject(widget.period.periodId, reason: reason),
      VatPeriodStatus.rejected,
      'Периодът е върнат за корекция.',
    );
  }

  Future<void> _run(
    Future<void> Function() action,
    VatPeriodStatus next,
    String message,
  ) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
      if (!mounted) return;
      setState(() => _newStatus = next);
      ref.invalidate(vatPeriodsProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Действието не мина. Опитай пак.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.period;
    final declaration = ref.watch(vatDeclarationProvider(p.periodId));
    final canAct = _status == VatPeriodStatus.ready ||
        _status == VatPeriodStatus.rejected ||
        _status == VatPeriodStatus.open;

    return Scaffold(
      appBar: AppBar(title: Text('ДДС ${p.code}')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          '${p.startDate} — ${p.endDate}',
                          style: TextStyle(
                            fontSize: 13,
                            color: Colors.black.withValues(alpha: 0.55),
                          ),
                        ),
                      ),
                      StatusPill(_status.label, color: _status.color),
                    ],
                  ),
                  if (_status == VatPeriodStatus.rejected &&
                      p.rejectionReason != null &&
                      p.rejectionReason!.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: const Color(0xFFDC2626).withValues(alpha: 0.07),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.undo_rounded,
                              size: 18, color: Color(0xFFB91C1C)),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              'Върнат за корекция: ${p.rejectionReason}',
                              style: const TextStyle(
                                  fontSize: 13, color: Color(0xFFB91C1C)),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  _SummaryRow(label: 'Начислен ДДС (продажби)', value: p.outputVat),
                  _SummaryRow(label: 'ДДС кредит (покупки)', value: p.inputVat),
                  const Divider(height: 24),
                  _SummaryRow(
                    label: p.netPayable >= 0 ? 'За внасяне' : 'За възстановяване',
                    value: p.netPayable.abs(),
                    bold: true,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 22),
          const SectionTitle('Справка-декларация'),
          declaration.when(
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
                child: Text(
                  'Декларацията не можа да се зареди.\n$e',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            ),
            data: (d) {
              final filled = d.cells.where((c) => c.value != 0).toList();
              if (filled.isEmpty) {
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Row(
                      children: [
                        Icon(Icons.info_outline_rounded,
                            size: 18, color: Colors.black.withValues(alpha: 0.4)),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            d.cells.isEmpty
                                ? 'Декларацията още не е изчислена за този период.'
                                : 'Всички клетки на декларацията са нулеви — '
                                    'няма ДДС записи в регистрите за периода.',
                            style: TextStyle(
                              fontSize: 13,
                              color: Colors.black.withValues(alpha: 0.6),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              }
              return Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: Column(
                    children: [
                      for (final c in filled)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            SizedBox(
                              width: 42,
                              child: Text(
                                'кл. ${c.cell}',
                                style: TextStyle(
                                  fontSize: 11.5,
                                  fontWeight: FontWeight.w700,
                                  color: Colors.black.withValues(alpha: 0.4),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                c.label.isEmpty ? '—' : c.label,
                                style: const TextStyle(fontSize: 13),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              formatMoney(c.value),
                              style: const TextStyle(
                                  fontSize: 13, fontWeight: FontWeight.w700),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(
              _error!,
              style: const TextStyle(color: Color(0xFFDC2626), fontSize: 13),
            ),
          ],
          const SizedBox(height: 26),
          if (_status == VatPeriodStatus.approved)
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF12A150).withValues(alpha: 0.09),
                borderRadius: BorderRadius.circular(14),
              ),
              child: const Row(
                children: [
                  Icon(Icons.verified_rounded, color: Color(0xFF12A150)),
                  SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Периодът е одобрен и приключен.',
                      style: TextStyle(
                        color: Color(0xFF0E7A3D),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            )
          else if (canAct) ...[
            FilledButton.icon(
              onPressed: _busy ? null : _approve,
              icon: _busy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2.2, color: Colors.white),
                    )
                  : const Icon(Icons.check_circle_outline_rounded),
              label: const Text('Одобри и приключи'),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: _busy ? null : _reject,
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(52),
                foregroundColor: const Color(0xFFDC2626),
                side: const BorderSide(color: Color(0xFFDC2626)),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              icon: const Icon(Icons.close_rounded),
              label: const Text('Откажи — върни за корекция'),
            ),
          ],
        ],
      ),
    );
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({
    required this.label,
    required this.value,
    this.bold = false,
  });

  final String label;
  final double value;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: TextStyle(
                fontSize: bold ? 14 : 13,
                fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
                color: bold ? null : Colors.black.withValues(alpha: 0.6),
              ),
            ),
          ),
          Text(
            formatMoney(value),
            style: TextStyle(
              fontSize: bold ? 16 : 14,
              fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
