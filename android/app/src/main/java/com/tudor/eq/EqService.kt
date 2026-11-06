package com.tudor.eq

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.bluetooth.BluetoothClass
import android.bluetooth.BluetoothManager
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.audiofx.AudioEffect
import android.media.audiofx.DynamicsProcessing
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Runs in the background, watches the audio outputs and keeps the EQ on only
 * while headphones (that the user has not switched off) are connected.
 *
 * The EQ itself is a DynamicsProcessing effect: on audio session 0 (the global
 * mix, all apps) by default, or - when that is not allowed on a phone - on each
 * player's own session, which players announce with
 * ACTION_OPEN_AUDIO_EFFECT_CONTROL_SESSION.
 */
class EqService : Service() {
    private lateinit var am: AudioManager
    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val effects = mutableMapOf<Int, DynamicsProcessing>()    // session -> effect
    private val sessions = mutableSetOf<Int>()                      // announced by players
    private var lastNote = ""

    private val devices = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = scan()
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = scan()
    }

    private val sessionReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            val id = i.getIntExtra(AudioEffect.EXTRA_AUDIO_SESSION, -1)
            if (id <= 0) return
            if (i.action == AudioEffect.ACTION_OPEN_AUDIO_EFFECT_CONTROL_SESSION) sessions += id
            else {
                sessions -= id
                effects.remove(id)?.release()
            }
            apply()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Store.init(this)
        am = getSystemService(AudioManager::class.java)
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, note("Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(1, note("Starting"))
        am.registerAudioDeviceCallback(devices, main)
        val f = IntentFilter().apply {
            addAction(AudioEffect.ACTION_OPEN_AUDIO_EFFECT_CONTROL_SESSION)
            addAction(AudioEffect.ACTION_CLOSE_AUDIO_EFFECT_CONTROL_SESSION)
        }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(sessionReceiver, f, RECEIVER_EXPORTED)
        else registerReceiver(sessionReceiver, f)
        scan()
        // Every edit (a band being dragged sends dozens a second) ends up here;
        // conflate + a short pause means the effect only hears the latest.
        scope.launch {
            combine(Store.state, Store.live) { s, l -> s to l.device }.conflate().collect {
                apply()
                delay(30)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!Store.state.value.enabled) {
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        am.unregisterAudioDeviceCallback(devices)
        unregisterReceiver(sessionReceiver)
        releaseAll()
        Store.live.update { it.copy(active = false, error = null) }
        super.onDestroy()
    }

    /** Which headphones are in, if any. Wireless first: a cable left in a DAC loses to the earbuds you just put on. */
    private fun scan() {
        val outs = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
        val hp = outs.filter { it.type in KINDS }.minByOrNull { KINDS.keys.indexOf(it.type) }
        if (hp == null) Store.connected(null, "", "", true)
        else {
            val name = hp.productName?.toString()?.trim().orEmpty().ifEmpty { KINDS[hp.type]!! }
            val worn = isWorn(hp, name)
            Store.connected("${hp.type}:$name", name, if (worn == false) "Bluetooth speaker" else KINDS[hp.type]!!,
                worn != false)
        }
    }

    /**
     * Bluetooth says what a device is: headphones, or a speaker / car stereo
     * that also plays over A2DP. Null when it can't tell (no permission, not
     * Bluetooth, unknown class) - those count as headphones.
     */
    @SuppressLint("MissingPermission")
    private fun isWorn(hp: AudioDeviceInfo, name: String): Boolean? {
        if (hp.type != AudioDeviceInfo.TYPE_BLUETOOTH_A2DP && hp.type != AudioDeviceInfo.TYPE_BLE_HEADSET) return null
        if (Build.VERSION.SDK_INT >= 31 &&
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) return null
        val bonded = runCatching { getSystemService(BluetoothManager::class.java).adapter.bondedDevices }.getOrNull()
            ?: return null
        val bt = bonded.firstOrNull { it.address.equals(hp.address, true) } ?: bonded.firstOrNull { it.name == name }
            ?: return null
        val cls = bt.bluetoothClass ?: return null
        if (cls.majorDeviceClass != BluetoothClass.Device.Major.AUDIO_VIDEO) return null
        return when (cls.deviceClass) {
            BluetoothClass.Device.AUDIO_VIDEO_HEADPHONES, BluetoothClass.Device.AUDIO_VIDEO_WEARABLE_HEADSET,
            BluetoothClass.Device.AUDIO_VIDEO_HANDSFREE -> true
            BluetoothClass.Device.AUDIO_VIDEO_UNCATEGORIZED -> null
            else -> false
        }
    }

    private fun apply() {
        val s = Store.state.value
        val key = Store.live.value.device
        val dev = key?.let { s.devices[it] }
        val on = s.enabled && dev != null && dev.enabled

        if (!on) {
            releaseAll()
            Store.live.update { it.copy(active = false, error = null) }
            update(when {
                dev == null -> "Standby · no headphones"
                else -> "Off for ${dev.name}"
            })
            return
        }

        val bands = Store.applied(s)
        val gains = Filters.sample(bands)
        val pre = if (s.autoPreamp) Filters.autoPreamp(bands).toFloat() else 0f
        val wanted = if (s.perSession) sessions.toSet() else setOf(0)
        effects.keys.filter { it !in wanted }.forEach { effects.remove(it)?.release() }

        var err: String? = null
        for (id in wanted) {
            try {
                val dp = effects.getOrPut(id) { create(id) }
                push(dp, gains, pre)
                if (!dp.hasControl()) err = "Another app's EQ has priority"
            } catch (e: Exception) {
                Log.w(TAG, "session $id", e)
                effects.remove(id)?.release()
                err = if (id == 0) "This phone blocks global EQ - switch to Per-app in Settings"
                      else "Could not attach to a player"
            }
        }
        val active = effects.isNotEmpty()
        Store.live.update { it.copy(active = active, error = err) }
        update(when {
            active -> "${s.selected} · ${dev!!.name}"
            s.perSession -> "Waiting for a player · ${dev!!.name}"
            else -> err ?: "Not running"
        })
    }

    private fun create(session: Int): DynamicsProcessing {
        val cfg = DynamicsProcessing.Config.Builder(
            DynamicsProcessing.VARIANT_FAVOR_FREQUENCY_RESOLUTION, 2,
            true, Filters.BANDS, false, 0, false, 0, true,
        ).setPreferredFrameDuration(10f).build()
        return DynamicsProcessing(Int.MAX_VALUE, session, cfg).also { it.enabled = true }
    }

    private fun push(dp: DynamicsProcessing, gains: FloatArray, preamp: Float) {
        val eq = DynamicsProcessing.Eq(true, true, Filters.BANDS)
        for (i in 0 until Filters.BANDS) eq.setBand(i, DynamicsProcessing.EqBand(true, Filters.cutoffs[i], gains[i]))
        dp.setPreEqAllChannelsTo(eq)
        dp.setInputGainAllChannelsTo(preamp)
        // Safety net only: with auto preamp the curve never goes above 0 dB.
        dp.setLimiterAllChannelsTo(DynamicsProcessing.Limiter(true, true, 0, 1f, 60f, 10f, -0.5f, 0f))
        if (!dp.enabled) dp.enabled = true
    }

    private fun releaseAll() {
        effects.values.forEach { runCatching { it.release() } }
        effects.clear()
    }

    // ---- notification

    private fun update(text: String) {
        if (text == lastNote) return
        lastNote = text
        getSystemService(NotificationManager::class.java).notify(1, note(text))
    }

    private fun note(text: String): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "EQ status", NotificationManager.IMPORTANCE_MIN)
            .apply { setShowBadge(false) })
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_eq)
            .setContentTitle("EQ")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "EQ"
        private const val CHANNEL = "status"

        /** Output types that count as headphones, in order of preference. */
        val KINDS = linkedMapOf(
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP to "Bluetooth",
            AudioDeviceInfo.TYPE_BLE_HEADSET to "Bluetooth LE",
            AudioDeviceInfo.TYPE_HEARING_AID to "Hearing aid",
            AudioDeviceInfo.TYPE_USB_HEADSET to "USB headset",
            AudioDeviceInfo.TYPE_USB_DEVICE to "USB DAC",
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES to "Wired",
            AudioDeviceInfo.TYPE_WIRED_HEADSET to "Wired",
        )

        fun start(ctx: Context) {
            if (Store.state.value.enabled) ctx.startForegroundService(Intent(ctx, EqService::class.java))
        }

        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, EqService::class.java))
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        Store.init(c)
        EqService.start(c)
    }
}
