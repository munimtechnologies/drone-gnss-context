"""Unit tests for ulog_flight.py (standard library only; no network). Synthetic ULog files are built in memory;
every expected value was worked out by hand.

    python -m unittest -v test_ulog_flight

By MV2 of Munim, Inc. (mv2@munimtech.com); made with AI agents. Apache-2.0.
"""

import calendar
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ulog_flight as uf  # noqa: E402

HEADER = uf.MAGIC + b"\x01" + struct.pack("<Q", 0)


def msg(t, payload):
    return struct.pack("<HB", len(payload), ord(t)) + payload


def fmt(s):
    return msg("F", s.encode())


def add(multi, msg_id, name):
    return msg("A", struct.pack("<BH", multi, msg_id) + name.encode())


def data(msg_id, payload):
    return msg("D", struct.pack("<H", msg_id) + payload)


T0 = calendar.timegm((2024, 5, 10, 20, 15, 0, 0, 0, 0))     # 2024-05-10T20:15:00Z
U0 = T0 * 1000000

NEW_FMT = ("sensor_gps:uint64_t timestamp;uint64_t time_utc_usec;double latitude_deg;double longitude_deg;"
           "float eph;uint8_t fix_type;uint8_t satellites_used;uint8_t spoofing_state;uint8_t jamming_state;"
           "int32_t jamming_indicator;uint8_t[4] _padding0;")
NEW_PACK = "<QQddfBBBBi"     # 44 bytes; the trailing 4-byte padding is left out, as PX4 may do

# (timestamp us, time_utc_usec, lat, lon, eph, fix_type, sats, spoofing_state, jamming_state, jamming_indicator)
SCENARIO = [
    (1000000, 0, 0.0, 0.0, 99.0, 1, 3, 1, 1, 10),                       # no fix, no UTC yet
    (2000000, U0, 52.1, 5.1, 30.0, 3, 5, 1, 1, 12),                     # first 3D fix, weak (eph 30 m, 5 sats)
    (3000000, U0 + 1000000, 52.1, 5.1, 2.5, 3, 9, 1, 2, 40),            # first good fix; jamming warning
    (4000000, U0 + 2000000, 52.1, 5.1, 2.5, 1, 9, 2, 3, 90),            # fix lost; spoofing indicated, jam critical
    (5000000, U0 + 103000000, 55.75, 37.6, 2.5, 3, 9, 3, 3, 95),        # 2,000+ km jump in 2 s; clock +100 s
]


def new_log(rows=SCENARIO, extra=b""):
    body = b"".join(data(1, struct.pack(NEW_PACK, *r)) for r in rows)
    return HEADER + fmt(NEW_FMT) + fmt("other:uint64_t timestamp;float x;") + add(0, 1, "sensor_gps") \
        + add(0, 2, "other") + data(2, struct.pack("<Qf", 1, 2.0)) + body + extra


OLD_FMT = ("vehicle_gps_position:uint64_t timestamp;int32_t lat;int32_t lon;float eph;uint8_t fix_type;"
           "uint8_t satellites_used;uint8_t[2] _padding0;")


def old_log():
    return (HEADER + fmt(OLD_FMT) + add(0, 7, "vehicle_gps_position")
            + data(7, struct.pack("<QiifBB", 1000000, -336000000, 1512000000, 1.5, 3, 12) + b"\0\0")
            + data(7, struct.pack("<QiifBB", 2000000, -336000000, 1512000000, 1.5, 3, 12)))


class TestReader(unittest.TestCase):
    def test_layout_and_resolve(self):
        name, fields = uf.parse_format(NEW_FMT)
        codes, names = uf.layout(name, {name: fields})
        self.assertEqual(codes, "QQddfBBBBi4x")
        self.assertEqual(struct.calcsize("<" + codes), 48)
        self.assertEqual(names[:4], ["timestamp", "time_utc_usec", "latitude_deg", "longitude_deg"])
        self.assertIsNone(uf.resolve(names, "lat"))     # 'latitude_deg' is not 'lat'

    def test_not_ulog(self):
        with self.assertRaises(uf.NotULog):
            uf.read_flight(b"hello world 12345678")

    def test_no_gnss_topic(self):
        s, info = uf.read_flight(HEADER + fmt("other:uint64_t timestamp;float x;") + add(0, 2, "other")
                                 + data(2, struct.pack("<Qf", 1, 2.0)))
        self.assertIsNone(s)
        self.assertFalse(info["truncated"])

    def test_truncated_log_still_reads(self):
        buf = new_log()[:-10]                       # the last data message is cut
        s, info = uf.read_flight(buf)
        self.assertTrue(info["truncated"])
        self.assertEqual(s["n_gps"], 4)
        self.assertEqual(s["teleports"], 0)


class TestNewStyleLog(unittest.TestCase):
    def setUp(self):
        self.s, self.info = uf.read_flight(new_log())

    def test_topic_and_counts(self):
        s = self.s
        self.assertEqual(s["topic"], "sensor_gps[0]")
        self.assertEqual(s["n_gps"], 5)
        self.assertEqual(s["n_fix"], 3)
        self.assertEqual(self.info["resyncs"], 0)

    def test_first_good_fix(self):
        f = self.s["first_fix"]
        self.assertEqual(f["quality"], "good")
        self.assertEqual(f["log_time_s"], 3.0)
        self.assertEqual((f["lat"], f["lon"]), (52.1, 5.1))
        self.assertEqual(f["eph"], 2.5)
        self.assertEqual(f["satellites_used"], 9)
        self.assertEqual(f["time_utc"], T0 + 1)
        self.assertEqual(f["time_iso"], "2024-05-10T20:15:01Z")

    def test_span(self):
        s = self.s
        self.assertEqual(s["utc_start"], "2024-05-10T20:14:59Z")    # log clock 1 s, offset U0 - 2 s
        self.assertEqual(s["utc_end"], "2024-05-10T20:15:03Z")
        self.assertEqual(s["duration_s"], 4.0)

    def test_receiver_reports(self):
        s = self.s
        self.assertEqual(s["spoofing"], {"counts": [0, 3, 1, 1], "reporting": 5, "indicated": 2, "multiple": 1})
        j = s["jamming"]
        self.assertEqual(j["counts"], [0, 2, 1, 2])
        self.assertEqual((j["reporting"], j["warning"], j["critical"]), (5, 1, 2))
        self.assertEqual(j["indicator_max"], 95)
        self.assertEqual(j["indicator_median"], 40)

    def test_jumps_and_losses(self):
        s = self.s
        self.assertEqual(s["teleports"], 1)
        self.assertGreater(s["max_jump_km"], 2000)
        self.assertLess(s["max_jump_km"], 2400)
        self.assertEqual(s["utc_jumps"], 1)
        self.assertEqual(s["max_utc_jump_s"], 100.0)
        self.assertEqual(s["fix_losses"], 1)
        self.assertEqual(s["max_eph"], 30.0)
        self.assertTrue(uf.suspicious(s))


class TestOldStyleLog(unittest.TestCase):
    def test_int_position_no_utc_no_states(self):
        s, _ = uf.read_flight(old_log())
        self.assertEqual(s["topic"], "vehicle_gps_position[0]")
        f = s["first_fix"]
        self.assertAlmostEqual(f["lat"], -33.6, places=6)
        self.assertAlmostEqual(f["lon"], 151.2, places=6)
        self.assertIsNone(f["time_utc"])
        self.assertIsNone(s["utc_start"])
        self.assertEqual(s["spoofing"]["reporting"], 0)
        self.assertIsNone(s["jamming"]["indicator_max"])
        self.assertEqual((s["teleports"], s["utc_jumps"], s["fix_losses"]), (0, 0, 0))
        self.assertFalse(uf.suspicious(s))


class TestSummarize(unittest.TestCase):
    def row(self, **kw):
        return tuple(kw.get(f) for f in uf.GPS_FIELDS)

    def test_weak_fix_only(self):
        s = uf.summarize([self.row(timestamp=1, fix_type=3, latitude_deg=10.0, longitude_deg=20.0, eph=50.0,
                                   satellites_used=4)])
        self.assertEqual(s["first_fix"]["quality"], "weak")
        self.assertEqual(s["n_fix"], 1)

    def test_bad_utc_ignored(self):
        s = uf.summarize([self.row(timestamp=1000000, time_utc_usec=5000000, fix_type=3, latitude_deg=10.0,
                                   longitude_deg=20.0)])       # receiver time in 1970: not set
        self.assertIsNone(s["first_fix"]["time_utc"])

    def test_empty(self):
        s = uf.summarize([])
        self.assertIsNone(s["first_fix"])
        self.assertIsNone(s["duration_s"])
        self.assertEqual(s["n_gps"], 0)

    def test_choose_topic_prefers_spoofing_reports(self):
        si = uf.GPS_FIELDS.index("spoofing_state")
        r0 = tuple(0 if i == si else None for i in range(len(uf.GPS_FIELDS)))
        r1 = tuple(1 if i == si else None for i in range(len(uf.GPS_FIELDS)))
        topics = {("sensor_gps", 0): {"rows": [r0]}, ("vehicle_gps_position", 0): {"rows": [r1]}}
        self.assertEqual(uf.choose_topic(topics), ("vehicle_gps_position", 0))
        self.assertIsNone(uf.choose_topic({}))


if __name__ == "__main__":
    unittest.main()
