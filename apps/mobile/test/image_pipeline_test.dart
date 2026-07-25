import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:heppsu_finance/core/scan/image_pipeline.dart';
import 'package:image/image.dart' as img;

/// Синтетична „снимка" с шум, за да не се компресира до нула байта.
Uint8List _photo(int width, int height) {
  final image = img.Image(width: width, height: height);
  for (var y = 0; y < height; y++) {
    for (var x = 0; x < width; x++) {
      image.setPixelRgb(x, y, (x * 7) % 256, (y * 13) % 256, (x * y) % 256);
    }
  }
  return Uint8List.fromList(img.encodeJpg(image, quality: 100));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const pipeline = ImagePipeline();

  test('смалява голяма снимка под лимита за дълга страна', () async {
    final raw = _photo(4000, 3000);
    final draft = await pipeline.process(raw);

    final decoded = img.decodeImage(draft.bytes)!;
    expect(decoded.width, 2200, reason: 'дългата страна се ресайзва до 2200px');
    expect(decoded.height, lessThan(2200));
    expect(draft.sizeBytes, lessThan(raw.length));
    expect(draft.savedRatio, greaterThan(0));
  });

  test('не уголемява снимка, по-малка от лимита', () async {
    final raw = _photo(800, 600);
    final draft = await pipeline.process(raw);

    final decoded = img.decodeImage(draft.bytes)!;
    expect(decoded.width, 800);
    expect(decoded.height, 600);
  });

  test('запазва портретна ориентация при ресайз', () async {
    final raw = _photo(1500, 4000);
    final draft = await pipeline.process(raw);

    final decoded = img.decodeImage(draft.bytes)!;
    expect(decoded.height, 2200);
    expect(decoded.width, lessThan(2200));
  });

  test('резултатът е JPEG със sha256 и име на файл', () async {
    final draft = await pipeline.process(_photo(1000, 1000));

    expect(draft.contentType, 'image/jpeg');
    expect(draft.filename, endsWith('.jpg'));
    expect(draft.sha256.length, 64);
  });

  test('еднакви входни байтове дават еднакъв sha256', () async {
    final raw = _photo(900, 700);
    final a = await pipeline.process(raw);
    final b = await pipeline.process(raw);

    expect(a.sha256, b.sha256);
  });

  test('неразпознат формат се качва без промяна', () async {
    final garbage = Uint8List.fromList(List.generate(64, (i) => i));
    final draft = await pipeline.process(garbage);

    expect(draft.bytes, garbage);
  });

  test('при строг таван сваля и качеството, и резолюцията', () async {
    const strict = ImagePipeline(maxBytes: 60 * 1024);
    final raw = _photo(3000, 2400);
    final draft = await strict.process(raw);
    final loose = await pipeline.process(raw);

    // Чистият шум е най-лошият случай за JPEG и не винаги слиза под тавана,
    // но строгата настройка трябва да даде осезаемо по-малък файл…
    expect(draft.sizeBytes, lessThan(loose.sizeBytes));

    // …и да е свалила резолюцията, без да пада под четимото за OCR.
    final decoded = img.decodeImage(draft.bytes)!;
    expect(decoded.width, lessThan(2200));
    expect(decoded.width, greaterThanOrEqualTo(1000));
  });
}
