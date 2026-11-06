package com.tudor.eq

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

object Ui {
    val BLACK = Color(0xFF000000)
    val WHITE = Color(0xFFFFFFFF)
    val GREY = Color(0xFFB1B3B3)
    val CARD = Color(0xFF111111)
    val CARD2 = Color(0xFF1A1A1A)
    val LINE = Color(0xFF262626)
    val MUT = Color(0xFF6B6B6B)
    val RED = Color(0xFFD71920)
    val MONO = FontFamily.Monospace
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Store.init(this)
        // Bluetooth: to tell headphones from a speaker or a car that also plays music
        val want = listOfNotNull(
            Manifest.permission.POST_NOTIFICATIONS.takeIf { Build.VERSION.SDK_INT >= 33 },
            Manifest.permission.BLUETOOTH_CONNECT.takeIf { Build.VERSION.SDK_INT >= 31 },
        ).filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (want.isNotEmpty()) requestPermissions(want.toTypedArray(), 1)
        EqService.start(this)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Ui.WHITE, background = Ui.BLACK,
                surface = Ui.CARD, onSurface = Ui.WHITE)) {
                App()
            }
        }
    }
}

// ---------------------------------------------------------------- bits

@Composable
fun Mono(text: String, color: Color = Ui.GREY, size: Int = 11) =
    Text(text.uppercase(), color = color, fontSize = size.sp, fontFamily = Ui.MONO, letterSpacing = 1.sp)

@Composable
fun Card(content: @Composable ColumnScope.() -> Unit) = Column(
    Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp)).background(Ui.CARD).padding(16.dp),
    verticalArrangement = Arrangement.spacedBy(10.dp), content = content)

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Pill(text: String, on: Boolean = false, color: Color = Ui.GREY, onLong: (() -> Unit)? = null, onClick: () -> Unit) =
    Box(Modifier.clip(CircleShape)
        .background(if (on) Ui.WHITE else Color.Transparent)
        .border(1.dp, if (on) Ui.WHITE else Color(0xFF333333), CircleShape)
        .combinedClickable(onClick = onClick, onLongClick = onLong)
        .padding(horizontal = 14.dp, vertical = 7.dp)) {
        Text(text, color = if (on) Ui.BLACK else color, fontSize = 14.sp)
    }

@Composable
fun Toggle(checked: Boolean, onChange: (Boolean) -> Unit) = Switch(checked, onChange,
    colors = SwitchDefaults.colors(checkedTrackColor = Ui.RED, checkedThumbColor = Ui.WHITE,
        uncheckedTrackColor = Ui.CARD2, uncheckedThumbColor = Ui.MUT, uncheckedBorderColor = Ui.LINE))

@Composable
fun Row2(title: String, sub: String? = null, end: @Composable () -> Unit) =
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = Ui.WHITE, fontSize = 15.sp)
            if (sub != null) Text(sub, color = Ui.MUT, fontSize = 12.sp)
        }
        end()
    }

@Composable
fun Labeled(label: String, value: String, pos: Float, onChange: (Float) -> Unit) = Column {
    Row(Modifier.fillMaxWidth()) {
        Mono(label, Ui.MUT)
        Spacer(Modifier.weight(1f))
        Mono(value, Ui.WHITE)
    }
    Slider(pos, onChange, colors = SliderDefaults.colors(thumbColor = Ui.WHITE, activeTrackColor = Ui.WHITE,
        inactiveTrackColor = Ui.LINE))
}

fun hz(f: Double) = if (f >= 1000) "${round2(f / 1000)} kHz" else "${f.toInt()} Hz"

fun db(g: Double) = (if (g > 0) "+" else "") + "%.1f dB".format(g)

// ---------------------------------------------------------------- screen

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun App() {
    val ctx = LocalContext.current
    val s by Store.state.collectAsState()
    val live by Store.live.collectAsState()
    var sel by remember { mutableIntStateOf(-1) }
    var dialog by remember { mutableStateOf<String?>(null) }      // "new", "rename:<name>", "autoeq:<key>"
    var menu by remember { mutableStateOf<String?>(null) }

    val bands = Store.current(s)
    val dev = live.device?.let { s.devices[it] }
    val correction = if (dev?.autoeqOn == true) dev.autoeq?.bands.orEmpty() else emptyList()
    if (sel >= bands.size) sel = -1
    LaunchedEffect(s.selected) { sel = -1 }

    fun toast(t: String) = Toast.makeText(ctx, t, Toast.LENGTH_SHORT).show()
    fun setBand(i: Int, b: Band) = Store.setBands(bands.toMutableList().also { it[i] = b })

    val importer = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        try {
            val text = ctx.contentResolver.openInputStream(uri)!!.bufferedReader().readText()
            toast("Added: " + Store.import(text).joinToString())
        } catch (e: Exception) {
            toast("Import failed: ${e.message}")
        }
    }
    val exporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        ctx.contentResolver.openOutputStream(uri)?.use { it.write(Store.export().toByteArray()) }
        toast("Exported ${s.presets.size} presets")
    }

    Column(Modifier.fillMaxSize().background(Ui.BLACK).safeDrawingPadding().verticalScroll(rememberScrollState())
        .padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {

        // ---- header + status
        Row(Modifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("EQ", color = Ui.WHITE, fontSize = 34.sp, fontFamily = Ui.MONO, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Toggle(s.enabled) { on ->
                Store.edit { it.copy(enabled = on) }
                if (on) EqService.start(ctx) else EqService.stop(ctx)
            }
        }
        Card {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(if (live.active) Ui.RED else Ui.MUT))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(dev?.name ?: "No headphones", color = Ui.WHITE, fontSize = 17.sp)
                    Mono(when {
                        !s.enabled -> "EQ off"
                        dev == null -> "Standby · connect headphones"
                        !dev.enabled -> "EQ off for these headphones"
                        live.active -> "Active · ${s.selected}" + if (correction.isNotEmpty()) " + AutoEQ" else ""
                        s.perSession -> "Waiting for a player to open"
                        else -> "Not running"
                    }, if (live.active) Ui.GREY else Ui.MUT)
                }
                if (dev != null) Toggle(dev.enabled) { Store.setDevice(dev.copy(enabled = it)) }
            }
            live.error?.let { Text(it, color = Ui.RED, fontSize = 13.sp) }
        }

        // ---- graph
        Card {
            Graph(bands, correction, sel, onSelect = { sel = it },
                onMove = { i, b -> setBand(i, b) },
                onAdd = { b ->
                    val nb = (bands + b).sortedBy { it.freq }
                    Store.setBands(nb)
                    sel = nb.indexOf(b)
                })
            val pre = Filters.autoPreamp(correction + bands)
            Mono(if (bands.isEmpty()) "Double-tap the graph to add a band"
                 else "Preamp ${if (s.autoPreamp) db(pre) else "off"} · drag points · double-tap to add", Ui.MUT, 10)
        }

        // ---- presets
        Card {
            Mono("Presets" + (dev?.let { " · for ${it.name}" } ?: ""))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (name in s.presets.keys) Box {
                    Pill(name, on = name == s.selected, onLong = { menu = name }) { Store.select(name) }
                    DropdownMenu(menu == name, { menu = null }) {
                        DropdownMenuItem({ Text("Rename") }, { menu = null; dialog = "rename:$name" })
                        DropdownMenuItem({ Text("Duplicate") }, {
                            menu = null; Store.newPreset(name, s.presets[name].orEmpty())
                        })
                        if (s.presets.size > 1) DropdownMenuItem({ Text("Delete", color = Ui.RED) }, {
                            menu = null; Store.delete(name)
                        })
                    }
                }
                Pill("+ New") { dialog = "new" }
            }
            Mono("Long-press a preset to rename or delete", Ui.MUT, 10)
        }

        // ---- bands
        Card {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Mono("Bands")
                Spacer(Modifier.weight(1f))
                Pill("+ Band") {
                    val nb = (bands + Band("bell", 1000.0, 0.0, 1.0)).sortedBy { it.freq }
                    Store.setBands(nb)
                    sel = nb.indexOfLast { it.freq == 1000.0 }
                }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                bands.forEachIndexed { i, b ->
                    Pill("${i + 1} · ${hz(b.freq)}", on = i == sel, color = if (b.on) Ui.GREY else Ui.MUT) {
                        sel = if (sel == i) -1 else i
                    }
                }
            }
            if (sel in bands.indices) {
                val b = bands[sel]
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (t in Filters.TYPES) Pill(Filters.LABEL[t]!!, on = b.type == t) {
                        setBand(sel, b.copy(type = t, q = if (t == "lowcut" || t == "highcut") 0.707 else b.q))
                    }
                }
                Labeled("Frequency", hz(b.freq), logSlider(b.freq, Filters.F_MIN, Filters.F_MAX)) {
                    setBand(sel, b.copy(freq = round(fromLogSlider(it, Filters.F_MIN, Filters.F_MAX))))
                }
                if (Filters.hasGain(b.type)) Labeled("Gain", db(b.gain), ((b.gain + DB_RANGE) / (2 * DB_RANGE)).toFloat()) {
                    setBand(sel, b.copy(gain = round1(it * 2 * DB_RANGE - DB_RANGE)))
                }
                Labeled("Q", "%.2f".format(b.q), logSlider(b.q, 0.1, 10.0)) {
                    setBand(sel, b.copy(q = round2(fromLogSlider(it, 0.1, 10.0))))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Pill(if (b.on) "Bypass" else "Turn on") { setBand(sel, b.copy(on = !b.on)) }
                    Pill("Delete", color = Ui.RED) {
                        Store.setBands(bands.filterIndexed { i, _ -> i != sel }); sel = -1
                    }
                }
            }
        }

        // ---- headphones
        Card {
            Mono("Headphones")
            if (s.devices.isEmpty()) Text("Connect headphones once and they show up here.", color = Ui.MUT, fontSize = 13.sp)
            for (d in s.devices.values.sortedBy { it.name }) {
                val now = d.key == live.device
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Ui.CARD2).padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row2(d.name, (if (now) "Connected · " else "") + "${d.kind} · preset ${d.preset}") {
                        Toggle(d.enabled) { Store.setDevice(d.copy(enabled = it)) }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Mono("AutoEQ", Ui.MUT, 10)
                            Text(d.autoeq?.name ?: "None", color = if (d.autoeq != null) Ui.GREY else Ui.MUT, fontSize = 13.sp)
                        }
                        Pill(if (d.autoeq == null) "Find" else "Change") { dialog = "autoeq:${d.key}" }
                        if (d.autoeq != null) {
                            Spacer(Modifier.width(6.dp))
                            Toggle(d.autoeqOn) { Store.setDevice(d.copy(autoeqOn = it)) }
                        }
                    }
                }
            }
            Text("EQ runs only while headphones switched on here are connected. " +
                "Turn off a car or speaker that connects over Bluetooth.", color = Ui.MUT, fontSize = 12.sp)
        }

        // ---- settings
        Card {
            Mono("Settings")
            Row2("Auto preamp", "Lowers the volume by the curve's highest boost, so it never clips") {
                Toggle(s.autoPreamp) { on -> Store.edit { it.copy(autoPreamp = on) } }
            }
            Row2("Per-app mode", "Use if the global EQ does nothing. Works with players that support " +
                "an external equalizer (Spotify: Settings > Playback > Equalizer)") {
                Toggle(s.perSession) { on -> Store.edit { it.copy(perSession = on) } }
            }
            val pm = ctx.getSystemService(PowerManager::class.java)
            if (!pm.isIgnoringBatteryOptimizations(ctx.packageName)) {
                Row2("Battery optimisation", "Allow EQ to run in the background, or the phone may stop it") {
                    Pill("Allow") {
                        ctx.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:${ctx.packageName}")))
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pill("Import from PC") { importer.launch(arrayOf("application/json", "*/*")) }
                Pill("Export") { exporter.launch("eq-presets.json") }
            }
        }
        Spacer(Modifier.heightIn(min = 24.dp))
    }

    // ---- dialogs
    when {
        dialog == "new" -> NameDialog("New preset", "", { dialog = null }) { Store.newPreset(it, bands) }
        dialog?.startsWith("rename:") == true -> {
            val old = dialog!!.removePrefix("rename:")
            NameDialog("Rename", old, { dialog = null }) { Store.rename(old, it) }
        }
        dialog?.startsWith("autoeq:") == true -> {
            val d = s.devices[dialog!!.removePrefix("autoeq:")]
            if (d == null) dialog = null
            else AutoEqDialog(d, { dialog = null }) { Store.setDevice(d.copy(autoeq = it, autoeqOn = it != null)) }
        }
    }
}

@Composable
fun NameDialog(title: String, initial: String, close: () -> Unit, done: (String) -> Unit) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(close, title = { Text(title) },
        text = { OutlinedTextField(text, { text = it }, singleLine = true) },
        confirmButton = { TextButton({ if (text.isNotBlank()) { done(text); close() } }) { Text("OK") } },
        dismissButton = { TextButton(close) { Text("Cancel") } },
        containerColor = Ui.CARD)
}

@Composable
fun AutoEqDialog(d: Headphone, close: () -> Unit, done: (Correction?) -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var q by remember { mutableStateOf(d.autoeq?.name ?: d.name) }
    var busy by remember { mutableStateOf(false) }
    val hits = remember(q) { AutoEq.search(ctx, q) }
    AlertDialog(close, title = { Text("AutoEQ for ${d.name}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Measured correction to a neutral target, from the AutoEQ project.", color = Ui.MUT, fontSize = 12.sp)
                OutlinedTextField(q, { q = it }, singleLine = true, placeholder = { Text("Search model") })
                if (busy) Mono("Downloading…")
                LazyColumn(Modifier.heightIn(max = 320.dp)) {
                    items(hits) { e ->
                        Column(Modifier.fillMaxWidth().clickable(enabled = !busy) {
                            busy = true
                            scope.launch {
                                try {
                                    done(withContext(Dispatchers.IO) { AutoEq.load(ctx, e) })
                                    close()
                                } catch (ex: Exception) {
                                    Toast.makeText(ctx, ex.message ?: "Download failed", Toast.LENGTH_LONG).show()
                                }
                                busy = false
                            }
                        }.padding(vertical = 8.dp)) {
                            Text(e.name, color = Ui.WHITE, fontSize = 14.sp)
                            Text(e.source, color = Ui.MUT, fontSize = 11.sp)
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(close) { Text("Close") } },
        dismissButton = { if (d.autoeq != null) TextButton({ done(null); close() }) { Text("Remove", color = Ui.RED) } },
        containerColor = Ui.CARD)
}
