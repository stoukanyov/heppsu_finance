import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../app/providers.dart';
import '../../core/scan/image_pipeline.dart';
import 'scan_review_screen.dart';

/// Стартира сканирането: избор на източник → снимка → смаляване → преглед.
Future<void> startScanFlow(BuildContext context, WidgetRef ref) async {
  final source = await showModalBottomSheet<ImageSource>(
    context: context,
    builder: (_) => SafeArea(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(height: 8),
          Container(
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: Colors.black.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(height: 16),
          ListTile(
            leading: const Icon(Icons.photo_camera_rounded),
            title: const Text('Снимай документ'),
            subtitle: const Text('Фактура, касова бележка'),
            onTap: () => Navigator.pop(context, ImageSource.camera),
          ),
          ListTile(
            leading: const Icon(Icons.photo_library_rounded),
            title: const Text('Избери от галерията'),
            onTap: () => Navigator.pop(context, ImageSource.gallery),
          ),
          const SizedBox(height: 8),
        ],
      ),
    ),
  );
  if (source == null || !context.mounted) return;

  final picker = ImagePicker();
  final picked = await picker.pickImage(
    source: source,
    // Първо смаляване още в plugin-а — по-малко памет преди нашата обработка.
    maxWidth: 3000,
    imageQuality: 92,
  );
  if (picked == null || !context.mounted) return;

  // Компресията върви в isolate; показваме индикатор докато трае.
  unawaited(showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => const _PreparingDialog(),
  ));

  final raw = await picked.readAsBytes();
  const pipeline = ImagePipeline();
  final draft = await pipeline.process(raw, sourceName: picked.name);

  if (!context.mounted) return;
  Navigator.of(context, rootNavigator: true).pop(); // затвори индикатора

  await Navigator.of(context).push(
    MaterialPageRoute(builder: (_) => ScanReviewScreen(draft: draft)),
  );
  ref.invalidate(documentsListProvider);
}

class _PreparingDialog extends StatelessWidget {
  const _PreparingDialog();

  @override
  Widget build(BuildContext context) {
    return const AlertDialog(
      content: Row(
        children: [
          SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2.4),
          ),
          SizedBox(width: 16),
          Expanded(child: Text('Подготвям изображението…')),
        ],
      ),
    );
  }
}
