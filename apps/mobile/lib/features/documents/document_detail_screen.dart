import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';
import 'edit_extraction_sheet.dart';
import 'posting_card.dart';

final _documentProvider = FutureProvider.autoDispose.family<Document, String>((
  ref,
  id,
) {
  return ref.watch(documentsRepositoryProvider).get(id);
});

final _documentFileProvider = FutureProvider.autoDispose
    .family<Uint8List, String>((ref, id) {
      return ref.watch(documentsRepositoryProvider).fileBytes(id);
    });

final _extractionProvider = FutureProvider.autoDispose
    .family<Extraction?, String>((ref, id) {
      return ref.watch(documentsRepositoryProvider).extraction(id);
    });

/// Детайл на документ: оригиналното изображение + статус + осчетоводяване.
class DocumentDetailScreen extends ConsumerStatefulWidget {
  const DocumentDetailScreen({super.key, required this.documentId});

  final String documentId;

  @override
  ConsumerState<DocumentDetailScreen> createState() =>
      _DocumentDetailScreenState();
}

class _DocumentDetailScreenState extends ConsumerState<DocumentDetailScreen> {
  /// Документът, върнат от потвърждаването — има предимство пред кеша,
  /// за да се види новият статус веднага.
  Document? _fresh;

  /// Сменя се след корекция, за да се пресъздаде картата с предложението
  /// (то е ново, а старото ѝ вътрешно състояние вече не важи).
  int _postingRevision = 0;

  String get documentId => widget.documentId;

  @override
  Widget build(BuildContext context) {
    final doc = ref.watch(_documentProvider(documentId));

    return Scaffold(
      appBar: AppBar(title: const Text('Документ')),
      body: doc.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(
          message: 'Документът не можа да се зареди.\n$e',
          onRetry: () => ref.invalidate(_documentProvider(documentId)),
        ),
        data: (loaded) {
          final d = _fresh ?? loaded;
          return ListView(
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
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
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
              _ExtractionCard(
                documentId: documentId,
                canEdit: d.status != DocStatus.posted &&
                    d.status != DocStatus.archived,
                onCorrected: () => setState(() => _postingRevision++),
              ),
              const SizedBox(height: 20),
              PostingCard(
                key: ValueKey(_postingRevision),
                documentId: documentId,
                onPosted: (updated) => setState(() => _fresh = updated),
              ),
            ],
          );
        },
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
                Icon(
                  Icons.image_not_supported_outlined,
                  size: 36,
                  color: Colors.black.withValues(alpha: 0.25),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Прегледът не е наличен',
                  style: TextStyle(fontSize: 12.5),
                ),
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

/// Разпознатите данни + бутон за корекция.
///
/// Корекцията е ключова за мобилния поток: без нея всеки документ, който AI
/// е разчел зле, изисква отваряне на уеб приложението.
class _ExtractionCard extends ConsumerWidget {
  const _ExtractionCard({
    required this.documentId,
    required this.canEdit,
    this.onCorrected,
  });

  final String documentId;
  final bool canEdit;

  /// Съобщава на екрана, че предложението за статия е презаредено.
  final VoidCallback? onCorrected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(_extractionProvider(documentId));

    return async.when(
      loading: () => const Card(
        child: Padding(
          padding: EdgeInsets.all(28),
          child: Center(
            child: SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2.2),
            ),
          ),
        ),
      ),
      error: (_, _) => const SizedBox.shrink(),
      data: (extraction) {
        if (extraction == null) {
          return const Card(
            child: Padding(
              padding: EdgeInsets.all(20),
              child: Text(
                'Документът още не е разпознат.',
                style: TextStyle(fontSize: 13),
              ),
            ),
          );
        }

        final fields = extraction.displayFields;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SectionTitle(
              'Разпознати данни',
              trailing: canEdit
                  ? TextButton.icon(
                      onPressed: () async {
                        final updated = await showEditExtractionSheet(
                          context,
                          documentId: documentId,
                          extraction: extraction,
                        );
                        if (updated != null) {
                          ref.invalidate(_extractionProvider(documentId));
                          ref.invalidate(_documentProvider(documentId));
                          onCorrected?.call();
                        }
                      },
                      icon: const Icon(Icons.edit_outlined, size: 17),
                      label: const Text('Поправи'),
                    )
                  : null,
            ),
            Card(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 6, 16, 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (fields.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 14),
                        child: Text('Няма разпознати полета.'),
                      )
                    else
                      for (final f in fields)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              SizedBox(
                                width: 128,
                                child: Text(
                                  f.label,
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: Colors.black.withValues(alpha: 0.55),
                                  ),
                                ),
                              ),
                              Expanded(
                                child: Text(
                                  f.value,
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w600),
                                ),
                              ),
                              if (f.isUncertain)
                                Container(
                                  margin: const EdgeInsets.only(left: 8, top: 6),
                                  width: 7,
                                  height: 7,
                                  decoration: const BoxDecoration(
                                    color: Color(0xFFD97706),
                                    shape: BoxShape.circle,
                                  ),
                                ),
                            ],
                          ),
                        ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
