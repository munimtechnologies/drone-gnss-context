---
name: drone-gnss-context
description: Check whether a drone flight's GPS/GNSS trouble coincided with a geomagnetic storm, the post-sunset equatorial plasma-bubble window, auroral-zone conditions, or aircraft-reported interference (GPSJam) at that time and place. Use when someone asks why a drone, PX4/ArduPilot vehicle or GNSS receiver lost accuracy, RTK fix or satellite lock at a known time and location.
---

# drone-gnss-context

A standard-library Python script that gives the space-weather and interference context of one flight from its
UTC time and position. It does not read the log itself and it is not a safety verdict.

## When to use

- A user reports GPS glitches, drift, "GPS lost", high EPH/EPV, RTK fix loss, or a jamming/spoofing flag on a
  drone flight and knows roughly when (UTC) and where it flew.
- Before blaming hardware, to rule space weather in or out.

## How to run

```bash
curl -sO https://raw.githubusercontent.com/munimtechnologies/drone-gnss-context/main/gnss_context.py
python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1          # text
python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1 --json   # JSON for further use
```

- `--time`: ISO 8601; no offset means UTC. Epoch seconds also work. Use the flight's start, or the moment the
  problem began.
- `--lat`, `--lon`: decimal degrees; a city-level position is enough (round it if the user's location is private).
- It makes one HTTPS request to GFZ Potsdam's public Kp service. `--offline` skips it (no storm check then).

To get time and position from a PX4 log: in PX4 Flight Review, or with `pyulog` (`ulog_info` / `ulog2csv`
on the `vehicle_gps_position` or `sensor_gps` topic: `time_utc_usec`, `latitude_deg`, `longitude_deg`).

## Reading the result

- `kp.g_scale` 1-5: a NOAA G1-G5 geomagnetic storm in that 3-hour interval; `g_scale_max_24h`: in the day before.
- `mag_band` low + `time_class` night (+ `equinox_season`): equatorial plasma-bubble window (scintillation,
  loss of lock).
- `mag_band` high/polar during a storm: auroral scintillation likely.
- `gpsjam`: a link to that UTC day's GPSJam map around the place. Open it and look at the hexes near the
  flight: red/yellow means many aircraft reported degraded navigation, often jamming. Absence of colour does
  not clear low-altitude local jamming.
- `notes`: plain-language summary. Report them, then suggest local causes when no red flag shows (jamming,
  obstructions, multipath, antenna placement, self-interference from the drone's electronics).

Tell the user it is context, not proof of cause.

Licence: Apache-2.0. Kp data: GFZ Potsdam, CC BY 4.0 (Matzka et al. 2021). By MV2 of Munim, Inc.
(mv2@munimtech.com); made with AI agents.
