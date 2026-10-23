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
    val entry: Double = 0.0,     // açık pozisyonun alış (ortalama) fiyatı
    val stopLoss: Double = 0.0,  // izleme stopu (saatlik kapanış onaylı; kurum stopu = stop)
    val signal: String = "",
    val lots: Int = 0,
    val entryLow: Double = 0.0,
    val entryHigh: Double = 0.0,
    val halfLot: Boolean = false,
    val totalPnl: Double = 0.0,
    val trades: Int = 0,
    val winRate: Int = 0,
    val updated: String = "",
    val live: Boolean = false,   // monitor son 10 dk içinde kalp attı (PC + piyasa açık)
    val hold: Boolean = false,   // "Beklemede Kalıyorum" modu
) {
    enum class Mode { ACTIVE, PICK, WAIT, NO_DATA }

    /**
     * Halkadaki yer (0..1).
     * Açık pozisyon: alışa sabit — tepe (0.5) = alış, sağ uç = hedef, sol uç = alıştan aynı mesafe aşağı.
     *   (Stop'a göre ölçeklemek, iz süren stop yükseldikçe halkayı yerinde sayıyormuş gibi gösteriyordu.)
     * Diğer durumlar: fiyatın stop→hedef aralığındaki yeri.
     */
    /** Bir fiyat seviyesinin halkadaki yeri (açık pozisyon, alışa sabit ölçek); yoksa -1. */
    fun ringPos(level: Double): Float =
        if (mode == Mode.ACTIVE && entry > 0 && target > entry && level > 0)
            (0.5 + 0.5 * (level - entry) / (target - entry)).coerceIn(0.0, 1.0).toFloat()
        else -1f

    val progress: Float
        get() = when {
            mode == Mode.ACTIVE && entry > 0 && target > entry ->
                (0.5 + 0.5 * (price - entry) / (target - entry)).coerceIn(0.0, 1.0).toFloat()
            target > stop && stop > 0 -> ((price - stop) / (target - stop)).coerceIn(0.0, 1.0).toFloat()
            else -> 0f
        }
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

/** BIST açık mı (hafta içi 09:55–18:15, İstanbul saati; resmi tatiller hariç tutulmaz). */
fun marketOpen(): Boolean {
    val c = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("Europe/Istanbul"))
    val d = c.get(java.util.Calendar.DAY_OF_WEEK)
    if (d == java.util.Calendar.SATURDAY || d == java.util.Calendar.SUNDAY) return false
    val m = c.get(java.util.Calendar.HOUR_OF_DAY) * 60 + c.get(java.util.Calendar.MINUTE)
    return m in 595..1095
}

/**
 * Firebase'deki gridtracker/advisor düğümünü okur (sayfa ile aynı kaynak).
 * 4 komplikasyon + kutucuk aynı anda istediğinde ağ 60 sn'de bir kez kullanılır;
 * ağ yoksa son başarılı veri (SharedPreferences) gösterilir.
 */
object AlSatRepo {
    private const val URL_ADVISOR =
        "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor.json"
    // Borsa açıkken veri ~her dakika tazelenir (yuvalar 60 sn'de bir ister);
    // kapalıyken fiyat değişmez → 30 dk'da bir ağa çıkılır (pil).
    private const val TTL_OPEN_MS = 50_000L
    private const val TTL_CLOSED_MS = 30 * 60_000L
    private const val URL_ACTION =
        "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor/userAction.json"
    private const val LIVE_SEC = 600L
    private val mutex = Mutex()
    private var cache: Snapshot? = null
    private var cacheTs = 0L

    suspend fun get(ctx: Context): Snapshot = mutex.withLock {
        val now = System.currentTimeMillis()
        val ttl = if (marketOpen()) TTL_OPEN_MS else TTL_CLOSED_MS
        cache?.let { if (now - cacheTs < ttl) return it }
        val prefs = ctx.getSharedPreferences("alsat", Context.MODE_PRIVATE)
        val body = fetch() ?: prefs.getString("last", null)
        if (body != null) prefs.edit().putString("last", body).apply()
        val snap = body?.let { runCatching { parse(it) }.getOrNull() } ?: Snapshot(Snapshot.Mode.NO_DATA)
        cache = snap; cacheTs = now
        snap
    }

    /** Sonraki get() ağdan taze okusun. */
    fun invalidate() { cacheTs = 0L }

    /** Saatten kullanıcı komutu (sayfadaki Sattım/Beklemede ile aynı kanal; PC'deki monitor işler). */
    suspend fun sendAction(action: String, symbol: String): Boolean = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        val body = JSONObject().put("action", action).put("symbol", symbol).put("ts", now)
            .put("id", "watch-$now-${(1000..9999).random()}").toString()
        val ok = runCatching {
            val c = URL(URL_ACTION).openConnection() as HttpURLConnection
            c.requestMethod = "PUT"; c.doOutput = true
            c.connectTimeout = 15_000; c.readTimeout = 15_000
            c.setRequestProperty("Content-Type", "application/json")
            try {
                c.outputStream.use { it.write(body.toByteArray()) }
                c.responseCode == 200
            } finally { c.disconnect() }
        }.getOrDefault(false)
        invalidate()
        ok
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
        val hb = root.optLong("heartbeat", 0L)
        val live = hb > 0 && System.currentTimeMillis() / 1000 - hb < LIVE_SEC
        return parseMode(root).copy(live = live)
    }

    private fun parseMode(root: JSONObject): Snapshot {
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
                entry = tr.optDouble("avg_cost", 0.0).takeIf { it > 0 } ?: tr.optDouble("entry_price", 0.0),
                stopLoss = tr.optDouble("stop_loss", 0.0),
                signal = if (sig == "—") "DEVAM" else sig,
                totalPnl = total, trades = trades, winRate = wr, updated = updated,
                hold = tr.optBoolean("hold", false),
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
