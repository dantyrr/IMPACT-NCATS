"""CTSA hub definitions for collaboration analysis.

The hub list lives in data/ctsa_hubs.csv, one row per hub with a readable
label and the IPF codes of every site that has held that hub's award. It is
curated by hand and checked against the grants table, so a hub can never be
silently missing.

This is stricter than sites.is_ctsa_hub, which flags every site with any UL1 or
UM1. NCATS also uses UM1 for New Approach Methods (NAMs) centers, first awarded
in FY2026 (MIT, Brigham and Women's, Texas A&M AgriLife, Cincinnati
Children's). Those are not CTSA hubs.
"""

import csv

from src.ncats.config import DATA_DIR

HUBS_CSV = DATA_DIR / "ctsa_hubs.csv"

# Career development and training awards made to hubs under the CTSA program.
# KL2/TL1 sat inside the UL1 era; K12/T32 replaced them under the UM1 hubs.
CTSA_TRAINING_CODES = {"KL2", "TL1", "K12", "T32"}

# UM1s that are not CTSA hub awards: the FY2026 New Approach Methods centers.
# Titles cannot separate these reliably (Michigan's hub UM1 is just "MICHR"),
# so they are listed. check_hubs_cover_awards fails on any UM1 that is neither
# a known hub's nor listed here, so a new non-hub UM1 forces a review.
NON_CTSA_UM1 = {
    "UM1TR006029": "MIT, NAMs center",
    "UM1TR006031": "Stanford, NAMs center (site is a hub through its UL1)",
    "UM1TR006046": "Johns Hopkins, NAMs center (site is a hub through its UL1)",
    "UM1TR006047": "Brigham and Women's, NAMs technology development center",
    "UM1TR006055": "Texas A&M AgriLife, NAMs center",
    "UM1TR006070": "Cincinnati Children's, NAMs center",
}


def is_ctsa_hub_award(activity_code, core_project_num):
    if activity_code == "UL1":
        return True
    return activity_code == "UM1" and core_project_num not in NON_CTSA_UM1


def is_ctsa_program_award(activity_code, core_project_num):
    """A hub award or one of the career/training awards that go with it."""
    return (activity_code in CTSA_TRAINING_CODES
            or is_ctsa_hub_award(activity_code, core_project_num))


def load_hubs(path=HUBS_CSV):
    """{hub_id: {label, members, city, state}} from the curated CSV."""
    hubs = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            hub_id = int(row["hub_id"])
            hubs[hub_id] = {
                "label": row["label"],
                "members": [int(x) for x in row["member_ipf_codes"].split(";")],
                "city": row["city"],
                "state": row["state"],
            }
    return hubs


def site_to_hub(hubs):
    out = {}
    for hub_id, h in hubs.items():
        for ipf in h["members"]:
            if ipf in out:
                raise ValueError(f"site {ipf} is listed under hubs {out[ipf]} and {hub_id}")
            out[ipf] = hub_id
    return out


def check_hubs_cover_awards(conn, hubs):
    """Raise if a site holds a CTSA hub award but is not in the hub list."""
    mapped = site_to_hub(hubs)
    missing = sorted({
        ipf for ipf, code, num in conn.execute(
            "SELECT ipf_code, activity_code, core_project_num FROM grants "
            "WHERE activity_code IN ('UL1', 'UM1')")
        if is_ctsa_hub_award(code, num) and ipf not in mapped
    })
    if missing:
        raise ValueError(f"sites with a CTSA hub award missing from {HUBS_CSV.name}: {missing}")
