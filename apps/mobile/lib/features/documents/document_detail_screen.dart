import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';
import 'posting_card.dart';

final _documentProvider =
    FutureProvider.autoDispose.family<Document, String>((ref, id) {
  return ref.watch(documentsRepositoryProvider).get(id);
});

final _documentFileProvider =
    FutureProvider.autoDispose.family<Uint8List, String>((ref, id) {
  return ref.watch(documentsRepositoryProvider).fileBytes(id);
});

/// Детайл на документ: оригиналното изображение + статус + осчетоводяване.
class DocumentDetailScreen extends ConsumerWidget {
  const DocumentDetailScreen({super.key, required this.documentId});

  final String documentId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final doc = ref.watch(_documentProvider(documentId));

    return Scaffold(
      appBar: AppBar(title: const Text('Документ')),
      body: doc.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(
          message: 'Документът не можа да се зареди.\n$e',
          onRetry: () => ref.invalidate(_documentProvider(documentId)),
        ),
        data: (d) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
          children: [
            _OriginalImage(documentId: documentId),
            const SizedBox(height: 16),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            d.originalFilename,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                        ),
                        StatusPill(d.status.label),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '${(d.sizeBytes / 1024).round()} KB · ${d.contentType} · '
                      'източник ${d.source == 'MOBILE' ? 'мобилно' : d.source.toLowerCase()}',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.black.withValues(alpha: 0.45),
                      ),
                    ),
                    if (d.notes != null && d.notes!.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Text(d.notes!, style: const TextStyle(fontSize: 13)),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            PostingCard(documentId: documentId),
          ],
        ),
      ),
    );
  }
}

/// Оригиналната снимка, запазена на сървъра.
class _OriginalImage extends ConsumerWidget {
  const _OriginalImage({required this.documentId});

  final String documentId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final file = ref.watch(_documentFileProvider(documentId));
    return Card(
      clipBehavior: Clip.antiAlias,
      child: SizedBox(
        height: 300,
        width: double.infinity,
        child: file.when(
          loading: () => const Center(
            child: SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            ),
          ),
          error: (_, _) => Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.image_not_supported_outlined,
                    size: 36, color: Colors.black.withValues(alpha: 0.25)),
                const SizedBox(height: 8),
                const Text('Прегледът не е наличен',
                    style: TextStyle(fontSize: 12.5)),
              ],
            ),
          ),
          data: (bytes) => InteractiveViewer(
            maxScale: 4,
            child: Image.memory(bytes, fit: BoxFit.contain),
          ),
        ),
      ),
    );
  }
}
