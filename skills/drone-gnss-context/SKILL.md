---
name: drone-gnss-context
description: Check whether a drone flight's GPS/GNSS trouble coincided with a geomagnetic storm, the post-sunset equatorial plasma-bubble window, auroral-zone conditions, or aircraft-reported interference (GPSJam), and what the drone's own receiver reported (spoofing, jamming, position jumps, clock jumps, fix loss) in a PX4 .ulg log. Use when someone asks why a drone, PX4/ArduPilot vehicle or GNSS receiver lost accuracy, RTK fix or satellite lock, or whether a flight was jammed or spoofed.
---

# drone-gnss-context

Standard-library Python that gives the space-weather and interference context of one flight, from a PX4 flight
log (.ulg) or from its UTC time and position. It is context, not a safety verdict.

## When to use

- A user reports GPS glitches, drift, "GPS lost", high EPH/EPV, RTK fix loss, or a jamming/spoofing warning on a
  drone flight, and has the PX4 log or knows roughly when (UTC) and where it flew.
- Before blaming hardware, to rule space weather in or out, and to see whether the receiver itself saw
  interference.

## How to run

```bash
curl -sO https://raw.githubusercontent.com/munimtechnologies/drone-gnss-context/main/gnss_context.py
curl -sO https://raw.githubusercontent.com/munimtechnologies/drone-gnss-context/main/ulog_flight.py
python gnss_context.py --ulog flight.ulg                                      # from a PX4 log
python gnss_context.py --ulog flight.ulg --json                               # JSON for further use
python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1          # without a log
```

- `--ulog`: a PX4 .ulg file. Read locally; nothing from it is uploaded. Time and position come from the first
  good GNSS fix. If the receiver never set UTC time (older logs), add `--time`.
- `--time`: ISO 8601; no offset means UTC. Epoch seconds also work. Overrides the log's time.
- `--lat`, `--lon`: decimal degrees; a city-level position is enough (round it if the user's location is private).
- It makes one HTTPS request to GFZ Potsdam's public Kp service (time window only). `--offline` skips it (no
  storm check then).

## Reading the result

- `kp.g_scale` 1-5: a NOAA G1-G5 geomagnetic storm in that 3-hour interval; `g_scale_max_24h`: in the day before.
- `mag_band` low + `time_class` night (+ `equinox_season`): equatorial plasma-bubble window (scintillation,
  loss of lock).
- `mag_band` high/polar during a storm: auroral scintillation likely.
- `gpsjam`: a link to that UTC day's GPSJam map around the place. Red/yellow hexes near the flight mean many
  aircraft reported degraded navigation, often jamming. Absence of colour does not clear low-altitude jamming.
- `receiver` (with `--ulog`): `spoofing.indicated` of `spoofing.reporting` samples, `jamming.warning` /
  `jamming.critical`, `teleports` (position jumps > 1 km at > 150 m/s), `utc_jumps` (receiver clock jumps > 2 s),
  `fix_losses`, and `first_fix`. `reporting` 0 means the receiver or PX4 version does not report these states.
- `notes`: plain-language summary. Report them. A quiet sky plus receiver interference signs (spoofing
  indicated, jamming critical, position or clock jumps) points to local or regional jamming/spoofing. A jamming
  *warning* alone is common in public PX4 logs and weak evidence. With no red flags at all, suggest local causes (obstructions, multipath, antenna
  placement, self-interference from the drone's electronics).

Tell the user it is context, not proof of cause, and that receiver spoofing/jamming flags are the receiver's own
heuristics.

Licence: Apache-2.0. Kp data: GFZ Potsdam, CC BY 4.0 (Matzka et al. 2021). By MV2 of Munim, Inc.
(mv2@munimtech.com); made with AI agents.
