"""Paper-level flags shared by the dashboard exports.

COVID-19 papers are flagged from their own text (title, abstract, MeSH
terms), not from the year, so the dashboards can show them, leave them out,
or show only them, without removing anything from the data. Large author
lists (100 or more) are flagged because one consortium paper can name
hundreds of institutions and dominate collaboration counts.
"""

import re

COVID_RX = re.compile(
    r"covid|sars-cov-2|sars cov 2|severe acute respiratory syndrome coronavirus 2"
    r"|coronavirus disease 2019|2019-ncov|\bn3c\b", re.IGNORECASE)
BIG_AUTHOR_LIST = 100


def is_covid(*texts):
    """Whether any of the texts names COVID-19 or SARS-CoV-2."""
    return any(t and COVID_RX.search(t) for t in texts)


def covid_pmids(conn):
    """PMIDs whose title, abstract or MeSH terms name COVID-19 or SARS-CoV-2."""
    return {pmid for pmid, title, abstract, mesh in conn.execute("""
                SELECT pm.pmid, pm.title, pt.abstract, pt.mesh_terms
                FROM pub_metrics pm LEFT JOIN pub_text pt USING(pmid)""")
            if is_covid(title, abstract, mesh)}
