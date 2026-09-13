package dev.haykal.refapps.flutter_sparse

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class FaultReceiver : BroadcastReceiver() {
    companion object {
        val allowedFaults = setOf(
            "arabic_indic_digits",
            "slow_settle",
            "duplicate_labels",
        )
    }

    override fun onReceive(context: Context, intent: Intent) {
        val preferences = context.getSharedPreferences("flutter_sparse", Context.MODE_PRIVATE)
        if (intent.action == "dev.haykal.refapp.RESET") {
            preferences.edit().clear().commit()
            return
        }
        if (intent.action != "dev.haykal.refapp.SET_FAULT") return
        val name = intent.getStringExtra("name") ?: return
        if (name !in allowedFaults) return
        val enabled = intent.getBooleanExtra("enabled", true)
        preferences.edit().putBoolean("fault.$name", enabled).commit()
    }
}
