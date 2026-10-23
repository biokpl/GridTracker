package com.biokpl.gridwatch

import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationText
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.RangedValueComplicationData
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService

/*
 * Kadran 4 ayrı yuvadan okur (WFF kadranı ağa çıkamaz, veriyi komplikasyonlar taşır):
 *   Halka   → fiyatın stop→hedef aralığındaki yeri (RANGED_VALUE)
 *   K/Z     → başlık = hisse, metin = K/Z; değerin İŞARETİ rengi belirler (RANGED_VALUE)
 *   Stop    → "S 351,45"  (SHORT_TEXT)
 *   Hedef   → "H 394,27"  (SHORT_TEXT)
 */

private fun t(s: String): ComplicationText = PlainComplicationText.Builder(s).build()

private fun short(s: String, desc: String = s): ComplicationData =
    ShortTextComplicationData.Builder(t(s), t(desc)).build()

private fun ranged(v: Float, min: Float, max: Float, title: String, text: String): ComplicationData =
    RangedValueComplicationData.Builder(v.coerceIn(min, max), min, max, t("$title $text"))
        .setTitle(t(title)).setText(t(text)).build()

private val PREVIEW = Snapshot(
    Snapshot.Mode.ACTIVE, symbol = "TUPRS", price = 384.90, pnlTl = 582.0, pnlPct = 2.5, qty = 62,
    stop = 351.45, target = 394.27, entry = 375.50, stopLoss = 368.72, signal = "DEVAM",
)

private fun ringData(s: Snapshot): ComplicationData = when (s.mode) {
    // Premium kadranlar halkanın metinlerini panelde alt satır olarak kullanır:
    //   TITLE = yüzde değişim / durum,  TEXT = "62 LOT · 384,90"
    Snapshot.Mode.ACTIVE -> ranged(s.progress, 0f, 1f, fmtPct(s.pnlPct), "${s.qty} LOT · ${fmtPrice(s.price)}")
    Snapshot.Mode.PICK -> ranged(1f, 0f, 1f, if (s.halfLot) "YARIM LOT" else "ÖNERİ", "${s.lots} LOT · ${fmtPrice(s.price)}")
    Snapshot.Mode.WAIT -> ranged(s.winRate / 100f, 0f, 1f, "%${s.winRate} İSABET", "${s.trades} İŞLEM")
    Snapshot.Mode.NO_DATA -> ranged(0f, 0f, 1f, "AL/SAT", "VERİ YOK")
}

/** K/Z değeri: >0 yeşil, <0 kırmızı, 0 nötr (kadran rengi buna göre seçer). */
private fun kzData(s: Snapshot): ComplicationData = when (s.mode) {
    Snapshot.Mode.ACTIVE -> ranged(
        when { s.pnlTl > 0 -> 1f; s.pnlTl < 0 -> -1f; else -> 0f }, -1f, 1f, s.symbol, fmtTl(s.pnlTl))
    Snapshot.Mode.PICK -> ranged(0.5f, -1f, 1f, s.symbol,
        "${s.lots} lot al" + if (s.halfLot) " ½" else "")
    Snapshot.Mode.WAIT -> ranged(0f, -1f, 1f, "Bekle", fmtTl(s.totalPnl))
    Snapshot.Mode.NO_DATA -> ranged(0f, -1f, 1f, "AL/SAT", "—")
}

/*
 * Stop / Hedef yuvaları metnin yanında halka iç çeperindeki bölge çizgilerini de taşır
 * (kadranda 8 yuva sınırı dolu olduğu için ayrı yuva yok):
 *   Stop  → değer = kurum stopunun halkadaki yeri  → kırmızı çizgi: halka başı → kurum stopu
 *   Hedef → min = kurum stopu, değer = izleme stopu → amber çizgi: kurum stopu → izleme stopu
 * Pozisyon yokken değerler 0 (çizgi görünmez). Konumlar her güncellemede yeniden hesaplanır.
 */
private fun stopText(s: Snapshot): String = when {
    s.stop > 0 && s.mode != Snapshot.Mode.WAIT -> "S:  ${fmtPrice(s.stop)}"
    s.mode == Snapshot.Mode.WAIT -> "${s.trades} işlem"
    else -> " "
}

private fun targetText(s: Snapshot): String = when {
    s.target > 0 && s.mode != Snapshot.Mode.WAIT -> "H:  ${fmtPrice(s.target)}"
    s.mode == Snapshot.Mode.WAIT -> "%${s.winRate} isabet"
    else -> " "
}

private fun stopData(s: Snapshot): ComplicationData {
    val hard = s.ringPos(s.stop).coerceAtLeast(0f)
    // max = canlılık bayrağı: 1 → ONLINE, 1.5 → OFFLINE (kadran [RANGED_VALUE_MAX] ile okur)
    return ranged(hard, 0f, if (s.live) 1f else 1.5f, " ", stopText(s))
}

private fun targetData(s: Snapshot): ComplicationData {
    val hard = s.ringPos(s.stop).coerceAtLeast(0f)
    val soft = s.ringPos(s.stopLoss).coerceAtLeast(0f)
    return ranged(maxOf(soft, hard), hard, 1f, " ", targetText(s))
}

abstract class DualService(
    private val ranged: (Snapshot) -> ComplicationData,
    private val text: (Snapshot) -> String,
) : SuspendingComplicationDataSourceService() {
    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        MinuteTicker.ensure(applicationContext)
        val s = AlSatRepo.get(applicationContext)
        android.util.Log.d("GridWatch", "${javaClass.simpleName} type=${request.complicationType} mode=${s.mode} entry=${s.entry} stop=${s.stop} sl=${s.stopLoss} tgt=${s.target} pos=${s.ringPos(s.stop)}")
        return when (request.complicationType) {
            ComplicationType.RANGED_VALUE -> ranged(s)
            ComplicationType.SHORT_TEXT -> short(text(s))
            else -> NoDataComplicationData()
        }
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData? = when (type) {
        ComplicationType.RANGED_VALUE -> ranged(PREVIEW)
        ComplicationType.SHORT_TEXT -> short(text(PREVIEW))
        else -> null
    }
}

abstract class BaseService(
    private val type: ComplicationType,
    private val build: (Snapshot) -> ComplicationData,
) : SuspendingComplicationDataSourceService() {
    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData {
        MinuteTicker.ensure(applicationContext)
        return if (request.complicationType != type) NoDataComplicationData()
        else build(AlSatRepo.get(applicationContext))
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData? =
        if (type == this.type) build(PREVIEW) else null
}

class RingComplicationService : BaseService(ComplicationType.RANGED_VALUE, ::ringData)
class KzComplicationService : BaseService(ComplicationType.RANGED_VALUE, ::kzData)
// RANGED_VALUE (A kadranı: metin + bölge çizgisi) ve SHORT_TEXT (diğer kadranlar: yalnız metin)
class StopComplicationService : DualService(::stopData, ::stopText)
class TargetComplicationService : DualService(::targetData, ::targetText)
