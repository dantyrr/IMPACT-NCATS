from pathlib import Path
from scripts.upload_to_r2 import build_key


def test_key_is_always_prefixed():
    """The bucket is shared with IMPACT; an unprefixed index.json would
    overwrite IMPACT's live production data."""
    data_dir = Path("/x/docs/data")
    assert build_key(data_dir / "index.json", data_dir, "ncats") == "ncats/index.json"


def test_nested_paths_keep_their_structure_under_the_prefix():
    data_dir = Path("/x/docs/data")
    key = build_key(data_dir / "sites" / "yale-university.json", data_dir, "ncats")
    assert key == "ncats/sites/yale-university.json"


def test_no_key_collides_with_impacts_own_layout():
    """IMPACT stores index.json and journals/*.json at the bucket root."""
    data_dir = Path("/x/docs/data")
    for rel in ["index.json", "sites/a.json", "investigators/1.json"]:
        key = build_key(data_dir / rel, data_dir, "ncats")
        assert key.startswith("ncats/")
        assert not key.startswith("index.json")
        assert not key.startswith("journals/")
