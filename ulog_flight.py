"""ulog_flight: what a PX4 flight log (.ulg) says about its own GNSS, for drone-gnss-context.

It reads one ULog file locally (nothing is sent anywhere) and returns
- the flight's first good 3D fix: UTC time (from the receiver's time_utc_usec), latitude and longitude, so
  gnss_context.py no longer needs them typed in;
- what the receiver itself reported during the log: spoofing states, jamming states and the jamming indicator;
- signs of manipulation or trouble in the log: position jumps no drone can fly ("teleports"), jumps of the
  receiver's clock against the flight controller's clock, and losses of the 3D fix.

The ULog reader below is the one published with MV2's drone-gnss-rfi study 1 (gnsswatch.py 0.1.0,
https://github.com/munimtechnologies/drone-gnss-rfi), copied unchanged: standard library only, it decodes just
the topics it is asked for and also works on a log that is cut short.

Field meanings follow PX4's sensor_gps message: spoofing_state 0 unknown, 1 none, 2 indicated, 3 multiple
indications; jamming_state 0 unknown, 1 ok, 2 warning, 3 critical.

By MV2 of Munim, Inc. (mv2@munimtech.com); made with AI agents. Apache-2.0.
"""

from __future__ import annotations

import math
import struct
import time

__version__ = "0.2.0"

# ---------------------------------------------------------------- ULog reading (from gnsswatch 0.1.0)

MAGIC = b"ULog\x01\x12\x35"
SYNC = bytes([0x2F, 0x73, 0x13, 0x20, 0x25, 0x0C, 0xBB, 0x12])
KNOWN = set(b"FIAMPQBDLCSOR")
BASIC = {"int8_t": ("b", 1), "uint8_t": ("B", 1), "int16_t": ("h", 2), "uint16_t": ("H", 2),
         "int32_t": ("i", 4), "uint32_t": ("I", 4), "int64_t": ("q", 8), "uint64_t": ("Q", 8),
         "float": ("f", 4), "double": ("d", 8), "bool": ("B", 1), "char": ("B", 1)}
_HDR = struct.Struct("<HB")
_U16 = struct.Struct("<H")


class NotULog(ValueError):
    pass


def parse_format(text):
    """('name', [(type, count or None, field), ...]) from a format string 'name:type field;type[n] field;'."""
    name, sep, rest = text.partition(":")
    if not sep or not name.strip():
        raise ValueError("not a format string")
    fields = []
    for part in rest.split(";"):
        part = part.strip()
        if not part:
            continue
        typ, _, fname = part.rpartition(" ")
        typ, fname = typ.strip(), fname.strip()
        if not typ or not fname:
            raise ValueError("bad field %r" % part)
        count = None
        if typ.endswith("]") and "[" in typ:
            typ, _, n = typ[:-1].partition("[")
            count = int(n)
        fields.append((typ, count, fname))
    return name.strip(), fields


def layout(name, formats, _depth=0):
    """(struct codes without the '<' prefix, [flat field names]) of one format. Nested types become
    'outer.inner', arrays 'field[i]'; _padding fields are skipped bytes with no name."""
    if _depth > 32:
        raise ValueError("nesting too deep")
    codes, names = [], []
    for typ, count, fname in formats[name]:
        reps = 1 if count is None else count
        pad = fname.startswith("_padding")
        if typ in BASIC:
            code, size = BASIC[typ]
            if pad:
                codes.append("%dx" % (size * reps))
                continue
            for i in range(reps):
                codes.append(code)
                names.append(fname if count is None else "%s[%d]" % (fname, i))
        else:
            sub_codes, sub_names = layout(typ, formats, _depth + 1)
            if pad:
                codes.append("%dx" % (struct.calcsize("<" + sub_codes) * reps))
                continue
            for i in range(reps):
                prefix = fname if count is None else "%s[%d]" % (fname, i)
                codes.append(sub_codes)
                names.extend(prefix + "." + n for n in sub_names)
    return "".join(codes), names


def resolve(names, want):
    """The flat name for a wanted field: an exact match, else the first nested name ending in '.want'."""
    if want in names:
        return want
    tail = "." + want
    for n in names:
        if n.endswith(tail):
            return n
    return None


def read_topics(buf, wanted):
    """Decode the topics named in `wanted` ({topic: [field, ...]}) from ULog bytes, which may be cut short.

    Returns (topics, info). topics maps (topic, multi_id) to {"fields": [resolved name or None per wanted
    field], "rows": [tuple of values in the wanted order, None where the log has no such field]}.
    info has "bytes", "truncated" (bytes left over that do not form a whole message) and "resyncs"."""
    if len(buf) < 16 or bytes(buf[:7]) != MAGIC:
        raise NotULog("not a ULog file")
    formats, subs, topics = {}, {}, {}
    info = {"bytes": len(buf), "truncated": False, "resyncs": 0}
    pos, n = 16, len(buf)
    while pos + 3 <= n:
        size, mtype = _HDR.unpack_from(buf, pos)
        if mtype not in KNOWN:
            nxt = buf.find(SYNC, pos + 1)
            if nxt < 0:
                break
            info["resyncs"] += 1
            pos = nxt + len(SYNC)
            continue
        start, end = pos + 3, pos + 3 + size
        if end > n:
            break
        if mtype == 0x44:                                   # 'D' data
            if size >= 2:
                sub = subs.get(_U16.unpack_from(buf, start)[0])
                if sub is not None:
                    st, idx, rows = sub
                    payload = buf[start + 2:end]
                    if len(payload) < st.size:              # a trailing _padding field may not be logged
                        payload = payload + b"\0" * (st.size - len(payload))
                    vals = st.unpack_from(payload, 0)
                    rows.append(tuple(vals[i] if i is not None else None for i in idx))
        elif mtype == 0x46:                                 # 'F' format
            try:
                name, fields = parse_format(buf[start:end].decode("utf-8", "replace").rstrip("\0"))
            except ValueError:
                pass
            else:
                formats[name] = fields
        elif mtype == 0x41:                                 # 'A' subscription
            if size >= 3:
                multi_id = buf[start]
                msg_id = _U16.unpack_from(buf, start + 1)[0]
                name = buf[start + 3:end].decode("utf-8", "replace").rstrip("\0")
                subs.pop(msg_id, None)
                if name in wanted:
                    try:
                        codes, names = layout(name, formats)
                        st = struct.Struct("<" + codes)
                    except (KeyError, ValueError, struct.error):
                        pass
                    else:
                        res = [resolve(names, w) for w in wanted[name]]
                        idx = [names.index(r) if r is not None else None for r in res]
                        topic = topics.setdefault((name, multi_id), {"fields": res, "rows": []})
                        subs[msg_id] = (st, idx, topic["rows"])
        elif mtype == 0x52:                                 # 'R' remove subscription
            if size >= 2:
                subs.pop(_U16.unpack_from(buf, start)[0], None)
        pos = end
    info["truncated"] = pos < n
    return topics, info


# ---------------------------------------------------------------- one flight's GNSS

GPS_TOPICS = ("sensor_gps", "vehicle_gps_position", "vehicle_gnss")
GPS_FIELDS = ("timestamp", "time_utc_usec", "fix_type", "latitude_deg", "longitude_deg", "lat", "lon", "eph",
              "satellites_used", "spoofing_state", "jamming_state", "jamming_indicator")
WANTED = {t: GPS_FIELDS for t in GPS_TOPICS}
_G = {f: i for i, f in enumerate(GPS_FIELDS)}

EARTH_R_M = 6371008.8
TELEPORT_MIN_M = 1000.0
TELEPORT_MIN_SPEED = 150.0          # m/s; no multicopter or small drone flies this fast
UTC_JUMP_US = 2000000               # receiver time running 2 s off the log clock between two samples
GOOD_MAX_EPH = 20.0                 # a "good" first fix: horizontal accuracy under 20 m ...
GOOD_MIN_SATS = 6                   # ... with at least 6 satellites
UTC_MIN_S, UTC_MAX_S = 1420070400, 2240611200     # 2015-01-01 and 2041-01-01, 00:00 UTC


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    k = len(xs) // 2
    return xs[k] if len(xs) % 2 else (xs[k - 1] + xs[k]) / 2


def position(row):
    """(lat, lon) in degrees from latitude_deg/longitude_deg, or from the older int32 lat/lon (1e-7 deg)."""
    la, lo = row[_G["latitude_deg"]], row[_G["longitude_deg"]]
    if la is None or lo is None:
        la, lo = row[_G["lat"]], row[_G["lon"]]
        if la is None or lo is None:
            return None
        la, lo = la * 1e-7, lo * 1e-7
    if not (math.isfinite(la) and math.isfinite(lo)) or not (-90 <= la <= 90 and -180 <= lo <= 180):
        return None
    if la == 0 and lo == 0:
        return None
    return la, lo


def utc_seconds(us):
    """Whole UTC epoch seconds from microseconds, or None outside 2015-2040 (receiver time not set)."""
    if us is None:
        return None
    s = int(us) // 1000000
    return s if UTC_MIN_S <= s < UTC_MAX_S else None


def iso(s):
    return None if s is None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s))


def summarize(rows):
    """Summary of one GNSS topic's rows (tuples in GPS_FIELDS order, in log order)."""
    g = _G
    spoof, jam, jind = [0, 0, 0, 0], [0, 0, 0, 0], []
    n_fix, good, weak, max_eph = 0, None, None, None
    offset = None                       # receiver UTC minus log clock (us), from the first row with both
    teleports, max_jump, utc_jumps, max_utc, fix_losses = 0, None, 0, None, 0
    prev_fix = prev_utc = None
    had_fix = False
    t_first = t_last = None
    for r in rows:
        t = r[g["timestamp"]]
        if t is not None:
            if t_first is None:
                t_first = t
            t_last = t
        s = r[g["spoofing_state"]]
        if s is not None and 0 <= s <= 3:
            spoof[s] += 1
        j = r[g["jamming_state"]]
        if j is not None and 0 <= j <= 3:
            jam[j] += 1
        ji = r[g["jamming_indicator"]]
        if ji is not None:
            jind.append(ji)
        u = r[g["time_utc_usec"]]
        if u and t is not None and utc_seconds(u) is not None:
            if offset is None:
                offset = u - t
            if prev_utc is not None:
                d = abs((u - prev_utc[0]) - (t - prev_utc[1]))
                if d > UTC_JUMP_US:
                    utc_jumps += 1
                    max_utc = d / 1e6 if max_utc is None else max(max_utc, d / 1e6)
            prev_utc = (u, t)
        fix = r[g["fix_type"]]
        has3d = fix is not None and fix >= 3
        if fix is not None:
            if had_fix and not has3d:
                fix_losses += 1
            had_fix = has3d
        pos = position(r) if has3d else None
        if pos is None or t is None:
            continue
        n_fix += 1
        eph, sats = r[g["eph"]], r[g["satellites_used"]]
        if eph is not None and math.isfinite(eph):
            max_eph = eph if max_eph is None else max(max_eph, eph)
        if weak is None:
            weak = (t, pos, eph, sats)
        if good is None and (eph is None or eph < GOOD_MAX_EPH) and (sats is None or sats >= GOOD_MIN_SATS):
            good = (t, pos, eph, sats)
        if prev_fix is not None:
            dt = (t - prev_fix[2]) / 1e6
            if dt > 0:
                dist = haversine_m(prev_fix[0], prev_fix[1], pos[0], pos[1])
                if dist > TELEPORT_MIN_M and dist / dt > TELEPORT_MIN_SPEED:
                    teleports += 1
                    km = dist / 1000.0
                    max_jump = km if max_jump is None else max(max_jump, km)
        prev_fix = (pos[0], pos[1], t)

    def at(t):
        return None if offset is None or t is None else utc_seconds(t + offset)

    first = None
    pick = good if good is not None else weak
    if pick is not None:
        t, pos, eph, sats = pick
        first = {"time_utc": at(t), "time_iso": iso(at(t)), "log_time_s": round(t / 1e6, 3),
                 "lat": pos[0], "lon": pos[1], "eph": None if eph is None else round(eph, 2),
                 "satellites_used": sats, "quality": "good" if pick is good else "weak"}
    return {"n_gps": len(rows), "n_fix": n_fix, "first_fix": first,
            "utc_start": iso(at(t_first)), "utc_end": iso(at(t_last)),
            "duration_s": None if t_first is None else round((t_last - t_first) / 1e6, 1),
            "spoofing": {"counts": spoof, "reporting": spoof[1] + spoof[2] + spoof[3],
                         "indicated": spoof[2] + spoof[3], "multiple": spoof[3]},
            "jamming": {"counts": jam, "reporting": jam[1] + jam[2] + jam[3], "warning": jam[2],
                        "critical": jam[3], "indicator_max": max(jind) if jind else None,
                        "indicator_median": median(jind)},
            "teleports": teleports, "max_jump_km": None if max_jump is None else round(max_jump, 1),
            "utc_jumps": utc_jumps, "max_utc_jump_s": None if max_utc is None else round(max_utc, 3),
            "fix_losses": fix_losses, "max_eph": None if max_eph is None else round(max_eph, 2)}


def choose_topic(topics):
    """The GNSS topic to summarise: the lowest instance of sensor_gps, vehicle_gps_position, vehicle_gnss (in
    that order) whose rows carry a non-zero spoofing state; else the first with rows."""
    cands = []
    for t in GPS_TOPICS:
        keys = sorted(k for k in topics if k[0] == t and topics[k]["rows"])
        if keys:
            cands.append(keys[0])
    if not cands:
        return None
    si = _G["spoofing_state"]
    for k in cands:
        if any(r[si] for r in topics[k]["rows"]):
            return k
    return cands[0]


def read_flight(buf):
    """(summary or None, parse info) for one log's bytes. The summary also names the topic it was built from."""
    topics, info = read_topics(buf, WANTED)
    key = choose_topic(topics)
    if key is None:
        return None, info
    s = summarize(topics[key]["rows"])
    s["topic"] = "%s[%d]" % key
    return s, info


def read_file(path):
    with open(path, "rb") as f:
        return read_flight(f.read())


def suspicious(s):
    """True when the log itself shows signs of interference: spoofing flagged by the receiver, jamming at
    critical level, position jumps no drone can fly, or receiver clock jumps. A jamming warning alone does not
    count: it shows up in most public PX4 logs that report a jamming state (px4-log-health fleet study: 70%)."""
    return bool(s["spoofing"]["indicated"] or s["jamming"]["critical"] or s["teleports"] or s["utc_jumps"])
