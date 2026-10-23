package com.biokpl.gridwatch

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceUpdateRequester
import java.util.Calendar
import java.util.TimeZone

/**
 * Borsa açıkken kadran yuvalarını DAKİKADA BİR yeniler.
 * Wear OS/Samsung, yuvaların kendi güncelleme süresini en az ~5 dk'ya sınırlıyor;
 * bu zamanlayıcı yuvalara her dakika "yenilen" der. Borsa kapalıyken ertesi açılışa
 * kadar uyur. Ekran kapalıyken (Doze) Android alarmları kendisi seyreltir → pil korunur.
 */
object MinuteTicker {
    private const val REQ = 4711
    private val SERVICES = listOf(
        RingComplicationService::class.java, KzComplicationService::class.java,
        StopComplicationService::class.java, TargetComplicationService::class.java,
        SparkComplicationService::class.java, CandleComplicationService::class.java,
    )

    private fun pending(ctx: Context): PendingIntent = PendingIntent.getBroadcast(
        ctx, REQ, Intent(ctx, TickReceiver::class.java),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    /** Sonraki tetikleme: açıkken +60 sn, kapalıyken bir sonraki açılış (09:55). */
    private fun nextAt(): Long {
        val now = System.currentTimeMillis()
        if (marketOpen()) return now + 60_000L
        val c = Calendar.getInstance(TimeZone.getTimeZone("Europe/Istanbul"))
        c.set(Calendar.SECOND, 0); c.set(Calendar.MILLISECOND, 0)
        val m = c.get(Calendar.HOUR_OF_DAY) * 60 + c.get(Calendar.MINUTE)
        if (m >= 595) c.add(Calendar.DAY_OF_MONTH, 1)
        c.set(Calendar.HOUR_OF_DAY, 9); c.set(Calendar.MINUTE, 55)
        while (c.get(Calendar.DAY_OF_WEEK) == Calendar.SATURDAY || c.get(Calendar.DAY_OF_WEEK) == Calendar.SUNDAY)
            c.add(Calendar.DAY_OF_MONTH, 1)
        return c.timeInMillis
    }

    fun schedule(ctx: Context) {
        val am = ctx.getSystemService(AlarmManager::class.java) ?: return
        val at = nextAt(); val pi = pending(ctx)
        runCatching {
            if (am.canScheduleExactAlarms()) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
        }.onFailure { am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi) }
    }

    /** Yuva istekleri ve açılışta çağrılır: alarm yoksa kurar (zararsız, idempotent değil ama
     *  FLAG_UPDATE_CURRENT aynı alarmı günceller). */
    fun ensure(ctx: Context) {
        val exists = PendingIntent.getBroadcast(
            ctx, REQ, Intent(ctx, TickReceiver::class.java),
            PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE,
        ) != null
        if (!exists) schedule(ctx.applicationContext)
    }

    fun tick(ctx: Context) {
        if (marketOpen()) {
            Log.d("GridWatch", "dakika tiki — yuvalar yenileniyor")
            for (cls in SERVICES)
                ComplicationDataSourceUpdateRequester.create(ctx, ComponentName(ctx, cls)).requestUpdateAll()
        }
        schedule(ctx)
    }
}

class TickReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED -> MinuteTicker.schedule(context.applicationContext)
            else -> MinuteTicker.tick(context.applicationContext)
        }
    }
}
