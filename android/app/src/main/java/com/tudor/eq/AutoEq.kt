package com.tudor.eq

import android.content.Context
import org.json.JSONArray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Headphone correction from AutoEQ (github.com/jaakkopasanen/AutoEq), as in the
 * PC app's autoeq.py. The index ships in the APK (assets/autoeq.json), so search
 * is offline; a headphone's ParametricEQ.txt is downloaded once and cached.
 */
object AutoEq {
    private const val RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
    private val CODES = mapOf("PK" to "bell", "LSC" to "lowshelf", "HSC" to "highshelf",
        "LS" to "lowshelf", "HS" to "highshelf")

    data class Entry(val name: String, val source: String, val folder: String)

    private var index: List<Entry>? = null

    fun search(ctx: Context, query: String, limit: Int = 40): List<Entry> {
        val all = index ?: JSONArray(ctx.assets.open("autoeq.json").bufferedReader().readText()).let { a ->
            (0 until a.length()).map { val e = a.getJSONArray(it); Entry(e.getString(0), e.getString(1), e.getString(2)) }
        }.also { index = it }
        val words = query.lowercase().split(" ").filter { it.isNotBlank() }
        if (words.isEmpty()) return emptyList()
        return all.asSequence().filter { e -> words.all { it in e.name.lowercase() } }.take(limit).toList()
    }

    fun parse(text: String): List<Band> {
        val re = Regex("""Filter\s*\d+:\s*ON\s+(\w+)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+(-?[\d.]+)\s*dB\s+Q\s+([\d.]+)""")
        return re.findAll(text).mapNotNull { m ->
            val t = CODES[m.groupValues[1].uppercase()] ?: return@mapNotNull null
            Band(t, m.groupValues[2].toDouble(), m.groupValues[3].toDouble(), m.groupValues[4].toDouble())
        }.toList()
    }

    /** Blocking; call off the main thread. */
    fun load(ctx: Context, e: Entry): Correction {
        val name = e.folder.trimEnd('/').substringAfterLast('/')
        val cache = File(ctx.filesDir, "autoeq/" + e.folder.replace(Regex("[^\\w.-]+"), "_") + ".txt")
        val text = if (cache.exists()) cache.readText() else {
            val path = "${e.folder}/$name ParametricEQ.txt".split("/")
                .joinToString("/") { URLEncoder.encode(it, "UTF-8").replace("+", "%20") }
            val c = URL(RAW + path).openConnection() as HttpURLConnection
            c.connectTimeout = 15000; c.readTimeout = 15000
            c.setRequestProperty("User-Agent", "eq-app")
            try {
                if (c.responseCode != 200) throw RuntimeException("AutoEQ: HTTP ${c.responseCode}")
                c.inputStream.bufferedReader().readText()
            } finally {
                c.disconnect()
            }.also { cache.parentFile?.mkdirs(); cache.writeText(it) }
        }
        val bands = parse(text)
        if (bands.isEmpty()) throw RuntimeException("AutoEQ: no filters in the file")
        return Correction(e.name, e.folder, bands)
    }
}
