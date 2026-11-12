package com.remotegamepad

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.view.Surface
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import kotlin.math.atan2

/**
 * Shows the PC's gamepad page full screen. The page and the PC protocol are identical to the PC
 * browser console. The app only adds what a web page cannot do on plain http: motion sensors and vibration.
 * JS bridge (window.RGNative): setMode(0 off|1 tilt|2 gyro), setSens(n), vibrate(ms).
 * Motion values go back to the page through window.rgMotion(tilt, gyroX, gyroY).
 */
class GamepadActivity : Activity(), SensorEventListener {
    private lateinit var web: WebView
    private lateinit var sm: SensorManager
    private var mode = 0
    private var sens = 5f
    private var tilt = 0f
    private var lastPush = 0L

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    @Suppress("DEPRECATION")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
            View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        sm = getSystemService(Context.SENSOR_SERVICE) as SensorManager

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#0F1115"))
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.setSupportZoom(false)
        web.addJavascriptInterface(Bridge(), "RGNative")
        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) {
                    Toast.makeText(this@GamepadActivity,
                        "Cannot reach the PC. Is the PC program running, and are both on the same network?",
                        Toast.LENGTH_LONG).show()
                    finish()
                }
            }
        }
        setContentView(web)

        var addr = (intent.getStringExtra("addr") ?: "").trim().removePrefix("http://").trimEnd('/')
        if (!addr.contains(":")) addr += ":8080"
        web.loadUrl("http://$addr/")
    }

    inner class Bridge {
        @JavascriptInterface
        fun setMode(m: Int) { runOnUiThread { mode = m; registerSensors() } }

        @JavascriptInterface
        fun setSens(s: Int) { sens = s.toFloat() }

        @JavascriptInterface
        fun vibrate(ms: Int) { buzz(ms.toLong()) }
    }

    @Suppress("DEPRECATION")
    private fun buzz(ms: Long) {
        val v = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator ?: return
        if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
        else v.vibrate(ms)
    }

    private fun registerSensors() {
        sm.unregisterListener(this)
        tilt = 0f
        if (mode == 1) sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let { sm.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
        if (mode == 2) sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let { sm.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
        if (mode == 0) push(0f, 0f, 0f)
    }

    private fun push(t: Float, gx: Float, gy: Float) {
        web.evaluateJavascript("window.rgMotion&&window.rgMotion($t,$gx,$gy)", null)
    }

    override fun onResume() { super.onResume(); web.onResume(); registerSensors() }
    override fun onPause() { super.onPause(); sm.unregisterListener(this); web.onPause() }
    override fun onDestroy() { sm.unregisterListener(this); web.destroy(); super.onDestroy() }
    override fun onAccuracyChanged(s: Sensor?, a: Int) {}

    @Suppress("DEPRECATION")
    override fun onSensorChanged(e: SensorEvent) {
        val rot = windowManager.defaultDisplay.rotation
        // device axes -> screen axes (landscape, either direction)
        val sx: Float
        val sy: Float
        if (rot == Surface.ROTATION_270) { sx = e.values[1]; sy = -e.values[0] } else { sx = -e.values[1]; sy = e.values[0] }
        var t = tilt
        var gx = 0f
        var gy = 0f
        if (e.sensor.type == Sensor.TYPE_ACCELEROMETER) {
            val deg = Math.toDegrees(atan2(-sx.toDouble(), sy.toDouble())).toFloat()
            val target = (deg / (60f / sens * 2f)).coerceIn(-1f, 1f)
            t = t * 0.7f + target * 0.3f
            tilt = t
        } else {
            val k = sens * 0.15f
            gx = (-sy * k).coerceIn(-1f, 1f)   // turn left/right
            gy = (-sx * k).coerceIn(-1f, 1f)   // look up/down
        }
        val now = SystemClock.uptimeMillis()
        if (now - lastPush >= 12) { lastPush = now; push(t, gx, gy) }
    }
}
