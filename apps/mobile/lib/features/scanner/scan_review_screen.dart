import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/network/api_exception.dart';
import '../../core/queue/scan_queue_db.dart';
import '../../core/queue/upload_queue.dart';
import '../../core/scan/image_pipeline.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';
import '../documents/edit_extraction_sheet.dart';
import '../documents/posting_card.dart';

/// Преглед на сканиран документ.
///
/// Самото качване се прави от опашката (`UploadQueue`) — този екран само
/// следи докъде е стигнала и показва резултата. Така сканът не зависи от
/// това дали екранът е отворен: ако няма мрежа, той чака в опашката.
class ScanReviewScreen extends ConsumerStatefulWidget {
  const ScanReviewScreen({
    super.key,
    required this.draft,
    required this.queueItemId,
  });

  final ScanDraft draft;
  final String queueItemId;

  @override
  ConsumerState<ScanReviewScreen> createState() => _ScanReviewScreenState();
}

class _ScanReviewScreenState extends ConsumerState<ScanReviewScreen> {
  ScanQueueItem? _item;
  ScanResult? _result;
  String? _loadError;
  bool _loadingResult = false;

  UploadQueue get _queue => ref.read(uploadQueueProvider);

  @override
  void initState() {
    super.initState();
    _queue.revision.addListener(_refresh);
    _refresh();
  }

  @override
  void dispose() {
    _queue.revision.removeListener(_refresh);
    super.dispose();
  }

  Future<void> _refresh() async {
    final item = await _queue.byId(widget.queueItemId);
    if (!mounted) return;
    setState(() => _item = item);

    // Щом сървърът е приел скана, дърпаме разпознатото и предложението.
    if (item?.status == QueueStatus.uploaded &&
        item?.serverDocumentId != null &&
        _result == null &&
        !_loadingResult) {
      await _loadResult(item!.serverDocumentId!);
    }
  }

  Future<void> _loadResult(String documentId) async {
    setState(() {
      _loadingResult = true;
      _loadError = null;
    });
    try {
      final repo = ref.read(documentsRepositoryProvider);
      // `propose-posting` е идемпотентно — връща вече създадената чернова.
      final document = await repo.get(documentId);
      final extraction = await repo.extraction(documentId);
      final posting = await repo.proposePosting(documentId);
      if (!mounted) return;
      setState(() {
        _result = ScanResult(
          document: document,
          extraction: extraction ??
              const Extraction(
                id: '',
                documentId: '',
                model: '',
                data: {},
              ),
          posting: posting,
        );
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _loadError = e.message);
    } catch (_) {
      if (mounted) setState(() => _loadError = 'Данните не се заредиха.');
    } finally {
      if (mounted) setState(() => _loadingResult = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = _item;

    return Scaffold(
      appBar: AppBar(title: const Text('Сканиран документ')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          _ImagePreview(draft: widget.draft),
          const SizedBox(height: 20),
          if (item == null)
            const _UploadingCard(message: 'Подготвям…')
          else if (_result != null)
            _ResultSection(result: _result!)
          else
            switch (item.status) {
              QueueStatus.pending => const _QueuedCard(),
              QueueStatus.uploading =>
                const _UploadingCard(message: 'Изпращам и разпознавам…'),
              QueueStatus.uploaded => _UploadingCard(
                  message: _loadError ?? 'Зареждам разпознатото…',
                ),
              QueueStatus.failedRetryable => _RetryingCard(item: item),
              QueueStatus.duplicate => const _FailedCard(
                  message: 'Този документ вече е качен по-рано.',
                ),
              QueueStatus.failedPermanent => _FailedCard(
                  message: item.lastError ?? 'Качването не мина.',
                  onRetry: () => _queue.retryNow(item.id),
                ),
            },
        ],
      ),
    );
  }
}

/// Сканът е записан локално и чака мрежа — най-важното съобщение в целия
/// поток, защото казва на потребителя, че нищо не се е загубило.
class _QueuedCard extends StatelessWidget {
  const _QueuedCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(9),
              decoration: BoxDecoration(
                color: const Color(0xFFD97706).withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(Icons.cloud_off_rounded,
                  color: Color(0xFFD97706), size: 20),
            ),
            const SizedBox(width: 14),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Записан на телефона',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  SizedBox(height: 3),
                  Text(
                    'Ще се изпрати автоматично при първа връзка с мрежата. '
                    'Може да затвориш екрана.',
                    style: TextStyle(fontSize: 12.5, color: Colors.black54),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Неуспешен опит, но ще има следващ.
class _RetryingCard extends StatelessWidget {
  const _RetryingCard({required this.item});

  final ScanQueueItem item;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            const Icon(Icons.schedule_rounded,
                color: Color(0xFFD97706), size: 30),
            const SizedBox(height: 12),
            Text(
              'Опит ${item.attempts} не мина — ще опитам пак автоматично.',
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            if (item.lastError != null && item.lastError!.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                item.lastError!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 12.5, color: Colors.black54),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Смаленото изображение + колко трафик е спестен.
class _ImagePreview extends StatelessWidget {
  const _ImagePreview({required this.draft});

  final ScanDraft draft;

  String _kb(int bytes) => '${(bytes / 1024).round()} KB';

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 280),
            child: Image.memory(
              draft.bytes,
              fit: BoxFit.contain,
              width: double.infinity,
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Icon(Icons.compress_rounded,
                    size: 18, color: Colors.black.withValues(alpha: 0.45)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Смалено: ${_kb(draft.originalBytes)} → ${_kb(draft.sizeBytes)}'
                    ' (−${(draft.savedRatio * 100).round()}%)',
                    style: TextStyle(
                      fontSize: 12.5,
                      color: Colors.black.withValues(alpha: 0.55),
                    ),
                  ),
                ),
                Text(
                  'Оригиналът се пази в архива',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: Colors.black.withValues(alpha: 0.4),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _UploadingCard extends StatelessWidget {
  const _UploadingCard({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            const SizedBox(
              width: 26,
              height: 26,
              child: CircularProgressIndicator(strokeWidth: 2.6),
            ),
            const SizedBox(height: 16),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 4),
            const Text(
              'Сървърът извлича данните и подготвя счетоводната статия.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12.5, color: Colors.black54),
            ),
          ],
        ),
      ),
    );
  }
}

class _FailedCard extends StatelessWidget {
  const _FailedCard({required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            const Icon(Icons.error_outline_rounded,
                color: Color(0xFFDC2626), size: 32),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Опитай пак'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Разпознати данни + предложена статия.
class _ResultSection extends StatefulWidget {
  const _ResultSection({required this.result});

  final ScanResult result;

  @override
  State<_ResultSection> createState() => _ResultSectionState();
}

class _ResultSectionState extends State<_ResultSection> {
  /// Обновеният документ след осчетоводяване (сменя статуса без ново зареждане).
  Document? _fresh;

  /// Резултатът след ръчна корекция — заменя първоначалния.
  ScanResult? _corrected;

  /// Пресъздава картата с предложението, защото след корекция то е ново.
  int _postingRevision = 0;

  Future<void> _edit(BuildContext context, ScanResult current) async {
    final updated = await showEditExtractionSheet(
      context,
      documentId: current.document.id,
      extraction: current.extraction,
    );
    if (updated != null && mounted) {
      setState(() {
        _corrected = updated;
        _fresh = updated.document;
        _postingRevision++;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final result = _corrected ?? widget.result;
    final extraction = result.extraction;
    final fields = extraction.displayFields;
    final confidence = extraction.confidence;
    final document = _fresh ?? result.document;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Expanded(child: SectionTitle('Разпознати данни')),
            if (document.status != DocStatus.posted)
              TextButton.icon(
                onPressed: () => _edit(context, result),
                icon: const Icon(Icons.edit_outlined, size: 17),
                label: const Text('Поправи'),
              ),
            StatusPill(document.status.label),
          ],
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
                    child: Text('Не бяха разпознати данни от документа.'),
                  )
                else
                  for (final f in fields) _DataRow(field: f),
                if (confidence != null) ...[
                  const Divider(height: 22),
                  Row(
                    children: [
                      Icon(
                        confidence >= 0.75
                            ? Icons.check_circle_outline_rounded
                            : Icons.info_outline_rounded,
                        size: 16,
                        color: confidence >= 0.75
                            ? const Color(0xFF12A150)
                            : const Color(0xFFD97706),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          confidence >= 0.75
                              ? 'Увереност ${(confidence * 100).round()}%'
                              : 'Ниска увереност ${(confidence * 100).round()}% — провери данните',
                          style: TextStyle(
                            fontSize: 12.5,
                            color: Colors.black.withValues(alpha: 0.55),
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        PostingCard(
          key: ValueKey(_postingRevision),
          documentId: result.document.id,
          initialProposal: result.posting,
          onPosted: (updated) => setState(() => _fresh = updated),
        ),
      ],
    );
  }
}

class _DataRow extends StatelessWidget {
  const _DataRow({required this.field});

  final ExtractedField field;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 9),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 128,
            child: Text(
              field.label,
              style: TextStyle(
                fontSize: 13,
                color: Colors.black.withValues(alpha: 0.55),
              ),
            ),
          ),
          Expanded(
            child: Text(
              field.value,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          // Точка до полетата, на които AI е по-малко сигурен.
          if (field.isUncertain)
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
    );
  }
}
