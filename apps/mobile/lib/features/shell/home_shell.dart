import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../deadlines/deadlines_screen.dart';
import '../documents/documents_screen.dart';
import '../queue/queue_screen.dart';
import '../reports/reports_screen.dart';
import '../scanner/scanner_flow.dart';
import '../vat/vat_screen.dart';

/// Основна навигация: Документи · ДДС · Отчети, с централен бутон „Сканирай".
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell>
    with WidgetsBindingObserver {
  int _index = 0;

  static const _titles = ['Документи', 'Срокове', 'ДДС', 'Отчети'];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Опашката тръгва веднага след вход: качва всичко, което е чакало мрежа.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(uploadQueueProvider).start();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Връщане на преден план е добър момент да пробваме пак — възможно е
    // мрежата да се е появила, докато приложението е било в заден план.
    if (state == AppLifecycleState.resumed) {
      ref.read(uploadQueueProvider).process();
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final company = session.activeCompany;
    final queued = ref.watch(queuePendingCountProvider).valueOrNull ?? 0;

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
          // Значка с броя чакащи сканове — видима от всеки таб, защото е
          // единственият знак, че нещо още не е стигнало до сървъра.
          if (queued > 0)
            IconButton(
              tooltip: 'Опашка за качване',
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const QueueScreen()),
              ),
              icon: Badge.count(
                count: queued,
                child: const Icon(Icons.cloud_upload_outlined),
              ),
            ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert_rounded),
            onSelected: (v) {
              if (v == 'logout') {
                ref.read(sessionProvider.notifier).logout();
              } else if (v == 'company') {
                _showCompanySheet(context);
              } else if (v == 'queue') {
                Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const QueueScreen()),
                );
              }
            },
            itemBuilder: (_) => [
              const PopupMenuItem(
                value: 'queue',
                child: ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.cloud_upload_outlined),
                  title: Text('Опашка за качване'),
                ),
              ),
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
      body: Column(
        children: [
          if (session.offline) const _OfflineBanner(),
          Expanded(
            child: IndexedStack(
              index: _index,
              children: const [
                DocumentsScreen(),
                DeadlinesScreen(),
                VatScreen(),
                ReportsScreen(),
              ],
            ),
          ),
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

/// Лента при офлайн вход: обяснява, че данните са кеширани, но сканирането
/// работи — сканът чака в опашката и тръгва щом има мрежа.
class _OfflineBanner extends ConsumerStatefulWidget {
  const _OfflineBanner();

  @override
  ConsumerState<_OfflineBanner> createState() => _OfflineBannerState();
}

class _OfflineBannerState extends ConsumerState<_OfflineBanner> {
  bool _retrying = false;

  Future<void> _retry() async {
    setState(() => _retrying = true);
    await ref.read(sessionProvider.notifier).retryOnline();
    if (mounted) setState(() => _retrying = false);
  }

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFFD97706).withValues(alpha: 0.12),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 8, 10),
        child: Row(
          children: [
            const Icon(Icons.cloud_off_rounded,
                size: 18, color: Color(0xFFB45309)),
            const SizedBox(width: 10),
            const Expanded(
              child: Text(
                'Офлайн режим — данните са от последното зареждане. '
                'Сканирането работи и ще се качи автоматично.',
                style: TextStyle(fontSize: 12.5, color: Color(0xFF92400E)),
              ),
            ),
            if (_retrying)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 12),
                child: SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              )
            else
              TextButton(
                onPressed: _retry,
                style: TextButton.styleFrom(
                  foregroundColor: const Color(0xFFB45309),
                  visualDensity: VisualDensity.compact,
                ),
                child: const Text('Опитай'),
              ),
          ],
        ),
      ),
    );
  }
}
