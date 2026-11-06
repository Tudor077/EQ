package com.tudor.eq

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.pow

const val DB_RANGE = 15.0

private val GRID_F = listOf(50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0)
private fun fLabel(f: Double) = if (f >= 1000) "${(f / 1000).toInt()}k" else "${f.toInt()}"

fun xOf(f: Double) = ln(f / Filters.F_MIN) / ln(Filters.F_MAX / Filters.F_MIN)
fun fOf(x: Double) = Filters.freqAt(x.coerceIn(0.0, 1.0))

/**
 * The curve: drag a point to move a band (sideways = frequency, up/down =
 * gain), tap one to pick it, double-tap empty space to add a bell there.
 */
@Composable
fun Graph(
    bands: List<Band>,
    correction: List<Band>,
    selected: Int,
    onSelect: (Int) -> Unit,
    onMove: (Int, Band) -> Unit,
    onAdd: (Band) -> Unit,
) {
    val tm = rememberTextMeasurer()
    val cur by rememberUpdatedState(bands)
    val select by rememberUpdatedState(onSelect)
    val move by rememberUpdatedState(onMove)
    val add by rememberUpdatedState(onAdd)
    val label = TextStyle(color = Ui.MUT, fontSize = 9.sp, fontFamily = Ui.MONO)
    val pad = 6f

    fun pointOf(b: Band, w: Float, h: Float): Offset {
        val y = if (Filters.hasGain(b.type)) b.gain else 0.0
        return Offset((xOf(b.freq) * w).toFloat(), (h / 2 - y / DB_RANGE * (h / 2 - pad)).toFloat())
    }

    fun nearest(p: Offset, w: Float, h: Float, reach: Float): Int {
        var best = -1
        var bestD = reach
        cur.forEachIndexed { i, b ->
            val q = pointOf(b, w, h)
            val d = hypot(q.x - p.x, q.y - p.y)
            if (d < bestD) { best = i; bestD = d }
        }
        return best
    }

    Canvas(
        Modifier
            .fillMaxWidth()
            .height(240.dp)
            .pointerInput(Unit) {
                val reach = 28.dp.toPx()
                detectTapGestures(
                    onTap = { select(nearest(it, size.width.toFloat(), size.height.toFloat(), reach)) },
                    onDoubleTap = {
                        val w = size.width.toFloat(); val h = size.height.toFloat()
                        if (nearest(it, w, h, reach) < 0) {
                            val g = (h / 2 - it.y) / (h / 2 - pad) * DB_RANGE
                            add(Band("bell", round(fOf(it.x / w.toDouble())), round1(g), 1.0))
                        }
                    },
                )
            }
            .pointerInput(Unit) {
                val reach = 36.dp.toPx()
                var idx = -1
                var pos = Offset.Zero
                detectDragGestures(
                    onDragStart = {
                        idx = nearest(it, size.width.toFloat(), size.height.toFloat(), reach)
                        pos = it
                        if (idx >= 0) select(idx)
                    },
                    onDragEnd = { idx = -1 },
                    onDragCancel = { idx = -1 },
                ) { ch, d ->
                    if (idx < 0 || idx >= cur.size) return@detectDragGestures
                    ch.consume()
                    pos += d
                    val w = size.width.toFloat(); val h = size.height.toFloat()
                    val b = cur[idx]
                    val f = round(fOf(pos.x / w.toDouble())).coerceIn(Filters.F_MIN, Filters.F_MAX)
                    val g = if (Filters.hasGain(b.type))
                        round1(((h / 2 - pos.y) / (h / 2 - pad) * DB_RANGE).coerceIn(-DB_RANGE, DB_RANGE)) else b.gain
                    move(idx, b.copy(freq = f, gain = g))
                }
            }
    ) {
        val w = size.width; val h = size.height
        val mid = h / 2
        val yOf = { db: Double -> (mid - db / DB_RANGE * (mid - pad)).toFloat() }

        for (f in GRID_F) {
            val x = (xOf(f) * w).toFloat()
            drawLine(Ui.LINE, Offset(x, 0f), Offset(x, h), 1f)
            val t = tm.measure(fLabel(f), label)
            drawText(t, topLeft = Offset(x + 3, h - t.size.height - 2))
        }
        for (db in listOf(-12, -6, 6, 12)) {
            drawLine(Ui.LINE, Offset(0f, yOf(db.toDouble())), Offset(w, yOf(db.toDouble())), 1f)
            drawText(tm, (if (db > 0) "+" else "") + db, Offset(3f, yOf(db.toDouble()) + 2), label)
        }
        drawLine(Ui.MUT, Offset(0f, mid), Offset(w, mid), 1f)

        fun curve(bs: List<Band>): Path {
            val ks = bs.filter { it.on }.map { Filters.coeffs(it) }
            val p = Path()
            val n = 200
            for (i in 0..n) {
                val x = i / n.toDouble()
                val db = ks.sumOf { Filters.magDb(it, Filters.freqAt(x)) }.coerceIn(-DB_RANGE - 3, DB_RANGE + 3)
                if (i == 0) p.moveTo(0f, yOf(db)) else p.lineTo((x * w).toFloat(), yOf(db))
            }
            return p
        }

        if (correction.isNotEmpty()) {
            drawPath(curve(correction), Ui.GREY, style = Stroke(1.5f,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
        }
        drawPath(curve(correction + bands), Ui.WHITE, style = Stroke(5f))

        bands.forEachIndexed { i, b ->
            val p = pointOf(b, w, h)
            val sel = i == selected
            val r = if (sel) 13.dp.toPx() else 10.dp.toPx()
            drawCircle(if (sel) Ui.RED else if (b.on) Ui.WHITE else Ui.MUT, r, p)
            val t = tm.measure("${i + 1}", TextStyle(color = if (sel) Ui.WHITE else Ui.BLACK, fontSize = 11.sp,
                fontFamily = Ui.MONO))
            drawText(t, topLeft = Offset(p.x - t.size.width / 2f, p.y - t.size.height / 2f))
        }
    }
}

fun round(f: Double) = when {
    f < 100 -> Math.round(f).toDouble()
    f < 1000 -> Math.round(f / 5) * 5.0
    else -> Math.round(f / 50) * 50.0
}

fun round1(x: Double) = Math.round(x * 10) / 10.0

fun round2(x: Double) = Math.round(x * 100) / 100.0

fun logSlider(v: Double, lo: Double, hi: Double) = (ln(v / lo) / ln(hi / lo)).toFloat()
fun fromLogSlider(p: Float, lo: Double, hi: Double) = lo * (hi / lo).pow(p.toDouble())
