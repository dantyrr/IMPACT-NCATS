# Methods and Limitations

How IMPACT-NCATS builds its numbers, and — just as importantly — what those numbers do not
mean. Read this before quoting any figure from this project.

## How grants become publications

1. Every NCATS award FY2012–present is pulled from the NIH RePORTER v2 projects API,
   including all activity codes (R, K, U, T, F, P, SBIR).
2. Awards are grouped by **core project number**, which collapses each competitive segment's
   yearly records into one grant. Dollar totals sum the per-fiscal-year `award_amount`.
3. Publications come from RePORTER's own publications endpoint, which maps
   `core_project_num → PMID`.
4. Those PMIDs are joined against `impact.db` to pick up journal, publication year, article
   type, and citation counts. RCR comes from iCite.

## Site definition

A site is keyed on RePORTER's `org_ipf_code`, a stable institutional identifier. This
matters: most CTSA hubs are renewed under a **new core project number** (for example
`UL1TR000090` → `UL1TR001070` at the same institution), so keying on core project number
would split a single continuous hub into several apparent sites.

The reverse problem also occurs, less often: an institution may re-register with NIH under a
new IPF code. Albert Einstein College of Medicine, for instance, holds three IPF codes across
2012–2026. These are merged through the curated `data/ipf_aliases.json`. Any addition to that
file should be verified by hand — same institution, contiguous funding, same city and state.

Every NCATS award at a hub's IPF rolls up to that site. Awards at organizations that never
held a UL1/UM1 are retained but flagged `is_ctsa_hub = 0`, so NCATS-wide questions remain
answerable.

## Limitations

**1. Linkage depends on authors citing their grant.** RePORTER knows about a publication only
if it was reported or tagged to the award. Papers that omitted the grant number are invisible
here. **Every publication count in this project is a floor, not a census.** Hubs also differ
in how diligently they report, so cross-hub comparisons partly measure reporting practice
rather than productivity alone.

**2. FY2012 floor.** NCATS was created in December 2011. The CTSA program itself began in
2006 under NCRR (`UL1RR*`), and those years are excluded by scope. A hub funded since 2006
will appear to start in 2012. **Do not read the left edge of any trend line as program
inception.**

**3. Investigator attribution is grant-linkage only.** An investigator's publications are the
papers linked to grants they hold — no author-name matching is performed. This is
reproducible and produces no false positives from name collisions, but it has two
consequences: a hub's contact PI is credited with the hub's entire linked output regardless
of personal involvement, and any work the investigator published outside their NCATS award is
absent.

**4. Shared publications receive full credit at every hub.** A multi-site paper linked to
grants at three hubs counts once in each hub's totals, and carries `n_linked_hubs = 3`.
**Per-site totals therefore sum to more than the true unique publication count.**
Consortium-wide figures de-duplicate on PMID. Neither number is wrong; they answer different
questions, and mixing them produces nonsense.

**5. Roughly 4% of linked PMIDs are absent from `impact.db`.** These are typically papers in
journals outside PubMed indexing or outside the 2003–2026 window. They are counted in
publication totals but excluded from journal and citation metrics. The pipeline asserts a
≥95% match rate and fails validation below that.

**6. RCR is undefined for recent papers.** iCite needs citation history, so papers from the
last year or two carry a null RCR and are omitted from mean-RCR figures. Recent years will
look thinner on this metric than they truly are.

**7. Cost-per-publication is a blunt instrument.** It divides award dollars by linked
publications in the same fiscal year and mechanism. Publications lag funding by years,
infrastructure awards (UL1/UM1) fund cores and services rather than papers directly, and
training awards produce output under trainees' own later grants. **A high cost-per-publication
is not evidence of waste**, particularly for hub and training mechanisms.

## Reproducibility

All code is open source and every script is idempotent. The full pipeline runs from public
APIs plus `impact.db`, itself built from the PubMed baseline and the iCite Open Citation
Collection. No proprietary or licensed data is involved.
