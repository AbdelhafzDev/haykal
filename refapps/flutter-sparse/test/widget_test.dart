import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_sparse/main.dart';

void main() {
  testWidgets('all sparse surfaces are deterministic', (tester) async {
    await tester.pumpWidget(const HaykalApp(faults: Faults.none));

    expect(find.byKey(const Key('semantics-on')), findsOneWidget);
    expect(find.text('بيتزا مارغريتا'), findsOneWidget);

    await tester.tap(find.byKey(const Key('surface-semanticsOff')));
    await tester.pump();
    expect(find.byKey(const Key('semantics-off')), findsOneWidget);

    await tester.tap(find.byKey(const Key('surface-imageOnly')));
    await tester.pump();
    expect(find.byKey(const Key('image-only')), findsOneWidget);
    expect(find.byType(CustomPaint), findsWidgets);
  });

  testWidgets('faults change digits, labels, and settle behavior', (
    tester,
  ) async {
    const faults = Faults(
      arabicIndicDigits: true,
      duplicateLabels: true,
      slowSettle: true,
    );
    await tester.pumpWidget(const HaykalApp(faults: faults));

    expect(find.text('٣٩٫٩٥ ر.س'), findsOneWidget);
    expect(find.text('عرض'), findsNWidgets(2));
    await tester.tap(find.byKey(const Key('surface-semanticsOff')));
    await tester.pump();
    expect(find.byKey(const Key('slow-settle')), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 1200));
    expect(find.byKey(const Key('semantics-off')), findsOneWidget);
  });
}
