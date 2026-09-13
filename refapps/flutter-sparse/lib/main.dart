import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

const _faultChannel = MethodChannel('dev.haykal.refapps.flutter_sparse/faults');

@immutable
class Faults {
  const Faults({
    this.arabicIndicDigits = false,
    this.slowSettle = false,
    this.duplicateLabels = false,
  });

  final bool arabicIndicDigits;
  final bool slowSettle;
  final bool duplicateLabels;

  static const none = Faults();

  factory Faults.fromMap(Map<Object?, Object?> values) => Faults(
    arabicIndicDigits: values['arabic_indic_digits'] == true,
    slowSettle: values['slow_settle'] == true,
    duplicateLabels: values['duplicate_labels'] == true,
  );
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  var faults = Faults.none;
  try {
    final values = await _faultChannel.invokeMapMethod<Object?, Object?>(
      'getFaults',
    );
    faults = Faults.fromMap(values ?? const {});
  } on PlatformException {
    // Widget tests and non-Android hosts intentionally use the fault-free state.
  }
  runApp(HaykalApp(faults: faults));
}

class HaykalApp extends StatelessWidget {
  const HaykalApp({super.key, required this.faults});

  final Faults faults;

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'Haykal Flutter Sparse',
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff125f55)),
      useMaterial3: true,
    ),
    builder: (context, child) =>
        Directionality(textDirection: TextDirection.rtl, child: child!),
    home: SparseHome(faults: faults),
  );
}

enum Surface { semanticsOn, semanticsOff, imageOnly }

class SparseHome extends StatefulWidget {
  const SparseHome({super.key, required this.faults});

  final Faults faults;

  @override
  State<SparseHome> createState() => _SparseHomeState();
}

class _SparseHomeState extends State<SparseHome> {
  Surface _surface = Surface.semanticsOn;
  bool _settled = true;

  void _select(Surface surface) {
    setState(() {
      _surface = surface;
      _settled = !widget.faults.slowSettle;
    });
    if (!_settled) {
      Future<void>.delayed(const Duration(milliseconds: 1200), () {
        if (mounted) setState(() => _settled = true);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final price = widget.faults.arabicIndicDigits ? '٣٩٫٩٥ ر.س' : '39.95 ر.س';
    return Scaffold(
      appBar: AppBar(title: const Text('مختبر Flutter الدلالي')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'ثلاثة أسطح متطابقة لاختبار شجرة الوصول والرؤية',
                key: Key('intro'),
              ),
              const SizedBox(height: 16),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _surfaceButton(Surface.semanticsOn, 'دلالات مفعلة'),
                  _surfaceButton(Surface.semanticsOff, 'دلالات معطلة'),
                  _surfaceButton(Surface.imageOnly, 'بطاقة صورية'),
                ],
              ),
              const SizedBox(height: 24),
              if (!_settled)
                const Center(
                  child: CircularProgressIndicator(key: Key('slow-settle')),
                )
              else
                Expanded(child: _surfaceBody(price)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _surfaceButton(Surface surface, String label) => FilledButton.tonal(
    key: Key('surface-${surface.name}'),
    onPressed: () => _select(surface),
    child: Text(label),
  );

  Widget _surfaceBody(String price) {
    final labels = widget.faults.duplicateLabels
        ? const ['عرض', 'عرض']
        : const ['عرض التفاصيل', 'أضف للسلة'];
    final card = _OfferCard(price: price, labels: labels);
    return switch (_surface) {
      Surface.semanticsOn => Semantics(
        key: const Key('semantics-on'),
        container: true,
        label: 'عرض بيتزا مارغريتا بسعر $price',
        child: card,
      ),
      Surface.semanticsOff => ExcludeSemantics(
        key: const Key('semantics-off'),
        child: card,
      ),
      Surface.imageOnly => Semantics(
        key: const Key('image-only'),
        container: true,
        label: 'منطقة صورية بلا وصف للعرض',
        child: ExcludeSemantics(
          child: CustomPaint(
            painter: _PriceCardPainter(price),
            child: const SizedBox.expand(),
          ),
        ),
      ),
    };
  }
}

class _OfferCard extends StatelessWidget {
  const _OfferCard({required this.price, required this.labels});

  final String price;
  final List<String> labels;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.local_pizza, size: 72),
          const Text('بيتزا مارغريتا', style: TextStyle(fontSize: 28)),
          Text(price, style: const TextStyle(fontSize: 24)),
          const SizedBox(height: 16),
          FilledButton(onPressed: () {}, child: Text(labels[0])),
          OutlinedButton(onPressed: () {}, child: Text(labels[1])),
        ],
      ),
    ),
  );
}

class _PriceCardPainter extends CustomPainter {
  _PriceCardPainter(this.price);

  final String price;

  @override
  void paint(Canvas canvas, Size size) {
    final card = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(28),
    );
    canvas.drawRRect(card, Paint()..color = const Color(0xfffff3df));
    canvas.drawCircle(
      Offset(size.width / 2, size.height * .3),
      72,
      Paint()..color = const Color(0xffe76f51),
    );
    final paragraph =
        (ui.ParagraphBuilder(
                ui.ParagraphStyle(
                  textAlign: TextAlign.center,
                  textDirection: TextDirection.rtl,
                  fontSize: 28,
                ),
              )
              ..pushStyle(ui.TextStyle(color: const Color(0xff1e2d2a)))
              ..addText('عرض بيتزا عائلية\n$price'))
            .build()
          ..layout(ui.ParagraphConstraints(width: size.width - 32));
    canvas.drawParagraph(paragraph, Offset(16, size.height * .55));
  }

  @override
  bool shouldRepaint(covariant _PriceCardPainter oldDelegate) =>
      oldDelegate.price != price;
}
