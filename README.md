# IMPACT-NCATS

**Publication impact of the NCATS grant portfolio, by CTSA site, investigator, and grant.**

### 🔗 **Live site: https://dantyrr.github.io/IMPACT-NCATS**

A sibling project to [IMPACT](https://github.com/dantyrr/IMPACT) and
[IMPACT-gender](https://github.com/dantyrr/IMPACT-gender). Where IMPACT measures journals,
IMPACT-NCATS measures **funding** — every award made by NIH's National Center for Advancing
Translational Sciences, and what was published as a result.

| | |
|---|---|
| CTSA sites | 67 |
| NCATS grants | 1,639 · $9.0B awarded |
| Linked publications | 148,720 |
| Matched to journal/citation data | 143,831 (96.7%) |

## What it answers

- How many publications, citations, and what average RCR does each CTSA hub produce?
- How does output differ by mechanism — hub awards (UL1/UM1) vs. training (KL2/TL1) vs.
  research (R01/R21) vs. small business (R43/R44)?
- What does a publication cost, per hub and per mechanism?
- Which investigators hold NCATS awards, and what has that funding produced?

## Data sources

| Source | Provides |
|---|---|
| [NIH RePORTER v2](https://api.reporter.nih.gov/) | Awards FY2012–present: activity code, organization, PIs, dollars |
| RePORTER publications API | `core_project_num` → PMID linkage |
| [iCite](https://icite.od.nih.gov/) | Relative Citation Ratio (RCR) |
| `impact.db` (from IMPACT) | 24.9M papers, citation events, journals, author affiliations |

No API keys are required. `impact.db` is opened **read-only** and never modified.

## Scope

**NCATS only, FY2012 onward, all activity codes.** NCATS was created in December 2011, so
FY2012 is the earliest fiscal year it appears in RePORTER. The CTSA program began in 2006
under NCRR (`UL1RR*` awards); those years are deliberately out of scope. See
[METHODS_ncats.md](METHODS_ncats.md).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env    # then set IMPACT_DB_PATH and R2 credentials
```

## Running the pipeline

```bash
python scripts/fetch_grants.py           # NCATS awards -> grants, sites, investigators
python scripts/build_site_registry.py    # identify CTSA hubs, write ctsa_registry.json
python scripts/fetch_publications.py     # grant -> PMID links (long-running; --resume works)
python scripts/fetch_rcr.py              # iCite RCR for linked PMIDs
python scripts/compute_ncats_metrics.py  # join impact.db, compute metrics
python scripts/export_ncats_json.py      # static JSON -> docs/data/
python scripts/validate_ncats.py         # integrity checks
python scripts/upload_to_r2.py           # sync to Cloudflare R2
```

For collaboration analysis, the full byline of every linked paper (all authors, ORCIDs,
and affiliation strings as written) comes from PubMed EFetch:

```bash
python scripts/fetch_authors.py --resume          # pub_authors, pub_author_affils (~25 min)
python scripts/export_author_affiliations.py      # exports/author_affiliations.csv + coverage by year
```

PubMed recorded only the first author's affiliation before about 2014, so papers from
2012–2013 mostly lack co-author affiliations. That gap is in the source data, not the fetch.

Collaboration between CTSA hubs uses only those PubMed affiliations, NIH RePORTER grant links,
and two curated files: [`data/ctsa_hubs.csv`](data/ctsa_hubs.csv) (the 67 hubs) and
[`data/hub_aliases.csv`](data/hub_aliases.csv) (the names that identify each hub's authors):

```bash
python scripts/match_hub_affiliations.py      # authors -> hubs, from data/hub_aliases.csv
python scripts/build_hub_network.py           # co-authorship and co-funding networks
python scripts/export_hub_matching.py         # hub assignments and matching checks
python scripts/suggest_hub_aliases.py         # names to consider adding to the alias list
```

Collaboration with institutions that are *not* hubs reads the country, US state, ZIP, city and a
rough institution name and type from the same affiliation text. US cities and ZIPs get map points,
and hubs their city centers, from the US Census Bureau Gazetteer: the 2026 place, county-subdivision
and ZCTA files from
`https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/`, unzipped into
`data/gazetteer/2026/{place,cousubs,zcta}/` (gitignored). Without them, everything but the points
and distances is still written.

```bash
python scripts/build_nonhub_collaboration.py  # per-hub outreach: places, distances, institution types
```

Every script is idempotent — re-running never duplicates rows or double-counts dollars.

## Architecture

```
RePORTER ──┐
iCite ─────┼──> data/ncats.db ──> join on PMID ──> docs/data/*.json ──> R2 ──> SPA
           │                          │
impact.db ─┘ (read-only) ─────────────┘
```

`ncats.db` is small (tens of MB) and holds grants, sites, investigators, and grant→PMID
links. All journal, citation, and author data is read from `impact.db` at compute time.

## Site identity

A "site" is keyed on RePORTER's **`org_ipf_code`**, not on the core project number. Most
CTSA hubs are renewed under an entirely new core project number (e.g. `UL1TR000090` →
`UL1TR001070` at the same institution), so core-project keying would split most hubs.

A few institutions also re-register with NIH under a *new* IPF code over time. Those are
merged via the curated [`data/ipf_aliases.json`](data/ipf_aliases.json). A slug collision
raises an error rather than silently overwriting a hub's data.

## Tests

```bash
python -m pytest tests/ -v
```

## License

MIT
