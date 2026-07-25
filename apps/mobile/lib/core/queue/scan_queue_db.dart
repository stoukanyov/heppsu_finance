import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

/// Състояние на скан в локалната опашка.
enum QueueStatus {
  pending,
  uploading,
  uploaded,
  failedRetryable,
  failedPermanent,
  duplicate;

  static QueueStatus parse(String raw) => QueueStatus.values.firstWhere(
        (s) => s.name == raw,
        orElse: () => QueueStatus.pending,
      );

  bool get isTerminal =>
      this == QueueStatus.uploaded ||
      this == QueueStatus.duplicate ||
      this == QueueStatus.failedPermanent;

  String get label {
    switch (this) {
      case QueueStatus.pending:
        return 'Чака мрежа';
      case QueueStatus.uploading:
        return 'Изпраща се';
      case QueueStatus.uploaded:
        return 'Изпратен';
      case QueueStatus.failedRetryable:
        return 'Ще опита пак';
      case QueueStatus.failedPermanent:
        return 'Неуспешен';
      case QueueStatus.duplicate:
        return 'Вече качен';
    }
  }
}

/// Един скан, чакащ да бъде изпратен.
class ScanQueueItem {
  const ScanQueueItem({
    required this.id,
    required this.filePath,
    required this.filename,
    required this.contentType,
    required this.sha256,
    required this.sizeBytes,
    required this.companyId,
    required this.status,
    required this.attempts,
    required this.createdAt,
    this.note,
    this.nextAttemptAt,
    this.serverDocumentId,
    this.lastError,
  });

  /// Клиентски UUID — идемпотентен ключ, оцелява през рестарти.
  final String id;

  /// Локалният файл; изтрива се след успешно качване.
  final String filePath;
  final String filename;
  final String contentType;
  final String sha256;
  final int sizeBytes;

  /// Опашката е за конкретна компания — сканът тръгва към нея, дори ако
  /// потребителят междувременно е сменил активната.
  final String companyId;

  final QueueStatus status;
  final int attempts;
  final DateTime createdAt;
  final String? note;
  final DateTime? nextAttemptAt;
  final String? serverDocumentId;
  final String? lastError;

  bool get isDue =>
      nextAttemptAt == null || nextAttemptAt!.isBefore(DateTime.now());

  ScanQueueItem copyWith({
    QueueStatus? status,
    int? attempts,
    DateTime? nextAttemptAt,
    String? serverDocumentId,
    String? lastError,
  }) =>
      ScanQueueItem(
        id: id,
        filePath: filePath,
        filename: filename,
        contentType: contentType,
        sha256: sha256,
        sizeBytes: sizeBytes,
        companyId: companyId,
        status: status ?? this.status,
        attempts: attempts ?? this.attempts,
        createdAt: createdAt,
        note: note,
        nextAttemptAt: nextAttemptAt ?? this.nextAttemptAt,
        serverDocumentId: serverDocumentId ?? this.serverDocumentId,
        lastError: lastError ?? this.lastError,
      );

  Map<String, Object?> toRow() => {
        'id': id,
        'file_path': filePath,
        'filename': filename,
        'content_type': contentType,
        'sha256': sha256,
        'size_bytes': sizeBytes,
        'company_id': companyId,
        'status': status.name,
        'attempts': attempts,
        'created_at': createdAt.millisecondsSinceEpoch,
        'note': note,
        'next_attempt_at': nextAttemptAt?.millisecondsSinceEpoch,
        'server_document_id': serverDocumentId,
        'last_error': lastError,
      };

  factory ScanQueueItem.fromRow(Map<String, Object?> r) => ScanQueueItem(
        id: r['id'] as String,
        filePath: r['file_path'] as String,
        filename: r['filename'] as String,
        contentType: r['content_type'] as String,
        sha256: r['sha256'] as String,
        sizeBytes: (r['size_bytes'] as int?) ?? 0,
        companyId: (r['company_id'] as String?) ?? '',
        status: QueueStatus.parse(r['status'] as String),
        attempts: (r['attempts'] as int?) ?? 0,
        createdAt:
            DateTime.fromMillisecondsSinceEpoch((r['created_at'] as int?) ?? 0),
        note: r['note'] as String?,
        nextAttemptAt: r['next_attempt_at'] == null
            ? null
            : DateTime.fromMillisecondsSinceEpoch(r['next_attempt_at'] as int),
        serverDocumentId: r['server_document_id'] as String?,
        lastError: r['last_error'] as String?,
      );
}

/// Локално хранилище на опашката (SQLite през `sqflite`).
///
/// Съзнателно без ORM/codegen — таблицата е една, заявките са няколко, и
/// проектът няма `build_runner` стъпка, която да поддържа.
class ScanQueueDb {
  ScanQueueDb({Database? database}) : _injected = database;

  final Database? _injected;
  Database? _db;

  static const _table = 'scan_queue';

  Future<Database> get _database async {
    if (_injected != null) return _injected;
    if (_db != null) return _db!;
    final dir = await getApplicationDocumentsDirectory();
    _db = await openDatabase(
      '${dir.path}/scan_queue.db',
      version: 1,
      onCreate: (db, _) => _createSchema(db),
    );
    return _db!;
  }

  static Future<void> _createSchema(Database db) async {
    await db.execute('''
      CREATE TABLE $_table (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        company_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        note TEXT,
        next_attempt_at INTEGER,
        server_document_id TEXT,
        last_error TEXT
      )
    ''');
    await db.execute('CREATE INDEX idx_status ON $_table(status)');
    await db.execute('CREATE INDEX idx_sha ON $_table(sha256)');
  }

  /// Създава схемата в подадена база — за тестове с in-memory SQLite.
  static Future<void> createSchemaFor(Database db) => _createSchema(db);

  Future<void> insert(ScanQueueItem item) async {
    final db = await _database;
    await db.insert(_table, item.toRow(),
        conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<List<ScanQueueItem>> all() async {
    final db = await _database;
    final rows = await db.query(_table, orderBy: 'created_at DESC');
    return rows.map(ScanQueueItem.fromRow).toList();
  }

  /// Само активните — приключилите не се показват в списъка за действие.
  Future<List<ScanQueueItem>> active() async {
    final db = await _database;
    final rows = await db.query(
      _table,
      where: 'status IN (?, ?, ?)',
      whereArgs: [
        QueueStatus.pending.name,
        QueueStatus.uploading.name,
        QueueStatus.failedRetryable.name,
      ],
      orderBy: 'created_at ASC',
    );
    return rows.map(ScanQueueItem.fromRow).toList();
  }

  /// Готовите за изпращане: чакащи или с изтекъл backoff.
  Future<List<ScanQueueItem>> due() async {
    final now = DateTime.now().millisecondsSinceEpoch;
    final db = await _database;
    final rows = await db.query(
      _table,
      where: 'status = ? OR (status = ? AND '
          '(next_attempt_at IS NULL OR next_attempt_at <= ?))',
      whereArgs: [QueueStatus.pending.name, QueueStatus.failedRetryable.name, now],
      orderBy: 'created_at ASC',
    );
    return rows.map(ScanQueueItem.fromRow).toList();
  }

  Future<int> pendingCount() async {
    final db = await _database;
    final r = await db.rawQuery(
      'SELECT COUNT(*) c FROM $_table WHERE status IN (?, ?, ?)',
      [
        QueueStatus.pending.name,
        QueueStatus.uploading.name,
        QueueStatus.failedRetryable.name,
      ],
    );
    return (r.first['c'] as int?) ?? 0;
  }

  /// Има ли вече такъв файл в опашката — пази от двойно добавяне на един и
  /// същ скан (сървърът дедупликира по същия sha256).
  Future<ScanQueueItem?> findBySha(String sha256) async {
    final db = await _database;
    final rows = await db.query(_table,
        where: 'sha256 = ?', whereArgs: [sha256], limit: 1);
    return rows.isEmpty ? null : ScanQueueItem.fromRow(rows.first);
  }

  Future<void> update(ScanQueueItem item) async {
    final db = await _database;
    await db.update(_table, item.toRow(), where: 'id = ?', whereArgs: [item.id]);
  }

  /// Изтрива записа и локалния файл към него.
  Future<void> remove(String id) async {
    final db = await _database;
    final rows =
        await db.query(_table, where: 'id = ?', whereArgs: [id], limit: 1);
    if (rows.isNotEmpty) {
      await _deleteFile(rows.first['file_path'] as String);
    }
    await db.delete(_table, where: 'id = ?', whereArgs: [id]);
  }

  /// Чисти приключилите записи и файловете им.
  Future<int> purgeCompleted() async {
    final db = await _database;
    final rows = await db.query(
      _table,
      where: 'status IN (?, ?)',
      whereArgs: [QueueStatus.uploaded.name, QueueStatus.duplicate.name],
    );
    for (final r in rows) {
      await _deleteFile(r['file_path'] as String);
    }
    return db.delete(
      _table,
      where: 'status IN (?, ?)',
      whereArgs: [QueueStatus.uploaded.name, QueueStatus.duplicate.name],
    );
  }

  /// Пълно изчистване при logout (GDPR — локалният кеш не бива да остава).
  Future<void> clear() async {
    final db = await _database;
    for (final r in await db.query(_table)) {
      await _deleteFile(r['file_path'] as String);
    }
    await db.delete(_table);
  }

  static Future<void> _deleteFile(String path) async {
    try {
      final f = File(path);
      if (f.existsSync()) await f.delete();
    } catch (_) {
      // Липсващ файл не е проблем — целта е да не остане на диска.
    }
  }
}
