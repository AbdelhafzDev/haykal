package dev.haykal.refapps.matjar

import android.content.Context
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Switch
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                MatjarApp(this)
            }
        }
    }
}

private fun Context.fault(name: String): Boolean =
    getSharedPreferences("matjar", Context.MODE_PRIVATE).getBoolean("fault.$name", false)

private fun Context.saveOrder() {
    getSharedPreferences("matjar", Context.MODE_PRIVATE).edit().putBoolean("order.created", true).commit()
}

private fun Context.machineString(name: String, value: String) {
    getSharedPreferences("matjar", Context.MODE_PRIVATE).edit()
        .putString("machine.$name", value).commit()
}

private fun Context.machineInt(name: String, value: Int) {
    getSharedPreferences("matjar", Context.MODE_PRIVATE).edit()
        .putInt("machine.$name", value).commit()
}

private fun Context.incrementMachine(name: String) {
    val preferences = getSharedPreferences("matjar", Context.MODE_PRIVATE)
    preferences.edit().putInt("machine.$name", preferences.getInt("machine.$name", 0) + 1).commit()
}

private fun Context.appendMachineEvent(name: String) {
    val preferences = getSharedPreferences("matjar", Context.MODE_PRIVATE)
    val existing = preferences.getString("machine.event_log", "").orEmpty()
    val updated = if (existing.isEmpty()) name else "$existing\n$name"
    preferences.edit().putString("machine.event_log", updated).commit()
}

@Composable
@OptIn(ExperimentalComposeUiApi::class)
private fun MatjarApp(context: Context) {
    var screen by remember { mutableStateOf("home") }
    var basketCount by remember { mutableStateOf(0) }
    var promoVisible by remember { mutableStateOf(context.fault("promo_modal")) }
    var settling by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { context.machineString("screen", "home") }
    val rtlPrice = if (context.fault("arabic_indic_digits")) "٥٥٫٢٠ ر.س" else "55.20 SAR"
    val navigate: (String) -> Unit = { target ->
        if (context.fault("slow_settle")) {
            settling = true
            scope.launch {
                delay(1500)
                screen = target
                context.machineString("screen", target)
                settling = false
            }
        } else {
            screen = target
            context.machineString("screen", target)
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().semantics { testTagsAsResourceId = true }.padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("متجر Matjar", style = MaterialTheme.typography.headlineMedium)
        Text("screen:$screen", modifier = Modifier.testTag("machine_screen"))
        if (settling) {
            CircularProgressIndicator(modifier = Modifier.testTag("slow_settle"))
        } else when (screen) {
            "home" -> HomeScreen(onNavigate = navigate)
            "view" -> ViewBaseline()
            "webview" -> WebStorefront()
            "compose" -> ComposeList()
            "search" -> SearchScreen(onResults = { navigate("results") })
            "results" -> ResultsScreen(
                sparse = context.fault("sparse_cards"),
                duplicateLabels = context.fault("duplicate_labels"),
                onProduct = { navigate("product") },
            )
            "product" -> ProductScreen(
                unavailable = context.fault("option_unavailable"),
                onAdd = {
                    basketCount += 1
                    context.machineInt("basket_count", basketCount)
                    navigate("basket")
                },
            )
            "basket" -> BasketScreen(
                count = basketCount,
                minimumOrder = context.fault("minimum_order"),
                onCheckout = {
                    navigate(if (context.fault("otp_challenge")) "otp" else "checkout")
                },
            )
            "otp" -> Text("رمز التحقق مطلوب • OTP required")
            "checkout" -> CheckoutScreen(
                total = if (context.fault("price_change")) "58.00 SAR" else rtlPrice,
                timeout = context.fault("submit_timeout"),
                addressBlocked = context.fault("address_out_of_area"),
                onSubmit = {
                    context.incrementMachine("submit_count")
                    context.appendMachineEvent("submit_order")
                    if (context.fault("payment_decline")) {
                        navigate("declined")
                    } else {
                        context.saveOrder()
                        if (context.fault("submit_created_no_confirm")) {
                            (context as? MainActivity)?.finish()
                        } else if (context.fault("submit_timeout")) {
                            // Deliberately remain on checkout after accepting the tap. The
                            // runtime must reconcile through Orders without tapping twice.
                        } else {
                            navigate("confirmation")
                        }
                    }
                },
            )
            "confirmation" -> Text(
                "تم الطلب بنجاح • رقم الطلب ••••7312",
                modifier = Modifier.testTag("confirmation"),
            )
            "declined" -> Text("تعذر الدفع Payment declined")
            "orders" -> OrdersScreen(context)
        }
        Spacer(Modifier.weight(1f))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = { navigate("home") }) { Text("الرئيسية") }
            TextButton(onClick = { navigate("orders") }, modifier = Modifier.testTag("orders_nav")) {
                Text("الطلبات")
            }
        }
    }

    if (promoVisible) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("عرض خاص") },
            text = { Text("خصم تجريبي") },
            confirmButton = { Button(onClick = { promoVisible = false }) { Text("إغلاق") } },
        )
    }
}

@Composable
private fun HomeScreen(onNavigate: (String) -> Unit) {
    Button(onClick = { onNavigate("search") }, modifier = Modifier.testTag("search_button")) {
        Text("بحث عن مطعم أو طبق")
    }
    Button(onClick = { onNavigate("view") }) { Text("Android View baseline") }
    Button(onClick = { onNavigate("compose") }) { Text("Compose lazy list") }
    Button(onClick = { onNavigate("webview") }) { Text("WebView storefront") }
}

@Composable
private fun SearchScreen(onResults: () -> Unit) {
    var query by remember { mutableStateOf("") }
    androidx.compose.material3.OutlinedTextField(
        value = query,
        onValueChange = { query = it },
        label = { Text("بحث") },
        modifier = Modifier.fillMaxWidth().testTag("search_box"),
    )
    Button(onClick = onResults, modifier = Modifier.testTag("show_results")) {
        Text("اعرض النتائج")
    }
}

@Composable
private fun ResultsScreen(sparse: Boolean, duplicateLabels: Boolean, onProduct: () -> Unit) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.testTag("results")) {
        items((1..12).toList()) { index ->
            val semantics = if (sparse) Modifier.clearAndSetSemantics {} else Modifier
            Card(
                onClick = onProduct,
                modifier = semantics.fillMaxWidth().testTag("result_$index"),
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text(
                        if (index == 1) "بيتزا هت" else "مطعم بيتزا $index",
                        modifier = Modifier.testTag("restaurant_$index"),
                    )
                    Text("بيبروني لارج", modifier = Modifier.testTag("item_$index"))
                    Text("4.${index % 10}", modifier = Modifier.testTag("rating_$index"))
                    Text("${40 + index} SAR", modifier = Modifier.testTag("price_$index"))
                    Text("فتح العرض")
                    if (duplicateLabels && index == 1) Button(onClick = {}) { Text("فتح العرض") }
                }
            }
        }
    }
}

@Composable
private fun ProductScreen(unavailable: Boolean, onAdd: () -> Unit) {
    Text("بيبروني لارج", modifier = Modifier.testTag("product_name"))
    Row { RadioButton(selected = true, onClick = {}, enabled = !unavailable); Text("كبير Large") }
    Button(onClick = onAdd, enabled = !unavailable, modifier = Modifier.testTag("add_to_basket")) {
        Text("أضف إلى السلة")
    }
}

@Composable
private fun BasketScreen(count: Int, minimumOrder: Boolean, onCheckout: () -> Unit) {
    Text("السلة • $count", modifier = Modifier.testTag("basket_badge"))
    if (minimumOrder) Text("الحد الأدنى للطلب 75 SAR")
    Button(
        onClick = onCheckout,
        enabled = !minimumOrder,
        modifier = Modifier.testTag("checkout_button"),
    ) { Text("متابعة إلى الدفع") }
}

@Composable
private fun CheckoutScreen(
    total: String,
    timeout: Boolean,
    addressBlocked: Boolean,
    onSubmit: () -> Unit,
) {
    Text("بيتزا هت", modifier = Modifier.testTag("checkout_merchant"))
    Text("1 × بيبروني لارج", modifier = Modifier.testTag("checkout_item"))
    Text("العنوان")
    Text("المنزل •••• 182", modifier = Modifier.testTag("checkout_address"))
    Text("طريقة الدفع")
    Text("بطاقة محفوظة •••• 4242", modifier = Modifier.testTag("checkout_payment"))
    Text("الإجمالي")
    Text(total, modifier = Modifier.testTag("total"))
    if (addressBlocked) Text("العنوان خارج نطاق التوصيل")
    if (timeout) CircularProgressIndicator(modifier = Modifier.testTag("submit_pending"))
    Button(
        onClick = onSubmit,
        enabled = !addressBlocked,
        modifier = Modifier.testTag("place_order"),
    ) { Text("إتمام الطلب") }
}

@Composable
private fun OrdersScreen(context: Context) {
    val created = context.getSharedPreferences("matjar", Context.MODE_PRIVATE)
        .getBoolean("order.created", false)
    Text("الطلبات", modifier = Modifier.testTag("orders_heading"))
    if (created) {
        Text("بيتزا هت", modifier = Modifier.testTag("order_merchant"))
        Text("55.20 SAR", modifier = Modifier.testTag("order_total"))
        Text("••••7312", modifier = Modifier.testTag("order_id"))
    } else Text("لا توجد طلبات", modifier = Modifier.testTag("orders_empty"))
}

@Composable
private fun ComposeList() {
    LazyColumn { items((1..50).toList()) { Text("عنصر $it", Modifier.padding(12.dp)) } }
}

@Composable
@Suppress("SetJavaScriptEnabled")
private fun WebStorefront() {
    AndroidView(
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = false
                loadDataWithBaseURL(
                    null,
                    "<html dir='rtl'><body><label>بحث المتجر</label><input aria-label='بحث المتجر'><button>بحث</button><p>بيتزا ٤٢ ر.س</p></body></html>",
                    "text/html",
                    "UTF-8",
                    null,
                )
            }
        },
        modifier = Modifier.fillMaxSize(),
    )
}

@Composable
@Suppress("DEPRECATION")
private fun ViewBaseline() {
    AndroidView(
        factory = { context ->
            LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                addView(EditText(context).apply { hint = "الاسم" })
                addView(Switch(context).apply { text = "الإشعارات" })
                addView(Button(context).apply { text = "حفظ" })
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                )
            }
        },
    )
}
