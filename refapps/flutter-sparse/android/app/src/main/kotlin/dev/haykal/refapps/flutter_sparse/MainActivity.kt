package dev.haykal.refapps.flutter_sparse

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "dev.haykal.refapps.flutter_sparse/faults",
        ).setMethodCallHandler { call, result ->
            if (call.method != "getFaults") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val preferences = getSharedPreferences("flutter_sparse", MODE_PRIVATE)
            result.success(
                FaultReceiver.allowedFaults.associateWith { name ->
                    preferences.getBoolean("fault.$name", false)
                },
            )
        }
    }
}
