import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;

/// Подготвен за качване скан: смалено изображение + метаданни.
class ScanDraft {
  const ScanDraft({
    required this.bytes,
    required this.filename,
    required this.contentType,
    required this.sha256,
    required this.originalBytes,
  });

  final Uint8List bytes;
  final String filename;
  final String contentType;
  final String sha256;

  /// Размер на оригинала преди компресия — за показване „спестени X%".
  final int originalBytes;

  int get sizeBytes => bytes.length;

  double get savedRatio =>
      originalBytes == 0 ? 0 : 1 - (bytes.length / originalBytes);
}

/// Смаляване и компресия на снимките преди трансфер.
///
/// Целта е малък upload при запазена четимост за OCR. Оригиналният документ
/// се пази на сървъра (`Document.storage_path`) — тук се смалява само това,
/// което тръгва по мрежата.
class ImagePipeline {
  const ImagePipeline({
    this.maxDimension = 2200,
    this.jpegQuality = 80,
    this.maxBytes = 4 * 1024 * 1024,
  });

  /// Дълга страна след ресайз (px). ~2200 е балансът OCR четимост ↔ трафик.
  final int maxDimension;

  /// Начално JPEG качество; сваля се стъпаловидно при все още голям файл.
  final int jpegQuality;

  /// Таван на изпратения файл; над него се компресира по-агресивно.
  final int maxBytes;

  /// Обработва сурови байтове от камерата/галерията.
  ///
  /// Тежката работа върви в отделен isolate (`compute`), за да не блокира UI-а.
  Future<ScanDraft> process(Uint8List raw, {String? sourceName}) async {
    final result = await compute(
      _compressInIsolate,
      _CompressRequest(raw, maxDimension, jpegQuality, maxBytes),
    );
    final digest = sha256.convert(result).toString();
    final stamp = DateTime.now().millisecondsSinceEpoch;
    return ScanDraft(
      bytes: result,
      filename: 'scan_$stamp.jpg',
      contentType: 'image/jpeg',
      sha256: digest,
      originalBytes: raw.length,
    );
  }
}

class _CompressRequest {
  const _CompressRequest(this.raw, this.maxDimension, this.quality, this.maxBytes);

  final Uint8List raw;
  final int maxDimension;
  final int quality;
  final int maxBytes;
}

/// Изпълнява се в отделен isolate — без достъп до Flutter binding.
Uint8List _compressInIsolate(_CompressRequest req) {
  final decoded = img.decodeImage(req.raw);
  if (decoded == null) {
    // Не е разпознат формат — качваме както е дошло.
    return req.raw;
  }

  /// Ресайз само надолу: не уголемявай малки снимки.
  img.Image fit(img.Image src, int limit) {
    final longest = src.width > src.height ? src.width : src.height;
    if (longest <= limit) return src;
    return img.copyResize(
      src,
      width: src.width >= src.height ? limit : null,
      height: src.height > src.width ? limit : null,
      interpolation: img.Interpolation.average,
    );
  }

  var dimension = req.maxDimension;
  var resized = fit(decoded, dimension);
  var quality = req.quality;
  var out = Uint8List.fromList(img.encodeJpg(resized, quality: quality));

  // Стъпаловидно сваляне на качеството, ако още е над тавана.
  while (out.length > req.maxBytes && quality > 40) {
    quality -= 15;
    out = Uint8List.fromList(img.encodeJpg(resized, quality: quality));
  }

  // Само качеството понякога не стига (гъсти, шумни снимки) — тогава сваляме
  // и резолюцията. Спираме на 1000px по дългата страна, за да остане четимо
  // за OCR дори ако файлът все още надхвърля тавана.
  const floor = 1000;
  while (out.length > req.maxBytes && dimension > floor) {
    // Никога под пода — по-скоро оставяме файла по-голям, отколкото нечетим.
    final next = (dimension * 0.75).round();
    dimension = next < floor ? floor : next;
    resized = fit(decoded, dimension);
    out = Uint8List.fromList(img.encodeJpg(resized, quality: quality));
  }
  return out;
}
