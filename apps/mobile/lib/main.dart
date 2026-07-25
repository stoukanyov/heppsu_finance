import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/providers.dart';
import 'app/theme.dart';
import 'features/auth/company_picker_screen.dart';
import 'features/auth/login_screen.dart';
import 'features/shell/home_shell.dart';

void main() {
  runApp(const ProviderScope(child: HeppsuApp()));
}

class HeppsuApp extends ConsumerWidget {
  const HeppsuApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stage = ref.watch(sessionProvider).stage;
    return MaterialApp(
      title: 'Heppsu Finance',
      debugShowCheckedModeBanner: false,
      theme: HeppsuTheme.light(),
      home: switch (stage) {
        SessionStage.loading => const _Splash(),
        SessionStage.unauthenticated => const LoginScreen(),
        SessionStage.needsCompany => const CompanyPickerScreen(),
        SessionStage.ready => const HomeShell(),
      },
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: CircularProgressIndicator()));
  }
}
