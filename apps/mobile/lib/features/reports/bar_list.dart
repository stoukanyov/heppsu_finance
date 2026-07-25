import 'package:flutter/material.dart';

import '../common/widgets.dart';

/// Хоризонтална лента-диаграма: списък с ред „етикет — лента — сума".
///
/// Стойностите се нормират спрямо най-голямата, така че лентите остават
/// четими независимо от мащаба на сумите.
class BarList extends StatelessWidget {
  const BarList({
    super.key,
    required this.title,
    required this.items,
    required this.color,
    this.currency = 'EUR',
    this.maxItems,
  });

  final String title;
  final List<({String label, double value})> items;
  final Color color;
  final String currency;

  /// Показва само първите N (по стойност); останалите се сумират в „Други".
  final int? maxItems;

  @override
  Widget build(BuildContext context) {
    final sorted = [...items]
      ..sort((a, b) => b.value.abs().compareTo(a.value.abs()));

    var shown = sorted;
    if (maxItems != null && sorted.length > maxItems!) {
      final rest = sorted.skip(maxItems!);
      final restSum = rest.fold<double>(0, (s, e) => s + e.value);
      shown = [
        ...sorted.take(maxItems!),
        (label: 'Други (${rest.length})', value: restSum),
      ];
    }

    final peak = shown.fold<double>(
      0,
      (m, e) => e.value.abs() > m ? e.value.abs() : m,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          title,
          style: TextStyle(
            fontSize: 12.5,
            fontWeight: FontWeight.w700,
            color: Colors.black.withValues(alpha: 0.5),
          ),
        ),
        const SizedBox(height: 10),
        for (final item in shown)
          Padding(
            padding: const EdgeInsets.only(bottom: 11),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        item.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      formatMoney(item.value, currency),
                      style: const TextStyle(
                          fontSize: 13, fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(999),
                  child: LinearProgressIndicator(
                    value: peak == 0 ? 0 : (item.value.abs() / peak),
                    minHeight: 6,
                    backgroundColor: color.withValues(alpha: 0.1),
                    valueColor: AlwaysStoppedAnimation(color),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
