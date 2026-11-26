# drone-gnss-context

Was it the sky, or was it something here? Give `gnss_context.py` a PX4 flight log, or the UTC time and place of
a drone flight, and it returns the space-weather and interference context of the flight's GNSS:

- **Kp** for that 3-hour interval and the 24 hours before, from GFZ Potsdam's public Kp service, with the
  NOAA storm level (G0 to G5);
- **magnetic latitude band** (centred dipole): low (equatorial anomaly and plasma-bubble zone, |mlat| < 20),
  mid, high (auroral zone, 55 to 70), polar;
- **local solar time** and whether the flight was in the post-sunset window (19:30 to 01:00) when equatorial
  plasma bubbles form, and whether the month is an equinox season;
- a **GPSJam link** for that UTC day around the place (aircraft-reported navigation accuracy; often a sign of
  jamming). Only the link is given; no GPSJam data is copied;
- **new in 0.2.0, with `--ulog`:** what the drone's own receiver reported during the flight: spoofing and
  jamming states, the jamming indicator, position jumps no drone can fly, jumps of the receiver's clock against
  the flight controller's clock, and losses of the 3D fix. Time and place come from the log's first good fix.
  When the sky was quiet but the receiver shows interference signs (spoofing flagged, jamming at critical level,
  position or clock jumps), it says so. A jamming *warning* alone does not count: it showed up in 70% of the
  public PX4 logs that report a jamming state in MV2's
  [px4-log-health](https://github.com/munimtechnologies/px4-log-health) fleet study.

It is context, not a verdict: a quiet sky does not prove a local cause, and a storm does not prove the storm
caused a given problem.

```bash
python gnss_context.py --ulog flight.ulg                                   # PX4 log (needs ulog_flight.py too)
python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1       # time and place by hand
```

```
Flight 2024-05-10T20:15:00Z at 52.1000, 5.1000
  magnetic latitude 53.1 (mid band); local solar time 20:35 (night)
  Kp 9- (G4, def) in the interval from 2024-05-10T18:00:00Z; max Kp in 24 h: 9-

- Geomagnetic storm at flight time (Kp 9-, NOAA G4). Storms add ionospheric delay error and scintillation; ...
- Aircraft over this area that day (GPSJam; ...): https://gpsjam.org/?lat=52.10&lon=5.10&z=6&date=2024-05-10
```

(Output abridged; Kp values from GFZ's answer for that interval. The magnetic latitude shown is computed by the
script.) With `--ulog`, one more line sums up the receiver's reports, for example
`receiver log (sensor_gps[0], 5 GNSS samples): spoofing flagged 2/5, jamming warning 1 critical 2, position
jumps 1, clock jumps 1, fix losses 1` (from the synthetic log in the tests), followed by plain-language notes.

Options: `--json` for machine-readable output, `--offline` to skip the Kp request, `--ulog FILE` to read a PX4
log (`--time`, `--lat`, `--lon` override what the log gives; a log whose receiver never set UTC time needs
`--time`). Standard library only, Python 3.8 or newer. Tests:
`python -m unittest -v test_gnss_context test_ulog_flight`.

### Reading a PX4 log

`ulog_flight.py` reads the log on your machine; nothing from the log is uploaded. The only request made is to
GFZ for the Kp values of that time window (no position is sent). It uses the `sensor_gps`,
`vehicle_gps_position` or `vehicle_gnss` topic (preferring one whose receiver reports a spoofing state), reads
positions from `latitude_deg`/`longitude_deg` or the older 1e-7-degree `lat`/`lon`, and works on logs that
are cut short. A "position jump" is a move of more than 1 km at more than 150 m/s between two 3D fixes; a
"clock jump" is the receiver's UTC time running more than 2 s off the log clock between two samples. Older PX4
versions and many receiver drivers do not report spoofing or jamming states; the output says so.

The ULog reader is the one published with MV2's drone-gnss-rfi study 1 (`gnsswatch.py` 0.1.0), copied unchanged.

## For coding agents

An agent skill is in [skills/drone-gnss-context/SKILL.md](skills/drone-gnss-context/SKILL.md):

```bash
npx skills add munimtechnologies/drone-gnss-context
```

## Background

This tool comes out of MV2's open research program
[drone-gnss-rfi](https://github.com/munimtechnologies/drone-gnss-rfi), which asks, with pre-registered studies of
public PX4 flight logs, whether real drones near the ground show the GNSS interference that airliners report, and
whether the 2023-2026 geomagnetic storms and post-sunset plasma bubbles measurably degraded drone GNSS. Those
studies have not produced results yet; this tool makes no claim about their outcome.

## Limits

- Centred-dipole magnetic latitude (pole 80.7 N, 72.7 W) is a coarse approximation of the real field; band edges
  are rough guides, not physical boundaries.
- Kp is a planetary 3-hour index; local disturbance can be stronger or weaker. GFZ marks recent values `now`
  (nowcast) until they become definitive (`def`).
- Plasma-bubble season and timing vary by longitude sector and solar cycle; the equinox flag is a rule of thumb.
- GPSJam maps are built from aircraft at altitude and say nothing about the cause; local jamming near the
  ground can be missed.
- A receiver's spoofing and jamming states are its own heuristics and differ between receiver models; a position
  or clock jump can also come from a receiver or logging fault. Kp and receiver reports are given for the log's
  first good fix and the whole log; they are not lined up minute by minute.
- Tested on synthetic logs built in the tests, not yet on a broad set of real flight logs.
- Made with AI agents; no human expert has reviewed it yet.

## Changes

- 0.2.0 (2026-11-26): `--ulog` reads a PX4 log (`ulog_flight.py`): time and place from the first good fix, and a
  summary of the receiver's own spoofing, jamming, position-jump, clock-jump and fix-loss reports, with a note
  when a quiet sky meets interference signs.
- 0.1.0 (2026-11-22): first release.

## Credits and licence

Kp: GFZ Potsdam, CC BY 4.0 (Matzka, J., Stolle, C., Yamazaki, Y., Bronkalla, O., Morschhauser, A. (2021). The
geomagnetic Kp index and derived indices of geomagnetic activity. Space Weather, 19, e2020SW002641,
doi:10.1029/2020SW002641). GPSJam: gpsjam.org by John Wiseman (linked, not copied). ULog format: PX4
documentation.

Code: Apache-2.0. By MV2 of Munim, Inc. (mv2@munimtech.com); made with AI agents.
