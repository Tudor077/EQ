package com.tudor.eq

import android.content.Context
import android.util.AtomicFile
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

data class Band(
    val type: String = "bell",
    val freq: Double = 1000.0,
    val gain: Double = 0.0,
    val q: Double = 0.707,
    val on: Boolean = true,
)

/** Headphone correction from AutoEQ. It belongs to the headphones, not to a preset. */
data class Correction(val name: String, val folder: String, val bands: List<Band>)

/** A pair of headphones (or a USB DAC) the phone has played through. */
data class Headphone(
    val key: String,
    val name: String,
    val kind: String,
    val enabled: Boolean = true,        // EQ on while these are connected
    val preset: String = "Flat",
    val autoeq: Correction? = null,
    val autoeqOn: Boolean = false,
)

data class State(
    val enabled: Boolean = true,
    val autoPreamp: Boolean = true,
    val perSession: Boolean = false,    // attach to each player's audio session instead of the global mix
    val presets: LinkedHashMap<String, List<Band>> = linkedMapOf("Flat" to emptyList()),
    val selected: String = "Flat",
    val devices: Map<String, Headphone> = emptyMap(),
)

/** What the service sees right now. Not saved. */
data class Live(
    val device: String? = null,         // key of the headphones in use, null = none
    val active: Boolean = false,        // EQ actually running
    val error: String? = null,
)

/**
 * The one copy of the state, shared by the screen and the service (same
 * process). Every change is saved to files/state.json half a second after the
 * last one; the first start is seeded from assets/seed.json (the PC presets).
 */
object Store {
    val state = MutableStateFlow(State())
    val live = MutableStateFlow(Live())

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var file: AtomicFile? = null
    private var saveJob: Job? = null

    @Synchronized
    fun init(ctx: Context) {
        if (file != null) return
        val f = AtomicFile(File(ctx.filesDir, "state.json"))
        file = f
        state.value = try {
            fromJson(JSONObject(String(f.readFully())))
        } catch (e: Exception) {
            try {
                val seed = JSONObject(ctx.assets.open("seed.json").bufferedReader().readText())
                State(presets = readPresets(seed).ifEmpty { linkedMapOf("Flat" to emptyList()) })
            } catch (e: Exception) {
                State()
            }
        }
    }

    fun edit(fn: (State) -> State) {
        state.update(fn)
        saveJob?.cancel()
        saveJob = scope.launch {
            delay(500)
            save()
        }
    }

    private fun save() {
        val f = file ?: return
        val out = f.startWrite()
        try {
            out.write(toJson(state.value).toString(1).toByteArray())
            f.finishWrite(out)
        } catch (e: Exception) {
            f.failWrite(out)
        }
    }

    // ---- what gets applied

    fun current(s: State = state.value) = s.presets[s.selected] ?: emptyList()

    /** Headphone correction first, then the preset - like the PC app. */
    fun applied(s: State = state.value): List<Band> {
        val dev = live.value.device?.let { s.devices[it] }
        val ae = if (dev?.autoeqOn == true) dev.autoeq?.bands.orEmpty() else emptyList()
        return ae + current(s)
    }

    // ---- edits

    /** Picking a preset while headphones are in also makes it theirs. */
    fun select(name: String) = edit { s ->
        val dev = live.value.device?.let { s.devices[it] }
        s.copy(selected = name,
            devices = if (dev == null) s.devices else s.devices + (dev.key to dev.copy(preset = name)))
    }

    fun setBands(bands: List<Band>) = edit { s ->
        s.copy(presets = LinkedHashMap(s.presets).apply { put(s.selected, bands) })
    }

    fun setDevice(d: Headphone) = edit { s -> s.copy(devices = s.devices + (d.key to d)) }

    fun freeName(s: State, base: String): String {
        if (base !in s.presets) return base
        var i = 2
        while ("$base ($i)" in s.presets) i++
        return "$base ($i)"
    }

    fun newPreset(name: String, bands: List<Band>) {
        val s = state.value
        val n = freeName(s, name.trim().ifEmpty { "Preset" })
        edit { it.copy(presets = LinkedHashMap(it.presets).apply { put(n, bands) }) }
        select(n)
    }

    fun rename(old: String, new: String) = edit { s ->
        val n = new.trim()
        if (n.isEmpty() || n in s.presets) return@edit s
        val p = LinkedHashMap<String, List<Band>>()
        for ((k, v) in s.presets) p[if (k == old) n else k] = v
        s.copy(presets = p, selected = if (s.selected == old) n else s.selected,
            devices = s.devices.mapValues { (_, d) -> if (d.preset == old) d.copy(preset = n) else d })
    }

    fun delete(name: String) = edit { s ->
        if (s.presets.size <= 1) return@edit s
        val p = LinkedHashMap(s.presets).apply { remove(name) }
        val first = p.keys.first()
        s.copy(presets = p, selected = if (s.selected == name) first else s.selected,
            devices = s.devices.mapValues { (_, d) -> if (d.preset == name) d.copy(preset = first) else d })
    }

    /** Headphones came in: remember them and switch to their preset. Speakers start switched off. */
    fun connected(key: String?, name: String, kind: String, worn: Boolean) {
        if (key == null) {
            live.update { it.copy(device = null) }
            return
        }
        edit { s ->
            val d = s.devices[key] ?: Headphone(key, name, kind, enabled = worn, preset = s.selected)
            val preset = if (d.preset in s.presets) d.preset else s.selected
            s.copy(devices = s.devices + (key to d.copy(name = name, preset = preset)), selected = preset)
        }
        live.update { it.copy(device = key) }
    }

    /** Presets from a PC export (or its state.json). Nothing is overwritten. */
    fun import(text: String): List<String> {
        val add = readPresets(JSONObject(text))
        if (add.isEmpty()) throw IllegalArgumentException("no EQ presets in this file")
        val names = mutableListOf<String>()
        edit { s ->
            val p = LinkedHashMap(s.presets)
            for ((n, b) in add) {
                val free = freeName(State(presets = p), n)
                p[free] = b
                names += free
            }
            s.copy(presets = p)
        }
        return names
    }

    fun export(): String = JSONObject().apply {
        val s = state.value
        put("app", "eq"); put("version", 1)
        put("order", JSONArray(s.presets.keys.toList()))
        put("presets", JSONObject().apply {
            for ((n, b) in s.presets) put(n, JSONObject().put("bands", bandsJson(b)))
        })
    }.toString(1)

    // ---- JSON

    private fun bandJson(b: Band) = JSONObject().put("type", b.type).put("freq", b.freq)
        .put("gain", b.gain).put("q", b.q).put("on", b.on)

    private fun bandsJson(bs: List<Band>) = JSONArray().apply { bs.forEach { put(bandJson(it)) } }

    fun readBands(a: JSONArray?): List<Band> {
        a ?: return emptyList()
        return (0 until a.length()).mapNotNull { i ->
            val o = a.optJSONObject(i) ?: return@mapNotNull null
            val t = o.optString("type", "bell")
            if (t !in Filters.TYPES) return@mapNotNull null
            Band(t, o.optDouble("freq", 1000.0), o.optDouble("gain", 0.0),
                o.optDouble("q", 0.707), o.optBoolean("on", true))
        }.sortedBy { it.freq }
    }

    private fun readPresets(o: JSONObject): LinkedHashMap<String, List<Band>> {
        val ps = o.optJSONObject("presets") ?: return linkedMapOf()
        val drafts = o.optJSONObject("drafts")
        val order = o.optJSONArray("order")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
        val names = order.filter { ps.has(it) } + ps.keys().asSequence().filter { it !in order }
        val out = LinkedHashMap<String, List<Band>>()
        for (n in names) {
            val p = drafts?.optJSONObject(n) ?: ps.optJSONObject(n) ?: continue
            out[n] = readBands(p.optJSONArray("bands"))
        }
        return out
    }

    private fun toJson(s: State) = JSONObject().apply {
        put("enabled", s.enabled); put("autoPreamp", s.autoPreamp); put("perSession", s.perSession)
        put("selected", s.selected)
        put("order", JSONArray(s.presets.keys.toList()))
        put("presets", JSONObject().apply {
            for ((n, b) in s.presets) put(n, JSONObject().put("bands", bandsJson(b)))
        })
        put("devices", JSONArray().apply {
            for (d in s.devices.values) put(JSONObject().apply {
                put("key", d.key); put("name", d.name); put("kind", d.kind)
                put("enabled", d.enabled); put("preset", d.preset); put("autoeqOn", d.autoeqOn)
                d.autoeq?.let {
                    put("autoeq", JSONObject().put("name", it.name).put("folder", it.folder)
                        .put("bands", bandsJson(it.bands)))
                }
            })
        })
    }

    private fun fromJson(o: JSONObject): State {
        val presets = readPresets(o).ifEmpty { linkedMapOf("Flat" to emptyList()) }
        val devs = o.optJSONArray("devices")
        val devices = (0 until (devs?.length() ?: 0)).associate { i ->
            val d = devs!!.getJSONObject(i)
            val ae = d.optJSONObject("autoeq")?.let {
                Correction(it.optString("name"), it.optString("folder"), readBands(it.optJSONArray("bands")))
            }
            d.getString("key") to Headphone(d.getString("key"), d.optString("name"), d.optString("kind"),
                d.optBoolean("enabled", true), d.optString("preset", "Flat"), ae, d.optBoolean("autoeqOn"))
        }
        val sel = o.optString("selected")
        return State(o.optBoolean("enabled", true), o.optBoolean("autoPreamp", true),
            o.optBoolean("perSession", false), presets,
            if (sel in presets) sel else presets.keys.first(), devices)
    }
}
