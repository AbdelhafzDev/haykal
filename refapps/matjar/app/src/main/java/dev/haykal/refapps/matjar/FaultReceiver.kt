package dev.haykal.refapps.matjar

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class FaultReceiver : BroadcastReceiver() {
    private val allowedFaults = setOf(
        "promo_modal",
        "price_change",
        "payment_decline",
        "submit_timeout",
        "submit_created_no_confirm",
        "option_unavailable",
        "minimum_order",
        "address_out_of_area",
        "otp_challenge",
        "sparse_cards",
        "arabic_indic_digits",
        "slow_settle",
        "duplicate_labels",
    )

    override fun onReceive(context: Context, intent: Intent) {
        val preferences = context.getSharedPreferences("matjar", Context.MODE_PRIVATE)
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
