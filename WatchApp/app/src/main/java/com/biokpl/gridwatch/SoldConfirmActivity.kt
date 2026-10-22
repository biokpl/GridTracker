package com.biokpl.gridwatch

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.wear.tiles.TileService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Kutucuktaki SATTIM düğmesi → onay ekranı. "Evet, sattım" sayfadaki Sattım butonuyla
 * aynı komutu yazar (fiyat boş → monitor anlık fiyatı tahmin olarak kullanır; sonra kalemle düzeltilebilir).
 */
class SoldConfirmActivity : Activity() {
    private val scope = CoroutineScope(Dispatchers.Main)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dp = resources.displayMetrics.density
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            setBackgroundColor(Color.BLACK); setPadding((20 * dp).toInt(), 0, (20 * dp).toInt(), 0)
        }
        setContentView(root)
        scope.launch {
            val s = AlSatRepo.get(applicationContext)
            build(root, s, dp)
        }
    }

    private fun tv(t: String, sp: Float, c: Int, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = sp; setTextColor(c); gravity = Gravity.CENTER
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun build(root: LinearLayout, s: Snapshot, dp: Float) {
        if (s.mode != Snapshot.Mode.ACTIVE) {
            root.addView(tv("Açık pozisyon yok", 16f, Color.WHITE, true))
            return
        }
        root.addView(tv("${s.symbol} sattın mı?", 18f, 0xFFF1EFE8.toInt(), true))
        root.addView(tv("${s.qty} lot · ~${fmtPrice(s.price)}", 13f, 0xFFB4B2A9.toInt()))
        root.addView(tv("(fiyatı sonra kalemle düzeltebilirsin)", 10f, 0xFF6E6E6A.toInt()))
        val yes = tv("EVET, SATTIM", 15f, 0xFFFFBEBE.toInt(), true).apply {
            background = GradientDrawable().apply {
                cornerRadius = 22 * dp; setColor(0xFF5A181A.toInt())
                setStroke((1.5f * dp).toInt(), 0xFFE24B4A.toInt())
            }
            setPadding((22 * dp).toInt(), (10 * dp).toInt(), (22 * dp).toInt(), (10 * dp).toInt())
            setOnClickListener {
                isEnabled = false; text = "Gönderiliyor…"
                scope.launch {
                    val ok = AlSatRepo.sendAction("sold", s.symbol)
                    Toast.makeText(
                        this@SoldConfirmActivity,
                        if (ok) "Satış kaydedildi" else "Bağlantı hatası", Toast.LENGTH_SHORT
                    ).show()
                    TileService.getUpdater(applicationContext).requestUpdate(AlSatTileService::class.java)
                    finish()
                }
            }
        }
        root.addView(yes, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = (14 * dp).toInt() })
        root.addView(tv("Vazgeç", 14f, 0xFF96968F.toInt()).apply {
            setPadding(0, (12 * dp).toInt(), 0, (8 * dp).toInt()); setOnClickListener { finish() }
        })
    }
}
