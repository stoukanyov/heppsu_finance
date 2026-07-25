import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/network/api_exception.dart';
import '../../core/scan/image_pipeline.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';
import '../documents/posting_card.dart';

/// Етапи на екрана: качване → резултат (данни + предложение) → потвърдено.
enum _Phase { uploading, done, failed }

/// Преглед и качване на сканиран документ.
///
/// Показва смаленото изображение, изпраща го към `POST /documents/scan`
/// и веднага визуализира разпознатите данни и предложената счетоводна статия.
class ScanReviewScreen extends ConsumerStatefulWidget {
  const ScanReviewScreen({super.key, required this.draft});

  final ScanDraft draft;

  @override
  ConsumerState<ScanReviewScreen> createState() => _ScanReviewScreenState();
}

class _ScanReviewScreenState extends ConsumerState<ScanReviewScreen> {
  _Phase _phase = _Phase.uploading;
  ScanResult? _result;
  String? _error;
  final _note = TextEditingController();

  @override
  void initState() {
    super.initState();
    _upload();
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _upload() async {
    setState(() {
      _phase = _Phase.uploading;
      _error = null;
    });
    try {
      final res = await ref.read(documentsRepositoryProvider).submitScan(
            bytes: widget.draft.bytes,
            filename: widget.draft.filename,
            contentType: widget.draft.contentType,
            note: _note.text.trim(),
          );
      if (!mounted) return;
      setState(() {
        _result = res;
        _phase = _Phase.done;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.isDuplicate
            ? 'Този документ вече е качен.'
            : e.message;
        _phase = _Phase.failed;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Няма връзка със сървъра. Опитай пак.';
        _phase = _Phase.failed;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Сканиран документ')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
        children: [
          _ImagePreview(draft: widget.draft),
          const SizedBox(height: 20),
          switch (_phase) {
            _Phase.uploading => const _UploadingCard(),
            _Phase.failed => _FailedCard(message: _error!, onRetry: _upload),
            _Phase.done => _ResultSection(result: _result!),
          },
        ],
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
  const _UploadingCard();

  @override
  Widget build(BuildContext context) {
    return const Card(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          children: [
            SizedBox(
              width: 26,
              height: 26,
              child: CircularProgressIndicator(strokeWidth: 2.6),
            ),
            SizedBox(height: 16),
            Text(
              'Изпращам и разпознавам…',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            SizedBox(height: 4),
            Text(
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
  const _FailedCard({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

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
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Опитай пак'),
            ),
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

  @override
  Widget build(BuildContext context) {
    final result = widget.result;
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
