package com.biokpl.gridwatch

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.drawable.Icon
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PhotoImageComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 5 dk'lık mum. */
data class Bar(val o: Double, val h: Double, val l: Double, val c: Double)

/** Gün içi 5 dk mumlar — Yahoo (BIST ~15 dk gecikmeli), 5 dk önbellek. */
object Intraday {
    private val mutex = Mutex()
    private val cache = HashMap<String, Pair<Long, List<Bar>>>()

    suspend fun bars(symbol: String): List<Bar> = mutex.withLock {
        if (symbol.isEmpty()) return emptyList()
        cache[symbol]?.let { if (System.currentTimeMillis() - it.first < 5 * 60_000L) return it.second }
        val bars = withContext(Dispatchers.IO) {
            runCatching {
                val u = URL("https://query1.finance.yahoo.com/v8/finance/chart/$symbol.IS?interval=5m&range=1d")
                val c = u.openConnection() as HttpURLConnection
                c.setRequestProperty("User-Agent", "Mozilla/5.0")
                c.connectTimeout = 15_000; c.readTimeout = 15_000
                val body = try { c.inputStream.bufferedReader().use { it.readText() } } finally { c.disconnect() }
                val q = JSONObject(body).getJSONObject("chart").getJSONArray("result").getJSONObject(0)
                    .getJSONObject("indicators").getJSONArray("quote").getJSONObject(0)
                val o = q.getJSONArray("open"); val h = q.getJSONArray("high")
                val l = q.getJSONArray("low"); val cl = q.getJSONArray("close")
                (0 until cl.length()).mapNotNull { i ->
                    if (cl.isNull(i) || o.isNull(i)) null
                    else Bar(o.getDouble(i), h.getDouble(i), l.getDouble(i), cl.getDouble(i))
                }
            }.getOrDefault(emptyList())
        }
        if (bars.isNotEmpty()) cache[symbol] = System.currentTimeMillis() to bars
        bars.ifEmpty { cache[symbol]?.second ?: emptyList() }
    }
}

private const val TEAL = 0xFF3CE1AA.toInt()
private const val RED = 0xFFFF5A50.toInt()
private const val NEON = 0xFF00E6FF.toInt()
private const val MAGENTA = 0xFFFF3CC8.toInt()

/** A kadranı: parlayan çizgi grafik (şeffaf zemin). */
fun sparkBitmap(bars: List<Bar>, w: Int = 220, h: Int = 110): Bitmap {
    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    val closes = bars.map { it.c }
    if (closes.size < 2) return bmp
    val lo = closes.min(); val hi = closes.max(); val span = (hi - lo).takeIf { it > 0 } ?: 1.0
    val pad = 10f
    val path = Path()
    closes.forEachIndexed { i, v ->
        val x = pad + (w - 2 * pad) * i / (closes.size - 1)
        val y = (h - pad) - (h - 2 * pad) * ((v - lo) / span).toFloat()
        if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    val col = if (closes.last() >= closes.first()) TEAL else RED
    val cv = Canvas(bmp)
    cv.drawPath(path, Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 9f; color = col; alpha = 60
        strokeJoin = Paint.Join.ROUND; strokeCap = Paint.Cap.ROUND
    })
    cv.drawPath(path, Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 3.5f; color = col
        strokeJoin = Paint.Join.ROUND; strokeCap = Paint.Cap.ROUND
    })
    return bmp
}

/** C kadranı: mum grafik + stop/hedef çizgileri (şeffaf zemin). */
fun candleBitmap(bars: List<Bar>, stop: Double, target: Double, w: Int = 300, h: Int = 110): Bitmap {
    val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
    if (bars.isEmpty()) return bmp
    // 5 dk mumları 18 mumda topla (okunur kalsın)
    val n = 18
    val chunk = ((bars.size + n - 1) / n).coerceAtLeast(1)
    val agg = bars.chunked(chunk).map { g -> Bar(g.first().o, g.maxOf { it.h }, g.minOf { it.l }, g.last().c) }
    var lo = agg.minOf { it.l }; var hi = agg.maxOf { it.h }
    if (stop > 0) lo = minOf(lo, stop); if (target > 0) hi = maxOf(hi, target)
    val span = (hi - lo).takeIf { it > 0 } ?: 1.0
    val pad = 6f
    fun y(v: Double) = (h - pad) - (h - 2 * pad) * ((v - lo) / span).toFloat()
    val cv = Canvas(bmp)
    val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { strokeWidth = 2f; pathEffect = DashPathEffect(floatArrayOf(8f, 6f), 0f) }
    if (stop > 0) cv.drawLine(0f, y(stop), w.toFloat(), y(stop), line.apply { color = RED })
    if (target > 0) cv.drawLine(0f, y(target), w.toFloat(), y(target), line.apply { color = 0xFF5AF0A0.toInt() })
    val cw = (w - 2 * pad - 30f) / agg.size
    val p = Paint(Paint.ANTI_ALIAS_FLAG)
    agg.forEachIndexed { i, b ->
        val xc = pad + cw * i + cw / 2
        p.color = if (b.c >= b.o) NEON else MAGENTA
        p.strokeWidth = 2f
        cv.drawLine(xc, y(b.h), xc, y(b.l), p)
        val top = y(maxOf(b.o, b.c)); val bot = maxOf(y(minOf(b.o, b.c)), top + 2f)
        cv.drawRect(xc - cw * 0.32f, top, xc + cw * 0.32f, bot, p)
    }
    val last = agg.last()
    val lx = pad + cw * (agg.size - 1) + cw / 2
    cv.drawCircle(lx, y(last.c), 9f, Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; alpha = 70 })
    cv.drawCircle(lx, y(last.c), 5f, Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE })
    return bmp
}

private fun photo(bmp: Bitmap, desc: String): ComplicationData =
    PhotoImageComplicationData.Builder(Icon.createWithBitmap(bmp), PlainComplicationText.Builder(desc).build()).build()

/** Pozisyondaki (yoksa önerilen) hissenin gün içi çizgi grafiği. */
class SparkComplicationService : SuspendingComplicationDataSourceService() {
    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        if (request.complicationType != ComplicationType.PHOTO_IMAGE) return NoDataComplicationData()
        val s = AlSatRepo.get(applicationContext)
        return photo(sparkBitmap(Intraday.bars(s.symbol.ifEmpty { "XU100" }), 180, 120), "${s.symbol} grafik")
    }
    override fun getPreviewData(type: ComplicationType): ComplicationData? = null
}

/** Mum grafik + stop/hedef çizgileri. */
class CandleComplicationService : SuspendingComplicationDataSourceService() {
    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        if (request.complicationType != ComplicationType.PHOTO_IMAGE) return NoDataComplicationData()
        val s = AlSatRepo.get(applicationContext)
        return photo(candleBitmap(Intraday.bars(s.symbol.ifEmpty { "XU100" }), s.stop, s.target), "${s.symbol} mum")
    }
    override fun getPreviewData(type: ComplicationType): ComplicationData? = null
}
