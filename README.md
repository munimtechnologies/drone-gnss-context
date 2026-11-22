# drone-gnss-context

Was it the sky, or was it something here? Give `gnss_context.py` the UTC time and place of a drone flight and it
returns the space-weather and interference context of the flight's GNSS:

- **Kp** for that 3-hour interval and the 24 hours before, from GFZ Potsdam's public Kp service, with the
  NOAA storm level (G0 to G5);
- **magnetic latitude band** (centred dipole): low (equatorial anomaly and plasma-bubble zone, |mlat| < 20),
  mid, high (auroral zone, 55 to 70), polar;
- **local solar time** and whether the flight was in the post-sunset window (19:30 to 01:00) when equatorial
  plasma bubbles form, and whether the month is an equinox season;
- a **GPSJam link** for that UTC day around the place (aircraft-reported navigation accuracy; often a sign of
  jamming). Only the link is given; no GPSJam data is copied.

It is context, not a verdict: a quiet sky does not prove a local cause, and a storm does not prove the storm
caused a given problem.

```bash
python gnss_context.py --time 2024-05-10T20:15Z --lat 52.1 --lon 5.1
```

```
Flight 2024-05-10T20:15:00Z at 52.1000, 5.1000
  magnetic latitude 53.1 (mid band); local solar time 20:35 (night)
  Kp 9- (G4, def) in the interval from 2024-05-10T18:00:00Z; max Kp in 24 h: 9-

- Geomagnetic storm at flight time (Kp 9-, NOAA G4). Storms add ionospheric delay error and scintillation; ...
- Aircraft over this area that day (GPSJam; ...): https://gpsjam.org/?lat=52.10&lon=5.10&z=6&date=2024-05-10
```

(Output abridged; Kp values from GFZ's answer for that interval. The magnetic latitude shown is computed by the
script.)

Options: `--json` for machine-readable output, `--offline` to skip the Kp request. Standard library only,
Python 3.8 or newer. Tests: `python -m unittest -v test_gnss_context`.

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
- Made with AI agents; no human expert has reviewed it yet.

## Credits and licence

Kp: GFZ Potsdam, CC BY 4.0 (Matzka, J., Stolle, C., Yamazaki, Y., Bronkalla, O., Morschhauser, A. (2021). The
geomagnetic Kp index and derived indices of geomagnetic activity. Space Weather, 19, e2020SW002641,
doi:10.1029/2020SW002641). GPSJam: gpsjam.org by John Wiseman (linked, not copied).

Code: Apache-2.0. By MV2 of Munim, Inc. (mv2@munimtech.com); made with AI agents.
