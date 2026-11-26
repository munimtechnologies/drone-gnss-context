"""Unit tests for gnss_context.py (standard library only; no network).

    python -m unittest -v test_gnss_context

By MV2 of Munim, Inc. (mv2@munimtech.com); made with AI agents. Apache-2.0.
"""

import calendar
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gnss_context as gc  # noqa: E402
import test_ulog_flight as tu  # noqa: E402  (synthetic ULog builders)
import ulog_flight as uf  # noqa: E402

I = gc.INTERVAL_S
DAY = gc.DAY_S


def utc(y, mo, d, h=0, mi=0, s=0):
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))


# GFZ's real answer for 2024-05-10 (start of the Kp 9 storm), first eight intervals.
SAMPLE = {"Kp": [2.667, 2.667, 2.333, 2.0, 3.667, 7.667, 8.667, 8.667],
          "datetime": ["2024-05-10T%02d:00:00Z" % h for h in range(0, 24, 3)],
          "meta": {"license": "CC BY 4.0", "source": "GFZ Potsdam"},
          "status": ["def"] * 8}


class TestTime(unittest.TestCase):
    def test_parse_time_forms(self):
        want = utc(2024, 5, 10, 20, 15)
        self.assertEqual(gc.parse_time("2024-05-10T20:15:00Z"), want)
        self.assertEqual(gc.parse_time("2024-05-10T20:15Z"), want)
        self.assertEqual(gc.parse_time("2024-05-10T22:15:00+02:00"), want)
        self.assertEqual(gc.parse_time("2024-05-10 20:15"), want)
        self.assertEqual(gc.parse_time(str(want)), want)
        self.assertEqual(gc.parse_time("2024-05-10"), utc(2024, 5, 10))

    def test_parse_time_bad(self):
        with self.assertRaises(ValueError):
            gc.parse_time("not-a-time")

    def test_iso(self):
        self.assertEqual(gc.iso(utc(2024, 5, 10, 18)), "2024-05-10T18:00:00Z")
        self.assertEqual(gc.iso_day(utc(2024, 5, 10, 23, 59, 59)), "2024-05-10")


class TestPlace(unittest.TestCase):
    def test_mag_lat_pole_and_equator(self):
        self.assertAlmostEqual(gc.mag_lat(80.7, -72.7), 90.0, places=4)    # asin is steep next to 1
        self.assertAlmostEqual(gc.mag_lat(-80.7, 107.3), -90.0, places=4)
        self.assertAlmostEqual(gc.mag_lat(9.3, 107.3), 0.0, places=6)   # on the dipole equator
        self.assertAlmostEqual(gc.mag_lat(0.0, -72.7), 9.3, places=6)   # pole's meridian, geographic equator

    def test_mag_band(self):
        self.assertEqual(gc.mag_band(0.0), "low")
        self.assertEqual(gc.mag_band(19.99), "low")
        self.assertEqual(gc.mag_band(-20.0), "mid")
        self.assertEqual(gc.mag_band(54.9), "mid")
        self.assertEqual(gc.mag_band(55.0), "high")
        self.assertEqual(gc.mag_band(-69.9), "high")
        self.assertEqual(gc.mag_band(70.0), "polar")

    def test_local_solar_hour(self):
        t = utc(2024, 5, 10, 20)
        self.assertEqual(gc.local_solar_hour(t, 0.0), 20.0)
        self.assertEqual(gc.local_solar_hour(t, -75.0), 15.0)
        self.assertEqual(gc.local_solar_hour(t, 90.0), 2.0)

    def test_time_class(self):
        self.assertEqual(gc.time_class(19.5), "night")
        self.assertEqual(gc.time_class(0.5), "night")
        self.assertEqual(gc.time_class(1.0), "late")
        self.assertEqual(gc.time_class(8.0), "day")
        self.assertEqual(gc.time_class(16.99), "day")
        self.assertEqual(gc.time_class(17.0), "dusk")
        self.assertEqual(gc.time_class(19.49), "dusk")

    def test_equinox_season(self):
        self.assertTrue(gc.equinox_season(utc(2024, 3, 20)))
        self.assertTrue(gc.equinox_season(utc(2024, 11, 30)))
        self.assertFalse(gc.equinox_season(utc(2024, 6, 15)))
        self.assertFalse(gc.equinox_season(utc(2024, 1, 31)))


class TestKp(unittest.TestCase):
    def test_kp_label(self):
        self.assertEqual(gc.kp_label(4.667), "5-")
        self.assertEqual(gc.kp_label(5.0), "5o")
        self.assertEqual(gc.kp_label(5.333), "5+")
        self.assertEqual(gc.kp_label(0.0), "0o")
        self.assertEqual(gc.kp_label(0.333), "0+")
        self.assertEqual(gc.kp_label(8.667), "9-")
        self.assertEqual(gc.kp_label(9.0), "9o")
        self.assertIsNone(gc.kp_label(None))

    def test_g_scale(self):
        self.assertEqual(gc.g_scale(4.333), 0)
        self.assertEqual(gc.g_scale(4.667), 1)
        self.assertEqual(gc.g_scale(5.333), 1)
        self.assertEqual(gc.g_scale(5.667), 2)
        self.assertEqual(gc.g_scale(6.333), 2)
        self.assertEqual(gc.g_scale(6.667), 3)
        self.assertEqual(gc.g_scale(7.333), 3)
        self.assertEqual(gc.g_scale(7.667), 4)
        self.assertEqual(gc.g_scale(8.667), 4)
        self.assertEqual(gc.g_scale(9.0), 5)
        self.assertIsNone(gc.g_scale(None))

    def test_kp_url(self):
        u = gc.kp_url(utc(2024, 5, 10), utc(2024, 5, 10, 23, 59, 59))
        self.assertTrue(u.startswith(gc.GFZ_URL + "?"))
        self.assertIn("start=2024-05-10T00:00:00Z", u)
        self.assertIn("end=2024-05-10T23:59:59Z", u)
        self.assertIn("index=Kp", u)

    def test_parse_kp_json(self):
        s = gc.parse_kp_json(SAMPLE)
        self.assertEqual(len(s), 8)
        self.assertEqual(s[utc(2024, 5, 10, 18)], (8.667, "def"))
        odd = gc.parse_kp_json({"datetime": ["2024-05-10T00:00:00Z", "2024-05-10T03:00:00Z",
                                             "2024-05-10T06:00:00Z", "2024-05-10T09:00:00Z"],
                                "Kp": [1.0, -1, None, 2.0], "status": ["def", "now"]})
        self.assertEqual(odd, {utc(2024, 5, 10): (1.0, "def"), utc(2024, 5, 10, 9): (2.0, None)})
        self.assertEqual(gc.parse_kp_json({}), {})

    def test_fetch_kp_with_fake_opener(self):
        seen = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(SAMPLE).encode("utf-8")

        def opener(req, timeout=None):
            seen["url"], seen["ua"] = req.full_url, req.get_header("User-agent")
            return Resp()

        s = gc.fetch_kp(utc(2024, 5, 10, 20, 15), opener=opener)
        self.assertIn("start=2024-05-09T21:00:00Z", seen["url"])
        self.assertIn("end=2024-05-10T20:59:59Z", seen["url"])
        self.assertTrue(seen["ua"].startswith("drone-gnss-context/"))
        self.assertEqual(len(s), 8)

    def test_kp_context_storm(self):
        k = gc.kp_context(gc.parse_kp_json(SAMPLE), utc(2024, 5, 10, 20, 15))
        self.assertEqual(k["interval_start"], "2024-05-10T18:00:00Z")
        self.assertEqual(k["kp"], 8.667)
        self.assertEqual(k["kp_label"], "9-")
        self.assertEqual(k["kp_status"], "def")
        self.assertEqual(k["g_scale"], 4)
        self.assertEqual(k["max_kp_24h"], 8.667)
        self.assertEqual(k["g_scale_max_24h"], 4)

    def test_kp_context_empty(self):
        for series in (None, {}):
            k = gc.kp_context(series, utc(2024, 5, 10, 20, 15))
            self.assertIsNone(k["kp"])
            self.assertIsNone(k["g_scale"])
            self.assertIsNone(k["max_kp_24h"])


class TestGpsjam(unittest.TestCase):
    def test_link(self):
        t = utc(2024, 6, 15, 12)
        self.assertEqual(gc.gpsjam_link(t, 45.0, 5.0, now=t + 3 * DAY),
                         "https://gpsjam.org/?lat=45.00&lon=5.00&z=6&date=2024-06-15")
        self.assertIsNone(gc.gpsjam_link(t, 45.0, 5.0, now=t + 60))          # that day's map is not out yet
        self.assertIsNone(gc.gpsjam_link(utc(2021, 6, 1), 45.0, 5.0, now=t))  # before GPSJam's first day


class TestContext(unittest.TestCase):
    def test_storm_flight(self):
        t = utc(2024, 5, 10, 20, 15)
        c = gc.context(t, 52.1, 5.1, gc.parse_kp_json(SAMPLE), now=t + 3 * DAY)
        self.assertEqual(c["time_utc"], "2024-05-10T20:15:00Z")
        self.assertEqual(c["kp"]["g_scale"], 4)
        self.assertIn("NOAA G4", c["notes"][0])
        self.assertIn("May 2024", c["notes"][0])
        self.assertIn("gpsjam.org/?lat=52.10&lon=5.10&z=6&date=2024-05-10", c["notes"][-1])
        self.assertNotIn("receiver", c)

    def test_storm_in_previous_day_only(self):
        t = utc(2024, 6, 15, 12)
        s = t // I * I
        c = gc.context(t, 45.0, 5.0, {s: (2.0, "now"), s - 3 * I: (7.0, "now")}, now=t + 3 * DAY)
        self.assertEqual(c["kp"]["g_scale"], 0)
        self.assertEqual(c["kp"]["g_scale_max_24h"], 3)
        self.assertIn("24 hours before", c["notes"][0])
        self.assertIn("max Kp 7o, NOAA G3", c["notes"][0])

    def test_low_latitude_post_sunset_equinox(self):
        t = utc(2024, 3, 20, 0, 20)
        c = gc.context(t, 0.0, -50.0, {t // I * I: (2.0, "def")}, now=t + 3 * DAY)
        self.assertEqual(c["mag_band"], "low")
        self.assertEqual(c["time_class"], "night")
        self.assertEqual(c["local_solar_time"], "21:00")
        self.assertTrue(c["equinox_season"])
        self.assertTrue(any("plasma bubbles" in n for n in c["notes"]))
        self.assertFalse(any("red flag" in n for n in c["notes"]))

    def test_quiet_mid_latitude_day(self):
        t = utc(2024, 6, 15, 12)
        c = gc.context(t, 45.0, 5.0, {t // I * I: (1.0, "def")}, now=t + 3 * DAY)
        self.assertEqual(c["mag_band"], "mid")
        self.assertEqual(c["time_class"], "day")
        self.assertEqual(c["kp"]["kp_label"], "1o")
        self.assertTrue(c["notes"][0].startswith("No space-weather red flag"))
        self.assertEqual(len(c["notes"]), 2)

    def test_auroral_storm(self):
        t = utc(2024, 6, 15, 12)
        c = gc.context(t, 65.0, -147.0, {t // I * I: (6.0, "def")}, now=t + 3 * DAY)
        self.assertEqual(c["mag_band"], "high")
        self.assertIn("NOAA G2", c["notes"][0])
        self.assertTrue(any(n.startswith("Auroral") for n in c["notes"]))

    def test_unknown_kp(self):
        t = utc(2024, 6, 15, 12)
        c = gc.context(t, 45.0, 5.0, None, now=t + 3 * DAY)
        self.assertIn("Kp unavailable", c["notes"][0])

    def test_bad_position(self):
        with self.assertRaises(ValueError):
            gc.context(utc(2024, 6, 15), 95.0, 0.0)
        with self.assertRaises(ValueError):
            gc.context(utc(2024, 6, 15), 0.0, 181.0)

    def test_render(self):
        t = utc(2024, 5, 10, 20, 15)
        text = gc.render(gc.context(t, 52.1, 5.1, gc.parse_kp_json(SAMPLE), now=t + 3 * DAY))
        self.assertIn("magnetic latitude", text)
        self.assertIn("Kp 9- (G4, def)", text)
        self.assertNotIn("receiver log", text)


class TestReceiver(unittest.TestCase):
    """Context with a flight log's own GNSS reports (the synthetic log from test_ulog_flight)."""

    def setUp(self):
        self.s = uf.read_flight(tu.new_log())[0]
        self.t = tu.T0 + 1                                   # the log's first good fix, 2024-05-10T20:15:01Z

    def test_quiet_sky_with_interference_signs(self):
        t = self.t
        c = gc.context(t, 52.1, 5.1, {t // I * I: (1.0, "def")}, now=t + 3 * DAY, receiver=self.s)
        n = c["notes"]
        self.assertTrue(n[0].startswith("No space-weather red flag"))
        self.assertTrue(any("flagged spoofing in 2 of 5 samples" in x and "(1 with multiple" in x for x in n))
        self.assertTrue(any("1 samples at warning level and 2 at critical level" in x for x in n))
        self.assertTrue(any("jumped 1 time(s)" in x for x in n))
        self.assertTrue(any("largest 100.0 s" in x for x in n))
        self.assertTrue(any("3D fix was lost 1 time(s)" in x for x in n))
        self.assertTrue(n[-2].startswith("A quiet sky together with"))
        self.assertIn("gpsjam.org/", n[-1])
        self.assertEqual(c["receiver"]["topic"], "sensor_gps[0]")
        self.assertTrue(gc.log_suspicious(self.s))

    def test_storm_means_no_local_verdict(self):
        t = self.t
        c = gc.context(t, 52.1, 5.1, gc.parse_kp_json(SAMPLE), now=t + 3 * DAY, receiver=self.s)
        self.assertIn("NOAA G4", c["notes"][0])
        self.assertFalse(any(x.startswith("A quiet sky") for x in c["notes"]))

    def test_unknown_kp_means_no_local_verdict(self):
        c = gc.context(self.t, 52.1, 5.1, None, now=self.t + 3 * DAY, receiver=self.s)
        self.assertFalse(any(x.startswith("A quiet sky") for x in c["notes"]))

    def test_jamming_warning_alone_is_weak(self):
        def gps_row(i):
            v = {"timestamp": 1000000 * (i + 1), "time_utc_usec": tu.U0 + 1000000 * i, "fix_type": 3,
                 "latitude_deg": 52.1, "longitude_deg": 5.1, "eph": 2.0, "satellites_used": 10,
                 "spoofing_state": 1, "jamming_state": 2, "jamming_indicator": 30}
            return tuple(v.get(f) for f in uf.GPS_FIELDS)

        s = uf.summarize([gps_row(i) for i in range(3)])
        self.assertEqual((s["jamming"]["warning"], s["jamming"]["critical"]), (3, 0))
        self.assertEqual((s["teleports"], s["utc_jumps"], s["fix_losses"]), (0, 0, 0))
        self.assertFalse(gc.log_suspicious(s))
        self.assertFalse(uf.suspicious(s))
        t = tu.T0
        c = gc.context(t, 52.1, 5.1, {t // I * I: (1.0, "def")}, now=t + 3 * DAY, receiver=s)
        self.assertTrue(any("3 samples at warning level and 0 at critical level" in x and "weak evidence" in x
                            for x in c["notes"]))
        self.assertFalse(any(x.startswith("A quiet sky") for x in c["notes"]))

    def test_receiver_without_states(self):
        s = uf.read_flight(tu.old_log())[0]
        t = utc(2024, 6, 15, 12)
        c = gc.context(t, -33.6, 151.2, {t // I * I: (1.0, "def")}, now=t + 3 * DAY, receiver=s)
        self.assertTrue(any(x.startswith("This receiver did not report spoofing or jamming states") for x in c["notes"]))
        self.assertFalse(any(x.startswith("A quiet sky") for x in c["notes"]))
        self.assertFalse(gc.log_suspicious(s))

    def test_render_receiver_line(self):
        t = self.t
        text = gc.render(gc.context(t, 52.1, 5.1, None, now=t + 3 * DAY, receiver=self.s))
        self.assertIn("receiver log (sensor_gps[0], 5 GNSS samples): spoofing flagged 2/5, jamming warning 1 "
                      "critical 2, position jumps 1, clock jumps 1, fix losses 1", text)


class TestMain(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gc.main(argv)
        return code, out.getvalue()

    def test_json_offline(self):
        code, out = self.run_main(["--time", "2024-06-15T12:00Z", "--lat", "45", "--lon", "5", "--offline", "--json"])
        self.assertEqual(code, 0)
        c = json.loads(out)
        self.assertEqual(c["mag_band"], "mid")
        self.assertIsNone(c["kp"]["kp"])
        self.assertEqual(c["version"], gc.__version__)

    def test_negative_longitude_and_text(self):
        code, out = self.run_main(["--time", "2024-06-15T12:00Z", "--lat", "-33.9", "--lon", "-70.6", "--offline"])
        self.assertEqual(code, 0)
        self.assertIn("Flight 2024-06-15T12:00:00Z", out)

    def test_bad_input(self):
        self.assertEqual(self.run_main(["--time", "2024-06-15T12:00Z", "--lat", "95", "--lon", "5", "--offline"])[0], 2)
        self.assertEqual(self.run_main(["--time", "not-a-time", "--lat", "45", "--lon", "5", "--offline"])[0], 2)
        self.assertEqual(self.run_main(["--lat", "45", "--lon", "5", "--offline"])[0], 2)      # no time

    def write(self, folder, name, data):
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_ulog(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "flight.ulg", tu.new_log())
            code, out = self.run_main(["--ulog", path, "--offline", "--json"])
        self.assertEqual(code, 0)
        c = json.loads(out)
        self.assertEqual(c["time_utc"], "2024-05-10T20:15:01Z")
        self.assertEqual((c["lat"], c["lon"]), (52.1, 5.1))
        self.assertEqual(c["receiver"]["spoofing"]["indicated"], 2)
        self.assertEqual(c["receiver"]["first_fix"]["quality"], "good")

    def test_ulog_without_utc_needs_time(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "old.ulg", tu.old_log())
            self.assertEqual(self.run_main(["--ulog", path, "--offline"])[0], 2)
            code, out = self.run_main(["--ulog", path, "--time", "2024-06-15T12:00Z", "--offline", "--json"])
        self.assertEqual(code, 0)
        c = json.loads(out)
        self.assertAlmostEqual(c["lat"], -33.6, places=6)
        self.assertEqual(c["time_utc"], "2024-06-15T12:00:00Z")

    def test_ulog_bad_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "notes.txt", b"hello world 12345678")
            self.assertEqual(self.run_main(["--ulog", path, "--offline"])[0], 2)
            self.assertEqual(self.run_main(["--ulog", os.path.join(d, "missing.ulg"), "--offline"])[0], 2)


if __name__ == "__main__":
    unittest.main()
