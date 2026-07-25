import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../../data/repositories.dart';
import '../network/api_exception.dart';
import '../scan/image_pipeline.dart';
import 'scan_queue_db.dart';

/// Изпраща чакащите сканове, когато има мрежа.
///
/// Сканът се записва локално веднага и се качва при първа възможност — така
/// снимка, направена без покритие, не се губи. Опашката се обработва при старт
/// на приложението, при връщане на преден план и при поява на мрежа.
class UploadQueue {
  UploadQueue({
    required this.db,
    required this.repository,
    Connectivity? connectivity,
  }) : _connectivity = connectivity ?? Connectivity();

  final ScanQueueDb db;

  /// Взима се лениво — опашката преживява смяна на активната компания.
  final DocumentsRepository Function() repository;
  final Connectivity _connectivity;

  StreamSubscription<List<ConnectivityResult>>? _netSub;
  bool _running = false;

  /// Известява при промяна, за да се опресни екранът на опашката.
  final ValueNotifier<int> revision = ValueNotifier(0);

  static const _baseBackoff = Duration(seconds: 5);
  static const _maxBackoff = Duration(minutes: 15);
  static const _maxAttempts = 12;

  /// Започва да следи мрежата. Извиква се веднъж, след вход.
  void start() {
    _netSub ??= _connectivity.onConnectivityChanged.listen((results) {
      final online = results.any((r) => r != ConnectivityResult.none);
      if (online) unawaited(process());
    });
    unawaited(process());
  }

  Future<void> dispose() async {
    await _netSub?.cancel();
    _netSub = null;
  }

  /// Добавя нов скан към опашката. Връща записа.
  ///
  /// Ако същият файл (по sha256) вече чака, не добавя втори — това пази от
  /// двойно натискане и от повторно сканиране на същия документ.
  Future<ScanQueueItem> enqueue({
    required ScanDraft draft,
    required String companyId,
    String? note,
  }) async {
    final existing = await db.findBySha(draft.sha256);
    if (existing != null && !existing.status.isTerminal) return existing;

    final path = await _persist(draft);
    final item = ScanQueueItem(
      id: _uuid(),
      filePath: path,
      filename: draft.filename,
      contentType: draft.contentType,
      sha256: draft.sha256,
      sizeBytes: draft.sizeBytes,
      companyId: companyId,
      status: QueueStatus.pending,
      attempts: 0,
      createdAt: DateTime.now(),
      note: note,
    );
    await db.insert(item);
    revision.value++;
    unawaited(process());
    return item;
  }

  /// Обработва всички готови записи. Безопасно е да се вика паралелно —
  /// повторните извиквания се игнорират, докато тече обработка.
  Future<void> process() async {
    if (_running) return;
    _running = true;
    try {
      for (final item in await db.due()) {
        await _upload(item);
      }
    } finally {
      _running = false;
      revision.value++;
    }
  }

  /// Ръчен повторен опит от екрана — нулира изчакването.
  Future<void> retryNow(String id) async {
    final matches = (await db.all()).where((i) => i.id == id);
    if (matches.isEmpty) return;
    final item = matches.first;
    await db.update(item.copyWith(
      status: QueueStatus.pending,
      attempts: 0,
      nextAttemptAt: DateTime.fromMillisecondsSinceEpoch(0),
      lastError: '',
    ));
    revision.value++;
    await process();
  }

  Future<void> remove(String id) async {
    await db.remove(id);
    revision.value++;
  }

  Future<int> purgeCompleted() async {
    final n = await db.purgeCompleted();
    revision.value++;
    return n;
  }

  Future<void> clear() async {
    await db.clear();
    revision.value++;
  }

  Future<List<ScanQueueItem>> items() => db.all();
  Future<int> pendingCount() => db.pendingCount();

  Future<ScanQueueItem?> byId(String id) async {
    final matches = (await db.all()).where((i) => i.id == id);
    return matches.isEmpty ? null : matches.first;
  }

  // ------------------------------------------------------------------ вътрешно

  Future<void> _upload(ScanQueueItem item) async {
    final file = File(item.filePath);
    if (!file.existsSync()) {
      // Файлът е изчезнал (изчистен кеш) — записът няма смисъл.
      await db.update(item.copyWith(
        status: QueueStatus.failedPermanent,
        lastError: 'Локалният файл липсва.',
      ));
      return;
    }

    await db.update(item.copyWith(status: QueueStatus.uploading));
    revision.value++;

    try {
      final result = await repository().submitScan(
        bytes: await file.readAsBytes(),
        filename: item.filename,
        contentType: item.contentType,
        note: item.note,
        companyId: item.companyId,
      );
      await db.update(item.copyWith(
        status: QueueStatus.uploaded,
        serverDocumentId: result.document.id,
        lastError: '',
      ));
      // Оригиналът вече е на сървъра — не го държим и на телефона.
      await file.delete().catchError((_) => file);
    } on ApiException catch (e) {
      await _handleFailure(item, e);
    } catch (e) {
      // Мрежова грешка/таймаут — подлежи на повторен опит.
      await _handleFailure(item, ApiException(0, e.toString()));
    }
    revision.value++;
  }

  Future<void> _handleFailure(ScanQueueItem item, ApiException e) async {
    if (e.isDuplicate) {
      await db.update(item.copyWith(
        status: QueueStatus.duplicate,
        lastError: 'Документът вече съществува на сървъра.',
      ));
      return;
    }

    final attempts = item.attempts + 1;

    // 4xx означава, че заявката няма да мине и при повторение.
    if (!e.isRetryable || attempts >= _maxAttempts) {
      await db.update(item.copyWith(
        status: QueueStatus.failedPermanent,
        attempts: attempts,
        lastError: e.message,
      ));
      return;
    }

    await db.update(item.copyWith(
      status: QueueStatus.failedRetryable,
      attempts: attempts,
      nextAttemptAt: DateTime.now().add(backoffFor(attempts)),
      lastError: e.message,
    ));
  }

  /// Експоненциално изчакване с таван и малко разсейване, за да не тръгнат
  /// всички записи едновременно след връщане на мрежата.
  static Duration backoffFor(int attempts) {
    final exponential = _baseBackoff * pow(2, attempts - 1).toDouble();
    final capped = exponential > _maxBackoff ? _maxBackoff : exponential;
    final jitter = Random().nextInt(1 + capped.inSeconds ~/ 4);
    return capped + Duration(seconds: jitter);
  }

  /// Премества байтовете в постоянна папка — временният файл на камерата
  /// може да бъде изтрит от системата преди да сме качили.
  Future<String> _persist(ScanDraft draft) async {
    final dir = await _queueDir();
    final path = '${dir.path}/${draft.sha256}.jpg';
    await File(path).writeAsBytes(draft.bytes, flush: true);
    return path;
  }

  static Future<Directory> _queueDir() async {
    final base = await getApplicationSupportDirectory();
    final dir = Directory('${base.path}/scan_queue');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  static String _uuid() {
    final r = Random.secure();
    String hex(int n) =>
        List.generate(n, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0'))
            .join();
    return '${hex(4)}-${hex(2)}-${hex(2)}-${hex(2)}-${hex(6)}';
  }
}
