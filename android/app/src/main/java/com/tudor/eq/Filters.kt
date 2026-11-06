package com.tudor.eq

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * The curve maths, ported from the PC app (apo.py / web/app.js): RBJ biquads,
 * the same formulas Equalizer APO runs, so a preset sounds the same on both.
 *
 * Android has no parametric EQ we can reach from an app, only
 * DynamicsProcessing's band EQ (a gain per frequency band). So the parametric
 * curve is drawn here and then sampled into [BANDS] log-spaced bands.
 */
object Filters {
    const val RATE = 48000.0
    const val F_MIN = 20.0
    const val F_MAX = 20000.0
    const val BANDS = 64
    const val FLOOR_DB = -30f       // cut filters fall to -inf; DP bands stop here

    val TYPES = listOf("bell", "lowshelf", "highshelf", "lowcut", "highcut", "notch")
    val LABEL = mapOf("bell" to "Bell", "lowshelf" to "Low shelf", "highshelf" to "High shelf",
        "lowcut" to "Low cut", "highcut" to "High cut", "notch" to "Notch")
    fun hasGain(type: String) = type == "bell" || type == "lowshelf" || type == "highshelf"

    /** b0 b1 b2 a1 a2, a0 = 1. */
    fun coeffs(b: Band): DoubleArray {
        val a = 10.0.pow(b.gain / 40.0)
        val w = 2 * PI * b.freq / RATE
        val cw = cos(w)
        val al = sin(w) / (2 * max(b.q, 0.05))
        val c = when (b.type) {
            "bell" -> doubleArrayOf(1 + al * a, -2 * cw, 1 - al * a, 1 + al / a, -2 * cw, 1 - al / a)
            "lowshelf", "highshelf" -> {
                val s = if (b.type == "lowshelf") 1 else -1
                val sq = 2 * sqrt(a) * al
                doubleArrayOf(
                    a * ((a + 1) - s * (a - 1) * cw + sq), 2 * s * a * ((a - 1) - s * (a + 1) * cw),
                    a * ((a + 1) - s * (a - 1) * cw - sq), (a + 1) + s * (a - 1) * cw + sq,
                    -2 * s * ((a - 1) + s * (a + 1) * cw), (a + 1) + s * (a - 1) * cw - sq)
            }
            "lowcut" -> doubleArrayOf((1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + al, -2 * cw, 1 - al)
            "highcut" -> doubleArrayOf((1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + al, -2 * cw, 1 - al)
            "notch" -> doubleArrayOf(1.0, -2 * cw, 1.0, 1 + al, -2 * cw, 1 - al)
            else -> doubleArrayOf(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        }
        val a0 = c[3]
        return doubleArrayOf(c[0] / a0, c[1] / a0, c[2] / a0, c[4] / a0, c[5] / a0)
    }

    fun magDb(k: DoubleArray, f: Double): Double {
        val w = 2 * PI * f / RATE
        val c1 = cos(w); val s1 = -sin(w); val c2 = cos(2 * w); val s2 = -sin(2 * w)
        val nr = k[0] + k[1] * c1 + k[2] * c2; val ni = k[1] * s1 + k[2] * s2
        val dr = 1 + k[3] * c1 + k[4] * c2; val di = k[3] * s1 + k[4] * s2
        return 10 * log10(max((nr * nr + ni * ni) / (dr * dr + di * di), 1e-18))
    }

    /** Summed response of the bands that are on, in dB. */
    fun responseDb(bands: List<Band>, f: Double): Double {
        var t = 0.0
        for (b in bands) if (b.on) t += magDb(coeffs(b), f)
        return t
    }

    /** Frequency at x in 0..1 across the graph / the band grid. */
    fun freqAt(x: Double) = F_MIN * (F_MAX / F_MIN).pow(x)

    /** Preamp that keeps the loudest point of the curve at 0 dB (from apo.py). */
    fun autoPreamp(bands: List<Band>): Double {
        val ks = bands.filter { it.on }.map { coeffs(it) }
        var peak = 0.0
        for (i in 0 until 240) {
            val f = freqAt(i / 239.0)
            peak = max(peak, ks.sumOf { magDb(it, f) })
        }
        return -peak
    }

    /** Upper edge of each DynamicsProcessing band. */
    val cutoffs = FloatArray(BANDS) { i -> freqAt((i + 1.0) / BANDS).toFloat() }

    /** Gain of each band: the curve at the band's geometric centre. */
    fun sample(bands: List<Band>): FloatArray {
        val ks = bands.filter { it.on }.map { coeffs(it) }
        return FloatArray(BANDS) { i ->
            val f = freqAt((i + 0.5) / BANDS)
            max(ks.sumOf { magDb(it, f) }.toFloat(), FLOOR_DB)
        }
    }
}
