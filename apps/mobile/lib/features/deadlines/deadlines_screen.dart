import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/notifications/reminder_service.dart';
import '../../domain/models.dart';
import '../common/widgets.dart';

/// Предстоящи срокове към НАП, НСИ и Търговския регистър + напомняния.
class DeadlinesScreen extends ConsumerWidget {
  const DeadlinesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(deadlinesProvider);

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => ErrorView(
        message: 'Не успях да заредя сроковете.\n$e',
        onRetry: () => ref.invalidate(deadlinesProvider),
      ),
      data: (deadlines) => RefreshIndicator(
        onRefresh: () async => ref.invalidate(deadlinesProvider),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 110),
          children: [
            const _ReminderToggle(),
            const SizedBox(height: 18),
            if (deadlines.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 40),
                child: EmptyView(
                  message: 'Няма предстоящи срокове в следващите 3 месеца.',
                  icon: Icons.event_available_outlined,
                ),
              )
            else
              for (final d in deadlines) ...[
                _DeadlineCard(deadline: d),
                const SizedBox(height: 10),
              ],
          ],
        ),
      ),
    );
  }
}

/// Превключвател за локалните напомняния.
class _ReminderToggle extends ConsumerStatefulWidget {
  const _ReminderToggle();

  @override
  ConsumerState<_ReminderToggle> createState() => _ReminderToggleState();
}

class _ReminderToggleState extends ConsumerState<_ReminderToggle> {
  bool _busy = false;

  Future<void> _toggle(bool value) async {
    setState(() => _busy = true);
    final granted =
        await ref.read(remindersEnabledProvider.notifier).toggle(value);
    if (!mounted) return;
    setState(() => _busy = false);

    if (value && !granted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Нужно е разрешение за известия — включи го от Настройки на телефона.',
          ),
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final enabled = ref.watch(remindersEnabledProvider);
    final offsets =
        ReminderOffset.all.map((o) => '${o.days} дни').join(' · ').replaceAll(
              '1 дни',
              '24 часа',
            );

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
        child: Row(
          children: [
            Icon(
              enabled
                  ? Icons.notifications_active_rounded
                  : Icons.notifications_off_outlined,
              color: enabled
                  ? Theme.of(context).colorScheme.primary
                  : Colors.black.withValues(alpha: 0.35),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Напомняния',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    enabled
                        ? 'Преди всеки срок: $offsets'
                        : 'Изключени',
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.black.withValues(alpha: 0.5),
                    ),
                  ),
                ],
              ),
            ),
            if (_busy)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 14),
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2.2),
                ),
              )
            else
              Switch(value: enabled, onChanged: _toggle),
          ],
        ),
      ),
    );
  }
}

class _DeadlineCard extends StatelessWidget {
  const _DeadlineCard({required this.deadline});

  final Deadline deadline;

  static const _authorityColors = <String, Color>{
    'НАП': Color(0xFF3B5BFE),
    'НСИ': Color(0xFF7C3AED),
    'Търговски регистър': Color(0xFF0891B2),
  };

  (String label, Color color) get _countdown {
    final d = deadline.daysRemaining;
    if (d < 0) return ('Просрочен', const Color(0xFFDC2626));
    if (d == 0) return ('Днес!', const Color(0xFFDC2626));
    if (d == 1) return ('Утре', const Color(0xFFDC2626));
    if (d <= 3) return ('След $d дни', const Color(0xFFD97706));
    if (d <= 7) return ('След $d дни', const Color(0xFFD97706));
    return ('След $d дни', const Color(0xFF12A150));
  }

  static String _fmt(DateTime d) => '${d.day.toString().padLeft(2, '0')}.'
      '${d.month.toString().padLeft(2, '0')}.${d.year}';

  String get _formattedDate => _fmt(deadline.dueDate);

  @override
  Widget build(BuildContext context) {
    final (countdown, color) = _countdown;
    final accent = _authorityColors[deadline.authority] ?? const Color(0xFF6366F1);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    deadline.title,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                StatusPill(countdown, color: color),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              deadline.description,
              style: TextStyle(
                fontSize: 13,
                height: 1.35,
                color: Colors.black.withValues(alpha: 0.6),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Icon(Icons.event_rounded,
                    size: 15, color: Colors.black.withValues(alpha: 0.4)),
                const SizedBox(width: 6),
                Text(
                  _formattedDate,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                if (deadline.periodLabel.isNotEmpty) ...[
                  Text(
                    '  ·  ${deadline.periodLabel}',
                    style: TextStyle(
                      fontSize: 12.5,
                      color: Colors.black.withValues(alpha: 0.5),
                    ),
                  ),
                ],
                const Spacer(),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: accent.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    deadline.authority,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: accent,
                    ),
                  ),
                ),
              ],
            ),
            if (deadline.movedForHoliday) ...[
              const SizedBox(height: 8),
              Text(
                deadline.originalDueDate == null
                    ? 'Преместен напред заради почивен ден.'
                    : 'По календар ${_fmt(deadline.originalDueDate!)} — '
                        'падa в почивен ден, затова срокът е $_formattedDate.',
                style: TextStyle(
                  fontSize: 11.5,
                  fontStyle: FontStyle.italic,
                  color: Colors.black.withValues(alpha: 0.45),
                ),
              ),
            ],
            if (deadline.conditional) ...[
              const SizedBox(height: 10),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.help_outline_rounded,
                      size: 15, color: Color(0xFFD97706)),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      deadline.conditionalNote ??
                          'Важи само при определени обстоятелства.',
                      style: const TextStyle(
                        fontSize: 11.5,
                        color: Color(0xFFB45309),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
