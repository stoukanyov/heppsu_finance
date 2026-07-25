import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';
import 'document_detail_screen.dart';

/// Списък със сканираните документи и техния статус.
class DocumentsScreen extends ConsumerWidget {
  const DocumentsScreen({super.key});

  static const _filters = <(String, DocStatus?)>[
    ('Всички', null),
    ('За проверка', DocStatus.needsReview),
    ('Предложени', DocStatus.proposed),
    ('Осчетоводени', DocStatus.posted),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(documentsListProvider);
    final active = ref.watch(documentsFilterProvider);

    return Column(
      children: [
        SizedBox(
          height: 52,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            itemCount: _filters.length,
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemBuilder: (context, i) {
              final (label, status) = _filters[i];
              return ChoiceChip(
                label: Text(label),
                selected: active == status,
                onSelected: (_) =>
                    ref.read(documentsFilterProvider.notifier).state = status,
              );
            },
          ),
        ),
        Expanded(
          child: async.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => ErrorView(
              message: 'Не успях да заредя документите.\n$e',
              onRetry: () => ref.invalidate(documentsListProvider),
            ),
            data: (docs) {
              if (docs.isEmpty) {
                return const EmptyView(
                  message: 'Няма документи.\nНатисни „Сканирай", за да добавиш.',
                  icon: Icons.document_scanner_outlined,
                );
              }
              return RefreshIndicator(
                onRefresh: () async => ref.invalidate(documentsListProvider),
                child: ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 110),
                  itemCount: docs.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, i) => _DocumentTile(doc: docs[i]),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _DocumentTile extends StatelessWidget {
  const _DocumentTile({required this.doc});

  final Document doc;

  static const _typeLabels = <String, String>{
    'INVOICE_PURCHASE': 'Фактура (покупка)',
    'INVOICE_SALE': 'Фактура (продажба)',
    'CREDIT_NOTE': 'Кредитно известие',
    'DEBIT_NOTE': 'Дебитно известие',
    'RECEIPT': 'Касова бележка',
    'BANK_STATEMENT': 'Банково извлечение',
    'CONTRACT': 'Договор',
    'OTHER': 'Друг',
    'UNKNOWN': 'Неопределен',
  };

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => DocumentDetailScreen(documentId: doc.id),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: Theme.of(context)
                      .colorScheme
                      .primary
                      .withValues(alpha: 0.09),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  doc.contentType.contains('pdf')
                      ? Icons.picture_as_pdf_rounded
                      : Icons.image_rounded,
                  color: Theme.of(context).colorScheme.primary,
                  size: 22,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _typeLabels[doc.docType] ?? doc.docType,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      '${doc.originalFilename} · ${(doc.sizeBytes / 1024).round()} KB',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.black.withValues(alpha: 0.45),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              StatusPill(doc.status.label),
            ],
          ),
        ),
      ),
    );
  }
}
