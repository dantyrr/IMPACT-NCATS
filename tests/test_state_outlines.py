from scripts.build_state_outlines import kml_to_features, _signed_area

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder>
<Placemark>
  <ExtendedData><SchemaData>
    <SimpleData name="STUSPS">RI</SimpleData><SimpleData name="NAME">Rhode Island</SimpleData>
  </SchemaData></ExtendedData>
  <MultiGeometry>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      -71.1,41.1,0 -71.2,41.2,0 -71.3,41.1,0 -71.1,41.1,0
    </coordinates></LinearRing></outerBoundaryIs>
    <innerBoundaryIs><LinearRing><coordinates>
      -71.15,41.12 -71.18,41.14 -71.2,41.12 -71.15,41.12
    </coordinates></LinearRing></innerBoundaryIs></Polygon>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      -71.55551,41.4 -71.6,41.5 -71.7,41.4 -71.55551,41.4
    </coordinates></LinearRing></outerBoundaryIs></Polygon>
  </MultiGeometry>
</Placemark>
<Placemark>
  <ExtendedData><SchemaData>
    <SimpleData name="STUSPS">PR</SimpleData><SimpleData name="NAME">Puerto Rico</SimpleData>
  </SchemaData></ExtendedData>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>
    -66.1,18.1 -66.2,18.2 -66.3,18.1 -66.1,18.1
  </coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark>
</Folder></Document></kml>"""


def test_kml_to_features_keeps_rings_and_rounds():
    feats = kml_to_features(KML.encode(), drop={"PR"}, digits=3)
    assert [f["properties"]["stusps"] for f in feats] == ["RI"]
    ri = feats[0]
    assert ri["properties"]["name"] == "Rhode Island"
    assert ri["geometry"]["type"] == "MultiPolygon"
    polys = ri["geometry"]["coordinates"]
    assert len(polys) == 2
    assert len(polys[0]) == 2                      # outer ring + hole
    assert [-71.1, 41.1] in polys[0][0]            # altitude dropped
    assert [-71.556, 41.4] in polys[1][0]          # rounded to 3 decimals


def test_rings_are_wound_the_way_d3_expects():
    feats = kml_to_features(KML.encode(), drop={"PR"}, digits=3)
    for poly in feats[0]["geometry"]["coordinates"]:
        assert _signed_area(poly[0]) < 0           # outer ring clockwise
        for hole in poly[1:]:
            assert _signed_area(hole) > 0          # holes counterclockwise
