"""drone-gnss-context: space-weather and interference context for one drone flight's GNSS.

Give it when (UTC) and where a flight happened. It answers the first questions an operator asks after a
GNSS problem ("was it the sky, or was it something here?"):

- the planetary geomagnetic index Kp for that 3-hour interval and the 24 hours before it, from GFZ Potsdam's
  public Kp web service (CC BY 4.0, Matzka et al. 2021), with the NOAA storm level (G0 to G5);
- the flight's centred-dipole magnetic latitude band (low: plasma-bubble zone; mid; high: auroral zone; polar);
- local solar time and whether the flight was in the post-sunset window when equatorial plasma bubbles form;
- whether the month is an equinox season (when plasma bubbles are most frequent in most longitude sectors);
- a link to the GPSJam map of that UTC day around the place (aircraft-reported navigation accuracy, often a sign
  of jamming). Only the link is given; no GPSJam data is copied.

It is information, not a safety verdict: a quiet sky does not prove a local cause, and a storm does not prove the
storm caused a given problem.

Standard library only. Usage:

    python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1
    python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1 --json

By MV2 of Munim, Inc. (mv2@munimtech.com); made with AI agents. Apache-2.0.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request

__version__ = "0.1.0"

INTERVAL_S = 10800                      # Kp is given for 3-hour UTC intervals starting 00, 03, ..., 21 UT
DAY_S = 86400
EPS = 1e-3
POLE_LAT, POLE_LON = 80.7, -72.7        # centred-dipole north geomagnetic pole, close to IGRF for 2020-2025
EQUINOX_MONTHS = (2, 3, 4, 9, 10, 11)
GFZ_URL = "https://kp.gfz.de/app/json/"
GPSJAM_FIRST = "2022-02-14"             # GPSJam has no data before this day
USER_AGENT = "drone-gnss-context/%s (+https://github.com/munimtechnologies/drone-gnss-context)" % __version__


# ---------------------------------------------------------------- time

def parse_time(text):
    """UTC epoch seconds from ISO 8601 text ('2024-05-10T20:15:00Z', '2024-05-10 20:15', '...+02:00'; no offset
    means UTC) or from a plain number of epoch seconds."""
    s = str(text).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s))
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    d = datetime.datetime.fromisoformat(s.replace(" ", "T", 1))
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp())


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def iso_day(t):
    return time.strftime("%Y-%m-%d", time.gmtime(t))


# ---------------------------------------------------------------- place and local time

def mag_lat(lat, lon):
    """Centred-dipole geomagnetic latitude (degrees) of a point (degrees)."""
    p, la = math.radians(POLE_LAT), math.radians(lat)
    s = math.sin(la) * math.sin(p) + math.cos(la) * math.cos(p) * math.cos(math.radians(lon - POLE_LON))
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def mag_band(mlat):
    """low (|mlat| < 20: equatorial anomaly and plasma-bubble zone), mid (20 to 55), high (55 to 70: auroral zone,
    which moves equatorward in storms) or polar (70 or more)."""
    a = abs(mlat)
    if a < 20.0:
        return "low"
    if a < 55.0:
        return "mid"
    if a < 70.0:
        return "high"
    return "polar"


def local_solar_hour(t, lon):
    """Mean local solar time (hours, 0 to < 24) at UTC epoch second t and longitude lon (degrees)."""
    return ((t % DAY_S) / 3600.0 + lon / 15.0) % 24.0


def time_class(lst):
    """night: 19:30 to 01:00 (post-sunset plasma-bubble window); day: 08:00 to 17:00; dusk: 17:00 to 19:30;
    late: 01:00 to 08:00."""
    if lst >= 19.5 or lst < 1.0:
        return "night"
    if 8.0 <= lst < 17.0:
        return "day"
    if 17.0 <= lst < 19.5:
        return "dusk"
    return "late"


def equinox_season(t):
    return time.gmtime(t).tm_mon in EQUINOX_MONTHS


# ---------------------------------------------------------------- Kp

def kp_label(kp):
    """Kp in the usual thirds notation: 4.667 -> '5-', 5.0 -> '5o', 5.333 -> '5+'."""
    if kp is None:
        return None
    n = int(round(kp * 3))
    base = (n + 1) // 3
    return "%d%s" % (base, {-1: "-", 0: "o", 1: "+"}[n - 3 * base])


def g_scale(kp):
    """NOAA geomagnetic storm level: G1 at Kp 5- to 5+, G2 at 6, G3 at 7, G4 at 8- to 9-, G5 at 9o; else 0."""
    if kp is None:
        return None
    for g, low in ((5, 9.0), (4, 7.667), (3, 6.667), (2, 5.667), (1, 4.667)):
        if kp >= low - EPS:
            return g
    return 0


def kp_url(t0, t1):
    q = {"start": iso(t0), "end": iso(t1), "index": "Kp"}
    return GFZ_URL + "?" + urllib.parse.urlencode(q, safe=":")


def parse_kp_json(obj):
    """{interval start (UTC epoch s): (Kp, status)} from GFZ's JSON answer ({"datetime": [...], "Kp": [...],
    "status": ["def" or "now", ...]}). Missing values (None or negative) are skipped."""
    out = {}
    kps, dts, st = obj.get("Kp") or [], obj.get("datetime") or [], obj.get("status") or []
    for i, (d, k) in enumerate(zip(dts, kps)):
        try:
            kv = float(k)
        except (TypeError, ValueError):
            continue
        if kv < 0 or not math.isfinite(kv):
            continue
        out[parse_time(d)] = (kv, st[i] if i < len(st) else None)
    return out


def fetch_kp(t, opener=None, timeout=20):
    """Kp series for the interval holding t and the 7 intervals before it (24 hours), from GFZ."""
    s = int(t) // INTERVAL_S * INTERVAL_S
    url = kp_url(s - 7 * INTERVAL_S, s + INTERVAL_S - 1)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
        return parse_kp_json(json.loads(resp.read().decode("utf-8")))


def kp_context(series, t):
    s = int(t) // INTERVAL_S * INTERVAL_S
    cur = series.get(s) if series else None
    prev = [series[x][0] for x in range(s - 7 * INTERVAL_S, s + 1, INTERVAL_S) if series and x in series]
    kp = cur[0] if cur else None
    mx = max(prev) if prev else None
    return {"interval_start": iso(s), "kp": kp, "kp_label": kp_label(kp), "kp_status": cur[1] if cur else None,
            "g_scale": g_scale(kp), "max_kp_24h": mx, "max_kp_24h_label": kp_label(mx), "g_scale_max_24h": g_scale(mx)}


# ---------------------------------------------------------------- GPSJam

def gpsjam_link(t, lat, lon, now=None):
    """Link to GPSJam's map of the flight's UTC day around the place, or None before GPSJam's first day or before
    that day's map can exist (maps appear soon after the UTC day ends)."""
    day = iso_day(t)
    now = time.time() if now is None else now
    if day < GPSJAM_FIRST or (int(t) // DAY_S + 1) * DAY_S > now:
        return None
    return "https://gpsjam.org/?lat=%.2f&lon=%.2f&z=6&date=%s" % (lat, lon, day)


# ---------------------------------------------------------------- context

def notes(c):
    """Plain-language notes for a context dict."""
    out = []
    k = c["kp"]
    if k["kp"] is None:
        out.append("Kp unavailable for this interval (no network, or the time is in the future), so the "
                   "geomagnetic storm check was skipped.")
    elif k["g_scale"] >= 1:
        text = ("Geomagnetic storm at flight time (Kp %s, NOAA G%d). Storms add ionospheric delay error and "
                "scintillation; single-frequency receivers, which most drones carry, are hit hardest."
                % (k["kp_label"], k["g_scale"]))
        if k["g_scale"] >= 3:
            text += (" In the Kp 9 storm of 10-11 May 2024, ground GNSS stations saw position errors grow "
                     "several-fold and RTK users, including farm machinery, lost accuracy.")
        out.append(text)
    elif (k["g_scale_max_24h"] or 0) >= 1:
        out.append("No storm in the flight's own 3-hour interval, but a storm was under way in the 24 hours "
                   "before (max Kp %s, NOAA G%d); the ionosphere can stay disturbed for hours."
                   % (k["max_kp_24h_label"], k["g_scale_max_24h"]))
    if c["mag_band"] == "low" and c["time_class"] == "night":
        if c["equinox_season"]:
            out.append("Post-sunset hours at low magnetic latitude in an equinox season: the main time and place "
                       "of equatorial plasma bubbles, which cause scintillation and loss of satellite lock "
                       "(most frequent near solar maximum).")
        else:
            out.append("Post-sunset hours at low magnetic latitude: equatorial plasma bubbles form at this time "
                       "of night, though less often outside the equinox seasons in most longitude sectors.")
    if c["mag_band"] in ("high", "polar") and k["kp"] is not None and k["g_scale"] >= 1:
        out.append("Auroral or polar-cap flight during a storm: fast ionospheric gradients and phase "
                   "scintillation are likely.")
    if not out:
        out.append("No space-weather red flag for this time and place. If GNSS was degraded, look at local "
                   "causes first: jamming or spoofing, obstructions and multipath, antenna placement, and "
                   "interference from the drone's own electronics.")
    if c["gpsjam"]:
        out.append("Aircraft over this area that day (GPSJam; red or yellow hexes mean many aircraft reported "
                   "degraded navigation, which often means jamming): " + c["gpsjam"])
    return out


def context(t, lat, lon, series=None, now=None):
    """Everything above for one flight: t in UTC epoch seconds, lat/lon in degrees. series is a Kp series as from
    fetch_kp (None: Kp unknown)."""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("latitude must be -90..90 and longitude -180..180")
    ml = mag_lat(lat, lon)
    lst = local_solar_hour(t, lon)
    c = {"version": __version__, "time_utc": iso(t), "lat": round(lat, 4), "lon": round(lon, 4),
         "mag_lat": round(ml, 1), "mag_band": mag_band(ml),
         "local_solar_time": "%02d:%02d" % divmod(int(round(lst * 60)) % 1440, 60),
         "local_solar_hour": round(lst, 3), "time_class": time_class(lst), "equinox_season": equinox_season(t),
         "kp": kp_context(series, t), "gpsjam": gpsjam_link(t, lat, lon, now)}
    c["notes"] = notes(c)
    c["sources"] = ["Kp: GFZ Potsdam, CC BY 4.0 (Matzka et al. 2021, doi:10.1029/2020SW002641)",
                    "GPSJam: gpsjam.org (link only)"]
    return c


def render(c):
    k = c["kp"]
    lines = ["Flight %s at %.4f, %.4f" % (c["time_utc"], c["lat"], c["lon"]),
             "  magnetic latitude %.1f (%s band); local solar time %s (%s)%s"
             % (c["mag_lat"], c["mag_band"], c["local_solar_time"], c["time_class"],
                "; equinox season" if c["equinox_season"] else ""),
             "  Kp %s (G%s, %s) in the interval from %s; max Kp in 24 h: %s"
             % (k["kp_label"] or "unknown", "?" if k["g_scale"] is None else k["g_scale"], k["kp_status"] or "-",
                k["interval_start"], k["max_kp_24h_label"] or "unknown"),
             ""]
    lines += ["- " + n for n in c["notes"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Space-weather and interference context for a drone flight's GNSS.")
    ap.add_argument("--time", required=True, help="flight time, ISO 8601 (no offset = UTC) or epoch seconds")
    ap.add_argument("--lat", required=True, type=float, help="latitude, degrees")
    ap.add_argument("--lon", required=True, type=float, help="longitude, degrees")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--offline", action="store_true", help="do not fetch Kp from GFZ")
    a = ap.parse_args(argv)
    try:
        t = parse_time(a.time)
    except ValueError:
        print("could not read --time %r" % a.time, file=sys.stderr)
        return 2
    series = None
    if not a.offline:
        try:
            series = fetch_kp(t)
        except (OSError, ValueError) as error:
            print("Kp fetch failed: %s" % error, file=sys.stderr)
    try:
        c = context(t, a.lat, a.lon, series)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(c, indent=1) if a.json else render(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
