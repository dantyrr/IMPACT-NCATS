#!/usr/bin/env python3
"""Convert the Census Bureau's state boundary file into GeoJSON for the
Collaboration tab's US map.

Source: US Census Bureau, 2024 Cartographic Boundary File, states, 1:20,000,000
(cb_2024_us_state_20m), KML version:
    https://www2.census.gov/geo/tiger/GENZ2024/kml/cb_2024_us_state_20m.zip

The output, docs/geo/us-states.json, is committed and served by GitHub Pages
with the site, so the map has no runtime data dependency. Coordinates are
rounded to 3 decimals (about 100 m), plenty for a national map. Puerto Rico is
left out: no CTSA hub is there, and the Albers USA projection has no inset for it.

Usage:
    python scripts/build_state_outlines.py path/to/cb_2024_us_state_20m.kml
"""

import sys, os, json, argparse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.config import PROJECT_ROOT

NS = {"k": "http://www.opengis.net/kml/2.2"}
OUT = PROJECT_ROOT / "docs" / "geo" / "us-states.json"


def _ring(el, digits):
    pts = []
    for tok in (el.text or "").split():
        lon, lat = tok.split(",")[:2]
        pts.append([round(float(lon), digits), round(float(lat), digits)])
    return pts


def _signed_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def _orient(rings):
    """D3 draws on a sphere and reads a counterclockwise outer ring as
    "everything except this state", filling the whole map. Census KML (like
    standard GeoJSON) winds outer rings counterclockwise, so flip them to
    clockwise, and holes to counterclockwise."""
    out = []
    for i, r in enumerate(rings):
        clockwise = _signed_area(r) < 0
        out.append(r if clockwise == (i == 0) else r[::-1])
    return out


def kml_to_features(kml_bytes, drop=frozenset({"PR"}), digits=3):
    root = ET.fromstring(kml_bytes)
    feats = []
    for pm in root.iter(f"{{{NS['k']}}}Placemark"):
        data = {d.get("name"): (d.text or "").strip()
                for d in pm.iter(f"{{{NS['k']}}}SimpleData")}
        if data.get("STUSPS") in drop:
            continue
        polys = []
        for poly in pm.iter(f"{{{NS['k']}}}Polygon"):
            rings = [_ring(c, digits) for c in
                     poly.findall("k:outerBoundaryIs/k:LinearRing/k:coordinates", NS)]
            rings += [_ring(c, digits) for c in
                      poly.findall("k:innerBoundaryIs/k:LinearRing/k:coordinates", NS)]
            polys.append(_orient(rings))
        feats.append({"type": "Feature",
                      "properties": {"stusps": data.get("STUSPS"), "name": data.get("NAME")},
                      "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kml", type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    feats = kml_to_features(args.kml.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection",
          "source": "US Census Bureau, 2024 Cartographic Boundary File, states, 1:20,000,000 "
                    "(cb_2024_us_state_20m)",
          "features": feats}
    args.out.write_text(json.dumps(fc, separators=(",", ":")))
    print(f"wrote {args.out} ({len(feats)} states, {args.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
