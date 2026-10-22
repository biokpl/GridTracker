package com.biokpl.gridwatch

import androidx.concurrent.futures.SuspendToFutureAdapter
import androidx.wear.protolayout.ActionBuilders
import androidx.wear.protolayout.ColorBuilders.argb
import androidx.wear.protolayout.ModifiersBuilders
import androidx.wear.protolayout.DimensionBuilders.degrees
import androidx.wear.protolayout.DimensionBuilders.dp
import androidx.wear.protolayout.DimensionBuilders.expand
import androidx.wear.protolayout.DimensionBuilders.sp
import androidx.wear.protolayout.LayoutElementBuilders
import androidx.wear.protolayout.LayoutElementBuilders.Arc
import androidx.wear.protolayout.LayoutElementBuilders.ArcLine
import androidx.wear.protolayout.LayoutElementBuilders.Box
import androidx.wear.protolayout.LayoutElementBuilders.Column
import androidx.wear.protolayout.LayoutElementBuilders.FontStyle
import androidx.wear.protolayout.LayoutElementBuilders.LayoutElement
import androidx.wear.protolayout.LayoutElementBuilders.Row
import androidx.wear.protolayout.LayoutElementBuilders.Spacer
import androidx.wear.protolayout.LayoutElementBuilders.Text
import androidx.wear.protolayout.ResourceBuilders
import androidx.wear.protolayout.TimelineBuilders
import androidx.wear.tiles.RequestBuilders
import androidx.wear.tiles.TileBuilders
import androidx.wear.tiles.TileService
import com.google.common.util.concurrent.ListenableFuture

private const val GRAY_TRACK = 0xFF2C2C2A.toInt()
private const val TEAL = 0xFF5DCAA5.toInt()
private const val TEAL_LIGHT = 0xFF9FE1CB.toInt()
private const val PURPLE = 0xFFAFA9EC.toInt()
private const val AMBER = 0xFFFAC775.toInt()
private const val CORAL = 0xFFE24B4A.toInt()
private const val RED_SOFT = 0xFFF09595.toInt()
private const val GREEN_SOFT = 0xFF97C459.toInt()
private const val WHITE = 0xFFF1EFE8.toInt()
private const val GRAY = 0xFFB4B2A9.toInt()
private const val GRAY_DARK = 0xFF5F5E5A.toInt()
private const val CYAN = 0xFF22D3EE.toInt()
private const val ICE = 0xFF7DD3FC.toInt()
private const val ID_HOLD = "hold"

/** Kaydırınca açılan detay kutucuğu — tasarım taslağındaki 3 durum. */
class AlSatTileService : TileService() {

    override fun onTileRequest(requestParams: RequestBuilders.TileRequest): ListenableFuture<TileBuilders.Tile> =
        SuspendToFutureAdapter.launchFuture {
            // BEKLE / DEVAM ET düğmesi: kutucuk yeniden istenir, komut burada gönderilir
            if (requestParams.currentState.lastClickableId == ID_HOLD) {
                val cur = AlSatRepo.get(applicationContext)
                if (cur.mode == Snapshot.Mode.ACTIVE)
                    AlSatRepo.sendAction(if (cur.hold) "hold_off" else "hold", cur.symbol)
            }
            val s = AlSatRepo.get(applicationContext)
            TileBuilders.Tile.Builder()
                .setResourcesVersion("1")
                .setFreshnessIntervalMillis(5 * 60_000L)
                .setTileTimeline(TimelineBuilders.Timeline.fromLayoutElement(layout(s)))
                .build()
        }

    override fun onTileResourcesRequest(
        requestParams: RequestBuilders.ResourcesRequest,
    ): ListenableFuture<ResourceBuilders.Resources> =
        SuspendToFutureAdapter.launchFuture { ResourceBuilders.Resources.Builder().setVersion("1").build() }

    private fun text(s: String, size: Float, color: Int, bold: Boolean = false): LayoutElement =
        Text.Builder().setText(s).setMaxLines(1).setFontStyle(
            FontStyle.Builder().setSize(sp(size)).setColor(argb(color))
                .setWeight(if (bold) LayoutElementBuilders.FONT_WEIGHT_MEDIUM else LayoutElementBuilders.FONT_WEIGHT_NORMAL)
                .build()
        ).build()

    private fun gap(h: Float): LayoutElement = Spacer.Builder().setHeight(dp(h)).build()

    private fun arc(start: Float, length: Float, color: Int, thick: Float = 6f): LayoutElement =
        Arc.Builder().setAnchorAngle(degrees(start)).setAnchorType(LayoutElementBuilders.ARC_ANCHOR_START)
            .addContent(ArcLine.Builder().setLength(degrees(length)).setThickness(dp(thick)).setColor(argb(color)).build())
            .build()

    private fun button(label: String, fg: Int, bg: Int, click: ModifiersBuilders.Clickable): LayoutElement =
        Box.Builder().setWidth(dp(64f)).setHeight(dp(28f))
            .setModifiers(
                ModifiersBuilders.Modifiers.Builder()
                    .setClickable(click)
                    .setBackground(
                        ModifiersBuilders.Background.Builder().setColor(argb(bg))
                            .setCorner(ModifiersBuilders.Corner.Builder().setRadius(dp(14f)).build()).build()
                    )
                    .setBorder(ModifiersBuilders.Border.Builder().setWidth(dp(1f)).setColor(argb(fg)).build())
                    .build()
            )
            .addContent(text(label, 12f, fg, true))
            .build()

    private fun buttons(s: Snapshot): LayoutElement {
        val sold = ModifiersBuilders.Clickable.Builder().setId("sold").setOnClick(
            ActionBuilders.LaunchAction.Builder().setAndroidActivity(
                ActionBuilders.AndroidActivity.Builder()
                    .setPackageName(packageName).setClassName(SoldConfirmActivity::class.java.name)
                    .build()
            ).build()
        ).build()
        val hold = ModifiersBuilders.Clickable.Builder().setId(ID_HOLD)
            .setOnClick(ActionBuilders.LoadAction.Builder().build()).build()
        return Row.Builder()
            .addContent(button("SATTIM", 0xFFFFBEBE.toInt(), 0xFF5A181A.toInt(), sold))
            .addContent(Spacer.Builder().setWidth(dp(8f)).build())
            .addContent(button(if (s.hold) "DEVAM ET" else "BEKLE", CYAN, 0xFF0A343E.toInt(), hold))
            .build()
    }

    private fun pair(left: String, lc: Int, right: String, rc: Int): LayoutElement =
        Row.Builder()
            .addContent(text(left, 13f, lc))
            .addContent(Spacer.Builder().setWidth(dp(12f)).build())
            .addContent(text(right, 13f, rc))
            .build()

    private fun layout(s: Snapshot): LayoutElement {
        val col = Column.Builder().setHorizontalAlignment(LayoutElementBuilders.HORIZONTAL_ALIGN_CENTER)
        val ring: LayoutElement
        when (s.mode) {
            Snapshot.Mode.ACTIVE -> {
                val sig = s.signal.ifEmpty { "DEVAM" }
                val sigColor = when {
                    s.hold -> ICE
                    sig == "DİKKAT" -> AMBER
                    sig == "ÇIK" || sig == "ACİL_ÇIK" -> CORAL
                    else -> TEAL_LIGHT
                }
                val sigText = if (s.hold) "BEKLEMEDE" else sig.replace('_', ' ')
                ring = arc(225f, 270f * s.progress, if (s.pnlTl >= 0) TEAL else CORAL)
                col.addContent(text("● $sigText", 12f, sigColor))
                    .addContent(text(s.symbol, 22f, WHITE, true))
                    .addContent(text(fmtTl(s.pnlTl), 24f, if (s.pnlTl >= 0) TEAL else CORAL, true))
                    .addContent(text("${fmtPrice(s.price)} · ${fmtPct(s.pnlPct)} · ${s.qty} lot", 12f, GRAY))
                    .addContent(gap(5f))
                    .addContent(pair("S ${fmtPrice(s.stop)}", RED_SOFT, "H ${fmtPrice(s.target)}", GREEN_SOFT))
                    .addContent(gap(6f))
                    .addContent(buttons(s))
                    .addContent(gap(4f))
                    .addContent(
                        if (s.live) text("● ONLINE · gecikmeli", 10f, 0xFF46E682.toInt())
                        else text("● OFFLINE", 10f, GRAY_DARK)
                    )
            }
            Snapshot.Mode.PICK -> {
                ring = arc(0f, 360f, PURPLE)
                col.addContent(text("GÜNÜN ÖNERİSİ", 12f, PURPLE))
                    .addContent(text(s.symbol, 22f, WHITE, true))
                    .addContent(text("${s.lots} lot al", 19f, TEAL, true))
                    .addContent(text("Giriş ${fmtPrice(s.entryLow)} – ${fmtPrice(s.entryHigh)}", 12f, GRAY))
                    .addContent(gap(4f))
                    .addContent(pair("Stop ${fmtPrice(s.stop)}", RED_SOFT, "Hedef ${fmtPrice(s.target)}", GREEN_SOFT))
                if (s.halfLot) col.addContent(gap(3f)).addContent(text("Piyasa zayıf · yarım lot", 12f, AMBER))
            }
            Snapshot.Mode.WAIT, Snapshot.Mode.NO_DATA -> {
                ring = arc(270f, 360f * s.winRate / 100f, TEAL)
                col.addContent(text("AL/SAT KAZANCI", 12f, GRAY))
                    .addContent(text(fmtTl(s.totalPnl), 24f, if (s.totalPnl >= 0) TEAL else CORAL, true))
                    .addContent(gap(4f))
                    .addContent(pair("${s.trades} işlem", WHITE, "%${s.winRate} isabet", WHITE))
                    .addContent(gap(4f))
                    .addContent(text(if (s.mode == Snapshot.Mode.WAIT) "Uygun hisse yok · bekle" else "Veri alınamadı", 12f, GRAY_DARK))
            }
        }
        return Box.Builder().setWidth(expand()).setHeight(expand())
            .setHorizontalAlignment(LayoutElementBuilders.HORIZONTAL_ALIGN_CENTER)
            .setVerticalAlignment(LayoutElementBuilders.VERTICAL_ALIGN_CENTER)
            .addContent(arc(0f, 360f, GRAY_TRACK))
            .addContent(ring)
            .addContent(col.build())
            .build()
    }
}
