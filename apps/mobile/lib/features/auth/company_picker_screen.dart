import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';

/// Избор на активна компания — задава `X-Company-Id` за всички заявки.
class CompanyPickerScreen extends ConsumerWidget {
  const CompanyPickerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final companies = session.companies;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Избери компания'),
        actions: [
          TextButton(
            onPressed: () => ref.read(sessionProvider.notifier).logout(),
            child: const Text('Изход'),
          ),
        ],
      ),
      body: companies.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: Text(
                  'Нямаш достъп до нито една компания.\n'
                  'Помоли администратор да те добави към екипа.',
                  textAlign: TextAlign.center,
                ),
              ),
            )
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: companies.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, i) {
                final c = companies[i];
                return Card(
                  child: ListTile(
                    contentPadding:
                        const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    leading: CircleAvatar(
                      backgroundColor: Theme.of(context)
                          .colorScheme
                          .primary
                          .withValues(alpha: 0.12),
                      child: Text(
                        c.name.characters.first.toUpperCase(),
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.primary,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    title: Text(c.name,
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: Text(
                      [
                        if (c.vatNumber != null) c.vatNumber,
                        c.baseCurrency,
                        if (c.role != null) c.role,
                      ].whereType<String>().join(' · '),
                    ),
                    trailing: const Icon(Icons.chevron_right_rounded),
                    onTap: () =>
                        ref.read(sessionProvider.notifier).selectCompany(c.id),
                  ),
                );
              },
            ),
    );
  }
}
