import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/network/api_exception.dart';
import '../../domain/models.dart';

/// Полетата, които се редактират от телефона, в реда на попълване.
/// Ключовете са тези, които backend-ът очаква в `fields`.
const _editable = <({String key, String label, TextInputType type})>[
  (key: 'issuer', label: 'Доставчик', type: TextInputType.text),
  (key: 'issuer_vat_number', label: 'ДДС номер', type: TextInputType.text),
  (key: 'document_number', label: 'Документ №', type: TextInputType.text),
  (key: 'document_date', label: 'Дата (ГГГГ-ММ-ДД)', type: TextInputType.datetime),
  (key: 'tax_base', label: 'Данъчна основа', type: TextInputType.number),
  (key: 'vat_amount', label: 'ДДС', type: TextInputType.number),
  (key: 'total', label: 'Общо', type: TextInputType.number),
];

const _amountKeys = {'tax_base', 'vat_amount', 'total'};

/// Отваря формуляра за корекция. Връща новия резултат, ако е записан.
Future<ScanResult?> showEditExtractionSheet(
  BuildContext context, {
  required String documentId,
  required Extraction extraction,
}) {
  return showModalBottomSheet<ScanResult>(
    context: context,
    isScrollControlled: true,
    builder: (_) => Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: _EditExtractionSheet(
        documentId: documentId,
        extraction: extraction,
      ),
    ),
  );
}

class _EditExtractionSheet extends ConsumerStatefulWidget {
  const _EditExtractionSheet({
    required this.documentId,
    required this.extraction,
  });

  final String documentId;
  final Extraction extraction;

  @override
  ConsumerState<_EditExtractionSheet> createState() =>
      _EditExtractionSheetState();
}

class _EditExtractionSheetState extends ConsumerState<_EditExtractionSheet> {
  final _formKey = GlobalKey<FormState>();
  final _controllers = <String, TextEditingController>{};
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final fields = widget.extraction.fields;
    for (final f in _editable) {
      final raw = fields[f.key];
      _controllers[f.key] = TextEditingController(
        text: raw == null ? '' : _display(f.key, raw),
      );
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  /// Числата се показват с десетична запетая (както се пише в България),
  /// а се пращат с точка.
  String _display(String key, Object value) {
    if (!_amountKeys.contains(key)) return value.toString();
    final n = double.tryParse(value.toString());
    return n == null ? value.toString() : n.toStringAsFixed(2).replaceAll('.', ',');
  }

  /// Праща само реално променените полета — така не „потвърждаваме" неща,
  /// които потребителят не е погледнал.
  Map<String, dynamic> _changedFields() {
    final original = widget.extraction.fields;
    final out = <String, dynamic>{};

    for (final f in _editable) {
      final text = _controllers[f.key]!.text.trim();
      final before = original[f.key];
      final beforeText = before == null ? '' : _display(f.key, before);
      if (text == beforeText) continue;

      if (text.isEmpty) {
        out[f.key] = null;
      } else if (_amountKeys.contains(f.key)) {
        out[f.key] = double.parse(text.replaceAll(' ', '').replaceAll(',', '.'));
      } else {
        out[f.key] = text;
      }
    }
    return out;
  }

  String? _validateAmount(String? v) {
    if (v == null || v.trim().isEmpty) return null;
    final n = double.tryParse(v.replaceAll(' ', '').replaceAll(',', '.'));
    if (n == null) return 'Въведи число';
    if (n < 0) return 'Не може отрицателно';
    return null;
  }

  String? _validateDate(String? v) {
    if (v == null || v.trim().isEmpty) return null;
    if (DateTime.tryParse(v.trim()) == null) return 'Формат ГГГГ-ММ-ДД';
    return null;
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;

    final changed = _changedFields();
    if (changed.isEmpty) {
      Navigator.pop(context);
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final result = await ref
          .read(documentsRepositoryProvider)
          .correctExtraction(widget.documentId, changed);
      if (!mounted) return;
      ref.invalidate(documentsListProvider);
      Navigator.pop(context, result);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) setState(() => _error = 'Записът не мина. Опитай пак.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Form(
        key: _formKey,
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
          children: [
            Center(
              child: Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 18),
            const Text(
              'Поправи данните',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            Text(
              'Коригираните полета се приемат за потвърдени от теб и статията '
              'се предлага наново.',
              style: TextStyle(
                fontSize: 12.5,
                color: Colors.black.withValues(alpha: 0.55),
              ),
            ),
            const SizedBox(height: 20),
            for (final f in _editable) ...[
              TextFormField(
                controller: _controllers[f.key],
                keyboardType: f.type,
                inputFormatters: _amountKeys.contains(f.key)
                    ? [FilteringTextInputFormatter.allow(RegExp(r'[\d.,\s]'))]
                    : null,
                decoration: InputDecoration(
                  labelText: f.label,
                  isDense: true,
                ),
                validator: _amountKeys.contains(f.key)
                    ? _validateAmount
                    : (f.key == 'document_date' ? _validateDate : null),
              ),
              const SizedBox(height: 12),
            ],
            if (_error != null) ...[
              const SizedBox(height: 4),
              Text(
                _error!,
                style: const TextStyle(color: Color(0xFFDC2626), fontSize: 13),
              ),
            ],
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2.2, color: Colors.white),
                    )
                  : const Icon(Icons.check_rounded),
              label: Text(_saving ? 'Записвам…' : 'Запази и предложи наново'),
            ),
          ],
        ),
      ),
    );
  }
}
