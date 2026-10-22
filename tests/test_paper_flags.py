import sqlite3

import pytest
from src.ncats.paper_flags import covid_pmids, is_covid
from src.ncats.schema import create_schema


@pytest.mark.parametrize("text, expected", [
    ("Outcomes of COVID-19 in kidney transplant recipients", True),
    ("Neutralizing antibodies to SARS-CoV-2 variants", True),
    ("Severe acute respiratory syndrome coronavirus 2 infection in children", True),
    ("Data from the National COVID Cohort Collaborative (N3C)", True),
    ("Coronavirus Disease 2019", True),
    ("Seasonal coronavirus infections before 2019", False),
    ("SARS-CoV (2003) and MERS", False),
    ("Covalent inhibitors of KRAS", False),
    (None, False),
])
def test_is_covid(text, expected):
    assert is_covid(text) is expected


def test_covid_pmids_reads_title_abstract_and_mesh():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    c.executemany("INSERT INTO pub_metrics (pmid, title) VALUES (?, ?)",
                  [(1, "A trial of remdesivir"), (2, "Asthma in adults"), (3, "Sepsis outcomes"), (4, "Gene editing")])
    c.executemany("INSERT INTO pub_text (pmid, abstract, mesh_terms) VALUES (?, ?, ?)",
                  [(1, "Patients hospitalized with COVID-19.", None), (2, None, '["COVID-19", "Asthma"]'),
                   (3, "Bacterial sepsis.", '["Sepsis"]')])
    assert covid_pmids(c) == {1, 2}
