import 'package:flutter_test/flutter_test.dart';
import 'package:heppsu_finance/core/queue/scan_queue_db.dart';
import 'package:heppsu_finance/core/queue/upload_queue.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Тестовете карат sqflite да върви на десктоп през FFI.
void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  /// `inMemoryDatabasePath` се споделя в рамките на процеса, затова я трием
  /// преди всяко отваряне — иначе тестовете си виждат данните.
  Future<ScanQueueDb> freshDb() async {
    await databaseFactoryFfi.deleteDatabase(inMemoryDatabasePath);
    final raw = await databaseFactoryFfi.openDatabase(inMemoryDatabasePath);
    await ScanQueueDb.createSchemaFor(raw);
    return ScanQueueDb(database: raw);
  }

  ScanQueueItem item({
    required String id,
    QueueStatus status = QueueStatus.pending,
    int attempts = 0,
    DateTime? nextAttemptAt,
    String sha = 'abc',
  }) =>
      ScanQueueItem(
        id: id,
        filePath: '/tmp/$id.jpg',
        filename: '$id.jpg',
        contentType: 'image/jpeg',
        sha256: sha,
        sizeBytes: 1024,
        companyId: 'company-1',
        status: status,
        attempts: attempts,
        createdAt: DateTime(2026, 7, 25),
        nextAttemptAt: nextAttemptAt,
      );

  group('Опашка — съхранение', () {
    test('записва и връща скан', () async {
      final db = await freshDb();
      await db.insert(item(id: 'a'));

      final all = await db.all();
      expect(all, hasLength(1));
      expect(all.first.id, 'a');
      expect(all.first.status, QueueStatus.pending);
      expect(all.first.companyId, 'company-1');
    });

    test('брои само незавършените', () async {
      final db = await freshDb();
      await db.insert(item(id: 'a', status: QueueStatus.pending, sha: '1'));
      await db.insert(item(id: 'b', status: QueueStatus.uploading, sha: '2'));
      await db.insert(item(id: 'c', status: QueueStatus.failedRetryable, sha: '3'));
      await db.insert(item(id: 'd', status: QueueStatus.uploaded, sha: '4'));
      await db.insert(item(id: 'e', status: QueueStatus.duplicate, sha: '5'));

      expect(await db.pendingCount(), 3);
    });

    test('за изпращане са само чакащите и тези с изтекъл backoff', () async {
      final db = await freshDb();
      await db.insert(item(id: 'ready', sha: '1'));
      await db.insert(item(
        id: 'waiting',
        status: QueueStatus.failedRetryable,
        nextAttemptAt: DateTime.now().add(const Duration(minutes: 10)),
        sha: '2',
      ));
      await db.insert(item(
        id: 'due',
        status: QueueStatus.failedRetryable,
        nextAttemptAt: DateTime.now().subtract(const Duration(minutes: 1)),
        sha: '3',
      ));
      await db.insert(item(id: 'done', status: QueueStatus.uploaded, sha: '4'));

      final due = (await db.due()).map((i) => i.id).toList();
      expect(due, containsAll(['ready', 'due']));
      expect(due, isNot(contains('waiting')), reason: 'backoff-ът още тече');
      expect(due, isNot(contains('done')));
    });

    test('намира по sha256 — пази от двойно добавяне', () async {
      final db = await freshDb();
      await db.insert(item(id: 'a', sha: 'deadbeef'));

      expect((await db.findBySha('deadbeef'))?.id, 'a');
      expect(await db.findBySha('друго'), isNull);
    });

    test('изчиства приключилите, но пази активните', () async {
      final db = await freshDb();
      await db.insert(item(id: 'a', status: QueueStatus.uploaded, sha: '1'));
      await db.insert(item(id: 'b', status: QueueStatus.duplicate, sha: '2'));
      await db.insert(item(id: 'c', status: QueueStatus.pending, sha: '3'));
      await db.insert(
          item(id: 'd', status: QueueStatus.failedPermanent, sha: '4'));

      expect(await db.purgeCompleted(), 2);
      final left = (await db.all()).map((i) => i.id).toList();
      expect(left, containsAll(['c', 'd']),
          reason: 'неуспешните се пазят, за да ги види потребителят');
    });

    test('пълното изчистване не оставя нищо (logout)', () async {
      final db = await freshDb();
      await db.insert(item(id: 'a', sha: '1'));
      await db.insert(item(id: 'b', sha: '2'));

      await db.clear();
      expect(await db.all(), isEmpty);
    });

    test('обновяването пази идентичността на записа', () async {
      final db = await freshDb();
      await db.insert(item(id: 'a'));
      final loaded = (await db.all()).first;

      await db.update(loaded.copyWith(
        status: QueueStatus.uploaded,
        serverDocumentId: 'doc-42',
      ));

      final after = (await db.all()).single;
      expect(after.id, 'a');
      expect(after.status, QueueStatus.uploaded);
      expect(after.serverDocumentId, 'doc-42');
    });
  });

  group('Изчакване между опитите', () {
    test('расте експоненциално', () async {
      final first = UploadQueue.backoffFor(1);
      final second = UploadQueue.backoffFor(2);
      final third = UploadQueue.backoffFor(3);

      expect(first.inSeconds, greaterThanOrEqualTo(5));
      expect(second, greaterThan(first));
      expect(third, greaterThan(second));
    });

    test('не надхвърля тавана', () {
      // Много опити не бива да дадат абсурдно изчакване.
      final late = UploadQueue.backoffFor(20);
      expect(late.inMinutes, lessThanOrEqualTo(19),
          reason: '15 мин таван + до 25% разсейване');
    });
  });

  group('Статуси', () {
    test('приключилите се разпознават', () {
      expect(QueueStatus.uploaded.isTerminal, isTrue);
      expect(QueueStatus.duplicate.isTerminal, isTrue);
      expect(QueueStatus.failedPermanent.isTerminal, isTrue);
      expect(QueueStatus.pending.isTerminal, isFalse);
      expect(QueueStatus.failedRetryable.isTerminal, isFalse);
    });

    test('всеки статус има български етикет', () {
      for (final s in QueueStatus.values) {
        expect(s.label, isNotEmpty);
      }
    });

    test('непознат статус от базата не чупи', () {
      expect(QueueStatus.parse('нещо-ново'), QueueStatus.pending);
    });
  });
}
