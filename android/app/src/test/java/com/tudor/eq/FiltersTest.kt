package com.tudor.eq

import org.junit.Assert.assertEquals
import org.junit.Test

/** Vectors from the PC app's apo.response_db / auto_preamp: a preset must sound the same on both. */
class FiltersTest {
    val bands = listOf(Band("lowshelf", 105.0, 5.3, 0.7), Band("bell", 3839.0, -9.6, 0.4), Band("highshelf", 9000.0, -2.0, 0.7), Band("lowcut", 30.0, 0.0, 0.707), Band("notch", 6000.0, 0.0, 4.0), Band("highcut", 16000.0, 0.0, 0.707))
    val expect = mapOf(20.0 to -2.54076905444033, 63.0 to 4.403552372200904, 100.0 to 2.8128404153199584, 440.0 to -0.8101134074834306, 1000.0 to -3.199335863816753, 3839.0 to -9.91705393552168, 6100.0 to -25.06674110941845, 12000.0 to -5.398657201439641, 19000.0 to -12.236764891868386)

    @Test fun responseMatchesPc() {
        for ((f, db) in expect) assertEquals("at $f Hz", db, Filters.responseDb(bands, f), 1e-6)
    }

    @Test fun preampMatchesPc() = assertEquals(-4.5, round1(Filters.autoPreamp(bands)), 1e-9)

    @Test fun bandGridCoversAudibleRange() {
        assertEquals(64, Filters.cutoffs.size)
        assertEquals(20000f, Filters.cutoffs.last(), 1f)
        for (i in 1 until Filters.BANDS) assert(Filters.cutoffs[i] > Filters.cutoffs[i - 1])
        val g = Filters.sample(bands)
        assert(g.all { it >= Filters.FLOOR_DB })
    }

    @Test fun autoEqParse() {
        val t = "Preamp: -6.2 dB\nFilter 1: ON LSC Fc 105 Hz Gain 5.3 dB Q 0.70\nFilter 2: ON PK Fc 3839 Hz Gain -9.6 dB Q 0.40\n"
        assertEquals(listOf(Band("lowshelf", 105.0, 5.3, 0.7), Band("bell", 3839.0, -9.6, 0.4)), AutoEq.parse(t))
    }
}
