import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../deadlines/deadlines_screen.dart';
import '../documents/documents_screen.dart';
import '../reports/reports_screen.dart';
import '../scanner/scanner_flow.dart';
import '../vat/vat_screen.dart';

/// Основна навигация: Документи · ДДС · Отчети, с централен бутон „Сканирай".
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int _index = 0;

  static const _titles = ['Документи', 'Срокове', 'ДДС', 'Отчети'];

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final company = session.activeCompany;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 20,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              _titles[_index],
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
            ),
            if (company != null)
              Text(
                company.name,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w400,
                  color: Colors.black.withValues(alpha: 0.5),
                ),
              ),
          ],
        ),
        actions: [
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert_rounded),
            onSelected: (v) {
              if (v == 'logout') {
                ref.read(sessionProvider.notifier).logout();
              } else if (v == 'company') {
                _showCompanySheet(context);
              }
            },
            itemBuilder: (_) => [
              if (session.companies.length > 1)
                const PopupMenuItem(
                  value: 'company',
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.swap_horiz_rounded),
                    title: Text('Смени компания'),
                  ),
                ),
              const PopupMenuItem(
                value: 'logout',
                child: ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.logout_rounded),
                  title: Text('Изход'),
                ),
              ),
            ],
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: IndexedStack(
        index: _index,
        children: const [
          DocumentsScreen(),
          DeadlinesScreen(),
          VatScreen(),
          ReportsScreen(),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => startScanFlow(context, ref),
        icon: const Icon(Icons.document_scanner_rounded),
        label: const Text('Сканирай'),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long_rounded),
            label: 'Документи',
          ),
          NavigationDestination(
            icon: Icon(Icons.event_outlined),
            selectedIcon: Icon(Icons.event_rounded),
            label: 'Срокове',
          ),
          NavigationDestination(
            icon: Icon(Icons.request_quote_outlined),
            selectedIcon: Icon(Icons.request_quote_rounded),
            label: 'ДДС',
          ),
          NavigationDestination(
            icon: Icon(Icons.insights_outlined),
            selectedIcon: Icon(Icons.insights_rounded),
            label: 'Отчети',
          ),
        ],
      ),
    );
  }

  void _showCompanySheet(BuildContext context) {
    final session = ref.read(sessionProvider);
    showModalBottomSheet<void>(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Смени компания',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            ),
            for (final c in session.companies)
              ListTile(
                title: Text(c.name),
                subtitle: Text(c.baseCurrency),
                trailing: c.id == session.activeCompanyId
                    ? const Icon(Icons.check_rounded)
                    : null,
                onTap: () {
                  ref.read(sessionProvider.notifier).selectCompany(c.id);
                  ref.invalidate(documentsListProvider);
                  ref.invalidate(vatPeriodsProvider);
                  Navigator.pop(context);
                },
              ),
          ],
        ),
      ),
    );
  }
}
