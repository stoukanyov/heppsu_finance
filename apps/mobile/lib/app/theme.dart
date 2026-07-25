import 'package:flutter/material.dart';

/// Премиум, спокойна финтех палитра (в тон с уеб редизайна).
class HeppsuTheme {
  static const _seed = Color(0xFF3B5BFE);

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: _seed,
      brightness: Brightness.light,
    );
    return ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      scaffoldBackgroundColor: const Color(0xFFF6F7FB),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        foregroundColor: Color(0xFF1A1D29),
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: BorderSide(color: Colors.black.withValues(alpha: 0.05)),
        ),
        margin: EdgeInsets.zero,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: Colors.black.withValues(alpha: 0.08)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: Colors.black.withValues(alpha: 0.08)),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  /// Цвят на status pill според статуса.
  static Color statusColor(String label) {
    switch (label) {
      case 'Одобрен':
      case 'Осчетоводен':
      case 'Разпознат':
        return const Color(0xFF12A150);
      case 'Нужна проверка':
      case 'Липсват данни':
      case 'Възможен дубликат':
      case 'Върнат':
        return const Color(0xFFD97706);
      case 'Отказан':
        return const Color(0xFFDC2626);
      default:
        return const Color(0xFF6366F1);
    }
  }
}
