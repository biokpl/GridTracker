package com.biokpl.gridwatch

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.NumberFormat
import java.util.Locale

/** Saatte gösterilecek AL/SAT durumu. */
data class Snapshot(
    val mode: Mode,
    val symbol: String = "",
    val price: Double = 0.0,
    val pnlTl: Double = 0.0,
    val pnlPct: Double = 0.0,
    val qty: Int = 0,
    val stop: Double = 0.0,      // kurumdaki STOP emri (hard_stop)
    val target: Double = 0.0,
    val signal: String = "",
    val lots: Int = 0,
    val entryLow: Double = 0.0,
    val entryHigh: Double = 0.0,
    val halfLot: Boolean = false,
    val totalPnl: Double = 0.0,
    val trades: Int = 0,
    val winRate: Int = 0,
    val updated: String = "",
) {
    enum class Mode { ACTIVE, PICK, WAIT, NO_DATA }

    /** Fiyatın stop→hedef aralığındaki yeri (0..1). */
    val progress: Float
        get() = if (target > stop && stop > 0) ((price - stop) / (target - stop)).coerceIn(0.0, 1.0).toFloat() else 0f
}

private val TR = Locale("tr", "TR")
fun fmtPrice(v: Double): String = NumberFormat.getNumberInstance(TR).apply {
    minimumFractionDigits = 2; maximumFractionDigits = 2
}.format(v)

fun fmtTl(v: Double, signed: Boolean = true): String {
    val s = NumberFormat.getNumberInstance(TR).apply { maximumFractionDigits = 0 }.format(kotlin.math.abs(v))
    val sign = if (!signed) "" else if (v >= 0) "+" else "−"
    return "$sign$s ₺"
}

fun fmtPct(v: Double): String {
    val s = NumberFormat.getNumberInstance(TR).apply { minimumFractionDigits = 1; maximumFractionDigits = 1 }
        .format(kotlin.math.abs(v))
    return (if (v >= 0) "+%" else "−%") + s
}

/**
 * Firebase'deki gridtracker/advisor düğümünü okur (sayfa ile aynı kaynak).
 * 4 komplikasyon + kutucuk aynı anda istediğinde ağ 60 sn'de bir kez kullanılır;
 * ağ yoksa son başarılı veri (SharedPreferences) gösterilir.
 */
object AlSatRepo {
    private const val URL_ADVISOR =
        "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor.json"
    private const val TTL_MS = 60_000L
    private val mutex = Mutex()
    private var cache: Snapshot? = null
    private var cacheTs = 0L

    suspend fun get(ctx: Context): Snapshot = mutex.withLock {
        val now = System.currentTimeMillis()
        cache?.let { if (now - cacheTs < TTL_MS) return it }
        val prefs = ctx.getSharedPreferences("alsat", Context.MODE_PRIVATE)
        val body = fetch() ?: prefs.getString("last", null)
        if (body != null) prefs.edit().putString("last", body).apply()
        val snap = body?.let { runCatching { parse(it) }.getOrNull() } ?: Snapshot(Snapshot.Mode.NO_DATA)
        cache = snap; cacheTs = now
        snap
    }

    private suspend fun fetch(): String? = withContext(Dispatchers.IO) {
        runCatching {
            val c = URL(URL_ADVISOR).openConnection() as HttpURLConnection
            c.connectTimeout = 15_000; c.readTimeout = 15_000
            try {
                if (c.responseCode != 200) null else c.inputStream.bufferedReader().use { it.readText() }
            } finally { c.disconnect() }
        }.getOrNull()
    }

    private fun JSONObject.str(k: String): String {
        if (isNull(k)) return ""
        return optString(k, "").let { if (it == "null") "" else it }
    }

    private fun parse(text: String): Snapshot {
        val root = JSONObject(text)
        val tr = root.optJSONObject("tracker") ?: JSONObject()
        val perf = tr.optJSONObject("perf") ?: JSONObject()
        val total = tr.optDouble("history_pnl_total", 0.0)
        val trades = perf.optInt("trades", 0)
        val wr = perf.optInt("win_rate", 0)
        val updated = root.str("ts_str")
        val active = tr.str("active_symbol")

        if (active.isNotEmpty()) {
            val stop = tr.optDouble("hard_stop", 0.0).takeIf { it > 0 } ?: tr.optDouble("stop_loss", 0.0)
            val sig = root.optJSONObject("exit_signal")?.str("signal") ?: ""
            return Snapshot(
                Snapshot.Mode.ACTIVE, symbol = active,
                price = tr.optDouble("current_price", 0.0),
                pnlTl = tr.optDouble("unrealized_pnl", 0.0),
                pnlPct = tr.optDouble("unrealized_pct", 0.0),
                qty = tr.optInt("open_qty", tr.optInt("total_qty", 0)),
                stop = stop, target = tr.optDouble("target1", 0.0),
                signal = if (sig == "—") "DEVAM" else sig,
                totalPnl = total, trades = trades, winRate = wr, updated = updated,
            )
        }

        val picks = root.optJSONArray("top_picks")
        val noTrade = root.optBoolean("no_trade_today", false)
        if (!noTrade && picks != null && picks.length() > 0) {
            val p = picks.getJSONObject(0)
            val sym = p.str("symbol")
            val li = root.optJSONObject("lot_info")?.optJSONObject(sym) ?: JSONObject()
            val ez = p.optJSONObject("entry_zone") ?: JSONObject()
            val stop = p.optDouble("hard_stop", 0.0).takeIf { it > 0 } ?: p.optDouble("stop_loss", 0.0)
            return Snapshot(
                Snapshot.Mode.PICK, symbol = sym, price = p.optDouble("price", 0.0),
                stop = stop, target = p.optDouble("target1", 0.0),
                lots = li.optInt("lots_main", li.optInt("lots", 0)),
                entryLow = ez.optDouble("low", 0.0), entryHigh = ez.optDouble("high", 0.0),
                halfLot = li.optBoolean("regime_half", false),
                totalPnl = total, trades = trades, winRate = wr, updated = updated,
            )
        }
        return Snapshot(Snapshot.Mode.WAIT, totalPnl = total, trades = trades, winRate = wr, updated = updated)
    }
}
