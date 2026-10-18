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
    stop = 351.45, target = 394.27, signal = "DEVAM",
)

private fun ringData(s: Snapshot): ComplicationData = when (s.mode) {
    Snapshot.Mode.ACTIVE -> ranged(s.progress, 0f, 1f, s.symbol, fmtPrice(s.price))
    Snapshot.Mode.PICK -> ranged(1f, 0f, 1f, s.symbol, "öneri")
    Snapshot.Mode.WAIT -> ranged(s.winRate / 100f, 0f, 1f, "isabet", "%${s.winRate}")
    Snapshot.Mode.NO_DATA -> ranged(0f, 0f, 1f, "AL/SAT", "veri yok")
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

private fun stopData(s: Snapshot): ComplicationData =
    if (s.stop > 0 && s.mode != Snapshot.Mode.WAIT) short("S ${fmtPrice(s.stop)}", "Stop ${fmtPrice(s.stop)}")
    else if (s.mode == Snapshot.Mode.WAIT) short("${s.trades} işlem")
    else short(" ")

private fun targetData(s: Snapshot): ComplicationData =
    if (s.target > 0 && s.mode != Snapshot.Mode.WAIT) short("H ${fmtPrice(s.target)}", "Hedef ${fmtPrice(s.target)}")
    else if (s.mode == Snapshot.Mode.WAIT) short("%${s.winRate} isabet")
    else short(" ")

abstract class BaseService(
    private val type: ComplicationType,
    private val build: (Snapshot) -> ComplicationData,
) : SuspendingComplicationDataSourceService() {
    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData =
        if (request.complicationType != type) NoDataComplicationData()
        else build(AlSatRepo.get(applicationContext))

    override fun getPreviewData(type: ComplicationType): ComplicationData? =
        if (type == this.type) build(PREVIEW) else null
}

class RingComplicationService : BaseService(ComplicationType.RANGED_VALUE, ::ringData)
class KzComplicationService : BaseService(ComplicationType.RANGED_VALUE, ::kzData)
class StopComplicationService : BaseService(ComplicationType.SHORT_TEXT, ::stopData)
class TargetComplicationService : BaseService(ComplicationType.SHORT_TEXT, ::targetData)
