import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/queue/scan_queue_db.dart';
import '../common/widgets.dart';

/// Опашка за качване: какво чака, какво се е провалило, ръчен повторен опит.
class QueueScreen extends ConsumerWidget {
  const QueueScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(queueItemsProvider);
    final queue = ref.read(uploadQueueProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Опашка за качване'),
        actions: [
          IconButton(
            tooltip: 'Изчисти приключилите',
            onPressed: () async {
              final n = await queue.purgeCompleted();
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(n == 0
                      ? 'Няма какво да се чисти.'
                      : 'Изчистени $n записа.'),
                  behavior: SnackBarBehavior.floating,
                ),
              );
            },
            icon: const Icon(Icons.cleaning_services_outlined),
          ),
        ],
      ),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(message: 'Опашката не се зареди.\n$e'),
        data: (items) {
          if (items.isEmpty) {
            return const EmptyView(
              message: 'Опашката е празна — всичко е изпратено.',
              icon: Icons.cloud_done_outlined,
            );
          }
          return RefreshIndicator(
            onRefresh: () async => queue.process(),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: items.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, i) => _QueueTile(item: items[i]),
            ),
          );
        },
      ),
    );
  }
}

class _QueueTile extends ConsumerWidget {
  const _QueueTile({required this.item});

  final ScanQueueItem item;

  Color get _color {
    switch (item.status) {
      case QueueStatus.uploaded:
        return const Color(0xFF12A150);
      case QueueStatus.failedPermanent:
        return const Color(0xFFDC2626);
      case QueueStatus.failedRetryable:
        return const Color(0xFFD97706);
      case QueueStatus.duplicate:
        return const Color(0xFF6366F1);
      case QueueStatus.pending:
      case QueueStatus.uploading:
        return const Color(0xFF3B5BFE);
    }
  }

  IconData get _icon {
    switch (item.status) {
      case QueueStatus.uploaded:
        return Icons.cloud_done_rounded;
      case QueueStatus.failedPermanent:
        return Icons.error_outline_rounded;
      case QueueStatus.failedRetryable:
        return Icons.schedule_rounded;
      case QueueStatus.duplicate:
        return Icons.copy_all_rounded;
      case QueueStatus.uploading:
        return Icons.cloud_upload_rounded;
      case QueueStatus.pending:
        return Icons.cloud_off_rounded;
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final queue = ref.read(uploadQueueProvider);
    final canRetry = item.status == QueueStatus.failedPermanent ||
        item.status == QueueStatus.failedRetryable;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(9),
                  decoration: BoxDecoration(
                    color: _color.withValues(alpha: 0.11),
                    borderRadius: BorderRadius.circular(11),
                  ),
                  child: Icon(_icon, color: _color, size: 19),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.filename,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${(item.sizeBytes / 1024).round()} KB'
                        '${item.attempts > 0 ? ' · опити: ${item.attempts}' : ''}',
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.black.withValues(alpha: 0.45),
                        ),
                      ),
                    ],
                  ),
                ),
                StatusPill(item.status.label, color: _color),
              ],
            ),
            if (item.lastError != null && item.lastError!.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(
                item.lastError!,
                style: const TextStyle(fontSize: 12, color: Color(0xFFB45309)),
              ),
            ],
            if (canRetry) ...[
              const SizedBox(height: 10),
              Row(
                children: [
                  TextButton.icon(
                    onPressed: () => queue.retryNow(item.id),
                    icon: const Icon(Icons.refresh_rounded, size: 18),
                    label: const Text('Опитай сега'),
                  ),
                  const Spacer(),
                  TextButton.icon(
                    onPressed: () => _confirmDelete(context, ref),
                    style: TextButton.styleFrom(
                      foregroundColor: const Color(0xFFDC2626),
                    ),
                    icon: const Icon(Icons.delete_outline_rounded, size: 18),
                    label: const Text('Изтрий'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Изтрий от опашката'),
        content: const Text(
          'Сканът ще бъде изтрит от телефона и няма да бъде изпратен. '
          'Това не може да се върне.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Назад'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFDC2626)),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Изтрий'),
          ),
        ],
      ),
    );
    if (ok == true) await ref.read(uploadQueueProvider).remove(item.id);
  }
}
