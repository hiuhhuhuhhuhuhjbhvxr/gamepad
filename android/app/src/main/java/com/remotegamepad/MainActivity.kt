package com.remotegamepad

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.util.Collections
import kotlin.concurrent.thread

/**
 * Start screen: finds the PC host by UDP broadcast (port 26761) or lets you type its address,
 * then opens the PC's own gamepad web page in a full-screen WebView (same GUI as the PC console).
 * Works over Wi-Fi, Ethernet-bridged LAN, USB tethering and Bluetooth tethering (all plain IP).
 */
class MainActivity : Activity() {
    private lateinit var list: LinearLayout
    private lateinit var status: TextView
    private lateinit var addrBox: EditText
    @Volatile private var scanning = false
    private val found = LinkedHashSet<String>()

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("rg", MODE_PRIVATE)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(24))
            setBackgroundColor(Color.parseColor("#0F1115"))
        }
        fun text(t: String, size: Float, color: String = "#E8EAF0") = TextView(this).apply {
            this.text = t; textSize = size; setTextColor(Color.parseColor(color))
        }
        root.addView(text("Game Pad Remote", 26f))
        root.addView(text("Run the Game Pad Remote program on your PC first. " +
            "Phone and PC must be on the same Wi-Fi / network (or use USB or Bluetooth tethering).", 13f, "#9AA3B5").apply { setPadding(0, dp(6), 0, dp(12)) })

        status = text("", 14f, "#7DD3FC")
        root.addView(status)
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(list)
        root.addView(Button(this).apply { text = "Search again"; setOnClickListener { scan() } })

        root.addView(text("Or type the PC address shown in the PC window:", 13f, "#9AA3B5").apply { setPadding(0, dp(18), 0, 0) })
        addrBox = EditText(this).apply {
            hint = "192.168.1.20  or  192.168.1.20:8080"
            setSingleLine(); inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(prefs.getString("addr", "")); setTextColor(Color.WHITE); setHintTextColor(Color.GRAY)
        }
        root.addView(addrBox)
        root.addView(Button(this).apply { text = "Connect"; setOnClickListener { open(addrBox.text.toString()) } })
        setContentView(ScrollView(this).apply { addView(root); setBackgroundColor(Color.parseColor("#0F1115")) })
        scan()
    }

    private fun open(addr: String) {
        val a = addr.trim()
        if (a.isEmpty()) { Toast.makeText(this, "Enter the PC address", Toast.LENGTH_SHORT).show(); return }
        getSharedPreferences("rg", MODE_PRIVATE).edit().putString("addr", a).apply()
        startActivity(Intent(this, GamepadActivity::class.java).putExtra("addr", a))
    }

    private fun addHost(name: String, addr: String) {
        list.addView(Button(this).apply {
            text = "$name  ($addr)"
            setOnClickListener { addrBox.setText(addr); open(addr) }
        })
    }

    private fun broadcastTargets(): List<InetAddress> {
        val out = ArrayList<InetAddress>()
        try { out.add(InetAddress.getByName("255.255.255.255")) } catch (e: Exception) { }
        try {
            for (ni in Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp || ni.isLoopback) continue
                for (ia in ni.interfaceAddresses) {
                    val b = ia.broadcast
                    if (b != null && !out.contains(b)) out.add(b)
                }
            }
        } catch (e: Exception) { }
        return out
    }

    private fun scan() {
        if (scanning) return
        scanning = true
        found.clear(); list.removeAllViews()
        status.text = "Searching for your PC..."
        thread {
            try {
                val sock = DatagramSocket()
                sock.broadcast = true
                sock.soTimeout = 400
                val msg = "RGDISCOVER".toByteArray()
                val targets = broadcastTargets()
                val buf = ByteArray(256)
                val end = System.currentTimeMillis() + 3500
                var nextSend = 0L
                while (System.currentTimeMillis() < end) {
                    if (System.currentTimeMillis() >= nextSend) {
                        for (t in targets) {
                            try { sock.send(DatagramPacket(msg, msg.size, t, 26761)) } catch (e: Exception) { }
                        }
                        nextSend = System.currentTimeMillis() + 800
                    }
                    try {
                        val p = DatagramPacket(buf, buf.size)
                        sock.receive(p)
                        val txt = String(p.data, 0, p.length)
                        if (txt.startsWith("RGHOST|")) {
                            val parts = txt.split("|")
                            val addr = p.address.hostAddress + ":" + parts[1]
                            val name = if (parts.size > 2) parts[2] else "PC"
                            if (found.add(addr)) runOnUiThread { addHost(name, addr) }
                        }
                    } catch (e: SocketTimeoutException) { }
                }
                sock.close()
            } catch (e: Exception) {
                // fall through to the status message
            } finally {
                scanning = false
                runOnUiThread {
                    status.text = if (found.isEmpty())
                        "No PC found automatically. Check the PC program is running and on the same network, or type its address below."
                    else "Tap your PC:"
                }
            }
        }
    }
}
