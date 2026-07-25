import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/network/api_exception.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';

/// Предложената от AI счетоводна статия + потвърждение от потребителя.
///
/// Принципът на системата е „AI предлага, човек потвърждава" — затова тук
/// статията се показва като чернова и се осчетоводява само след натискане
/// на „Потвърди осчетоводяване".
class PostingCard extends ConsumerStatefulWidget {
  const PostingCard({
    super.key,
    required this.documentId,
    this.initialProposal,
  });

  final String documentId;

  /// Предложението, ако вече е дошло със scan-а; иначе се заявява при показване.
  final PostingProposal? initialProposal;

  @override
  ConsumerState<PostingCard> createState() => _PostingCardState();
}

class _PostingCardState extends ConsumerState<PostingCard> {
  PostingProposal? _proposal;
  bool _loading = false;
  bool _confirming = false;
  String? _error;
  JournalEntry? _posted;

  @override
  void initState() {
    super.initState();
    _proposal = widget.initialProposal;
    if (_proposal == null) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final p =
          await ref.read(documentsRepositoryProvider).proposePosting(widget.documentId);
      if (!mounted) return;
      setState(() => _proposal = p);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Неуспешна връзка със сървъра.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _confirm() async {
    final entry = _proposal?.entry;
    if (entry == null) return;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Потвърди осчетоводяване'),
        content: Text(
          'Статията ще бъде осчетоводена и няма да може да се редактира — '
          'само сторнирана.\n\nОбщо: ${formatMoney(entry.totalDebit, entry.currency)}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Отказ'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Осчетоводи'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    setState(() {
      _confirming = true;
      _error = null;
    });
    try {
      final result = await ref
          .read(documentsRepositoryProvider)
          .confirmPosting(widget.documentId);
      if (!mounted) return;
      setState(() => _posted = result.entry);
      ref.invalidate(documentsListProvider);
      widget.onPosted?.call(result.document);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Осчетоводено${result.entry.entryNumber != null ? ' — статия № ${result.entry.entryNumber}' : ''}.',
          ),
          behavior: SnackBarBehavior.floating,
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Осчетоводяването не мина. Опитай пак.');
    } finally {
      if (mounted) setState(() => _confirming = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Card(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Center(
            child: SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            ),
          ),
        ),
      );
    }

    final proposal = _proposal;
    if (proposal == null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              Text(_error ?? 'Няма предложение за осчетоводяване.',
                  textAlign: TextAlign.center),
              const SizedBox(height: 14),
              OutlinedButton.icon(
                onPressed: _load,
                icon: const Icon(Icons.auto_awesome_rounded),
                label: const Text('Предложи статия'),
              ),
            ],
          ),
        ),
      );
    }

    final entry = _posted ?? proposal.entry;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionTitle(
          'Осчетоводяване',
          trailing: entry != null && entry.isPosted
              ? const StatusPill('Осчетоводен')
              : StatusPill(
                  'Предложение',
                  color: Theme.of(context).colorScheme.primary,
                ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (proposal.rationale.isNotEmpty) ...[
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.auto_awesome_rounded,
                          size: 17,
                          color: Theme.of(context).colorScheme.primary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          proposal.rationale,
                          style: TextStyle(
                            fontSize: 13,
                            height: 1.35,
                            color: Colors.black.withValues(alpha: 0.65),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                ],
                if (entry == null)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      'Не може да се предложи статия от този документ. '
                      'Довърши го от уеб приложението.',
                    ),
                  )
                else
                  _EntryTable(entry: entry),
                if (proposal.warnings.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  for (final w in proposal.warnings)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.warning_amber_rounded,
                              size: 16, color: Color(0xFFD97706)),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              w,
                              style: const TextStyle(
                                fontSize: 12.5,
                                color: Color(0xFFB45309),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _error!,
                    style: const TextStyle(color: Color(0xFFDC2626), fontSize: 13),
                  ),
                ],
                if (entry != null && !entry.isPosted) ...[
                  const SizedBox(height: 18),
                  FilledButton.icon(
                    onPressed: _confirming ? null : _confirm,
                    icon: _confirming
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                                strokeWidth: 2.2, color: Colors.white),
                          )
                        : const Icon(Icons.check_circle_outline_rounded),
                    label: Text(
                      _confirming ? 'Осчетоводявам…' : 'Потвърди осчетоводяване',
                    ),
                  ),
                ],
                if (entry != null && entry.isPosted) ...[
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFF12A150).withValues(alpha: 0.09),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.verified_rounded,
                            color: Color(0xFF12A150), size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            entry.entryNumber != null
                                ? 'Осчетоводено — статия № ${entry.entryNumber}'
                                : 'Осчетоводено',
                            style: const TextStyle(
                              color: Color(0xFF0E7A3D),
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// Редовете на статията — Дт/Кт по сметки.
class _EntryTable extends ConsumerWidget {
  const _EntryTable({required this.entry});

  final JournalEntry entry;

  /// „602 · Разходи за външни услуги" — от кеширания сметкоплан, ако редът
  /// не носи кода сам.
  String _accountLabel(JournalLine line, Map<String, Account>? accounts) {
    final parts = [line.accountCode, line.accountName]
        .whereType<String>()
        .where((s) => s.isNotEmpty)
        .toList();
    if (parts.isNotEmpty) return parts.join(' · ');

    final a = accounts?[line.accountId];
    if (a != null) return '${a.code} · ${a.name}';
    return 'Сметка';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accounts = ref.watch(accountsByIdProvider).valueOrNull;
    return Column(
      children: [
        for (final line in entry.lines)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 7),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: (line.debit > 0
                            ? const Color(0xFF3B5BFE)
                            : const Color(0xFF12A150))
                        .withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    line.debit > 0 ? 'Дт' : 'Кт',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: line.debit > 0
                          ? const Color(0xFF3B5BFE)
                          : const Color(0xFF12A150),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _accountLabel(line, accounts),
                        style: const TextStyle(
                            fontSize: 13.5, fontWeight: FontWeight.w600),
                      ),
                      if (line.description != null &&
                          line.description!.isNotEmpty)
                        Text(
                          line.description!,
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.black.withValues(alpha: 0.45),
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  formatMoney(
                    line.debit > 0 ? line.debit : line.credit,
                    entry.currency,
                  ),
                  style: const TextStyle(
                      fontSize: 13.5, fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
        const Divider(height: 22),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              'Общо',
              style: TextStyle(
                fontSize: 13,
                color: Colors.black.withValues(alpha: 0.55),
              ),
            ),
            Text(
              formatMoney(entry.totalDebit, entry.currency),
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
            ),
          ],
        ),
      ],
    );
  }
}
