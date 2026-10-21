import pytest
from src.ncats.gazetteer import Gazetteer, Point, city_key, place_keys, km, path

PLACE = """USPS|GEOID|GEOIDFQ|ANSICODE|NAME|LSAD|FUNCSTAT|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG
MD|2404000|x|x|Baltimore city|25|A|209000000|0|0|0|39.300|-76.610
MD|2407125|x|x|Bethesda CDP|57|S|34000000|0|0|0|38.987|-77.105
MO|2965000|x|x|St. Louis city|25|A|160000000|0|0|0|38.636|-90.244
TN|4752006|x|x|Nashville-Davidson metropolitan government (balance)|00|F|1230000000|0|0|0|36.171|-86.785
CA|0665042|x|x|San Buenaventura (Ventura) city|25|A|56000000|0|0|0|34.267|-119.255
CA|0666000|x|x|San Diego city|25|A|840000000|0|0|0|32.818|-117.135
CA|0699999|x|x|Franklin CDP|57|S|1000|0|0|0|35.0|-120.0
CA|0699998|x|x|Franklin city|25|A|500|0|0|0|36.0|-121.0
"""
COUSUB = """USPS|GEOID|GEOIDFQ|ANSICODE|NAME|FUNCSTAT|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG
NY|3604710022|x|x|Brooklyn borough|G|180000000|0|0|0|40.635|-73.950
NH|3300933860|x|x|Hanover town|A|127000000|0|0|0|43.711|-72.204
"""
ZCTA = """GEOID\tGEOIDFQ\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\tINTPTLONG
21205\tx\t5000000\t0\t0\t0\t39.302\t-76.578
"""


@pytest.fixture
def gaz(tmp_path):
    for kind, text in (("place", PLACE), ("cousubs", COUSUB), ("zcta", ZCTA)):   # zcta: older, tab format
        p = path(kind, tmp_path, 2026)
        p.parent.mkdir(parents=True)
        p.write_text(text)
    return Gazetteer.load(tmp_path, 2026)


def test_city_key():
    assert city_key("Saint Louis") == city_key("St. Louis") == "st louis"
    assert city_key("Ft. Worth") == "fort worth"
    assert city_key("Bethesda 20892") == "bethesda"


def test_place_keys_drop_census_descriptors():
    assert place_keys("Baltimore city") == {"baltimore"}
    assert place_keys("Boise City city") == {"boise city"}
    assert place_keys("Nashville-Davidson metropolitan government (balance)") == {"nashville davidson", "nashville"}
    assert place_keys("San Buenaventura (Ventura) city") == {"san buenaventura", "ventura"}
    assert place_keys("Winston-Salem city") == {"winston salem"}
    assert place_keys("Amherst Town city") == {"amherst"}


def test_city_point(gaz):
    assert gaz.city_point("Baltimore", "MD").geoid == "2404000"
    assert gaz.city_point("Saint Louis", "MO").name == "St. Louis city"
    assert gaz.city_point("Nashville", "TN").geoid == "4752006"
    assert gaz.city_point("La Jolla", "CA").name == "San Diego city"          # alias
    assert gaz.city_point("Brooklyn", "NY").kind == "cousubs"                 # NYC borough
    assert gaz.city_point("Hanover", "NH").name == "Hanover town"             # New England town
    assert gaz.city_point("Franklin", "CA").name == "Franklin city"           # government over CDP
    assert gaz.city_point("Baltimore", "MA") is None                          # state must match
    assert gaz.city_point(None, "MD") is None


def test_zip_point(gaz):
    assert (gaz.zip_point("21205").lat, gaz.zip_point("21205").lon) == (39.302, -76.578)
    assert gaz.zip_point("20892") is None
    assert gaz.zip_point(None) is None


def test_km():
    balt, dc = Point(39.29, -76.61, "", "", ""), Point(38.90, -77.04, "", "", "")
    assert km(balt, dc) == pytest.approx(56, abs=2)
    assert km(balt, balt) == 0


def test_missing_files_say_where_to_get_them(tmp_path):
    with pytest.raises(FileNotFoundError, match="gazetteer.py"):
        Gazetteer.load(tmp_path, 2026)
