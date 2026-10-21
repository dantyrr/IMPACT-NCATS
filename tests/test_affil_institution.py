import pytest
from src.ncats.affil_institution import describe, institution_type, institution_key


def _inst(text):
    parts = [p for p in describe(text) if p.institution]
    return (parts[-1].institution.key, parts[-1].institution.type) if parts else None


@pytest.mark.parametrize("text, key, kind", [
    ("Centre for Cancer Genetic Epidemiology, Department of Public Health and Primary Care, "
     "University of Cambridge, Cambridge, UK.", "university of cambridge", "university"),
    ("Department of Psychiatry, University of Maryland School of Medicine, Baltimore, Maryland.",
     "university of maryland baltimore", "university"),
    ("Department of Medicine, University of Maryland, Baltimore, MD, USA.",
     "university of maryland baltimore", "university"),
    ("Molecular and Cell Biology, University of California, Berkeley, Berkeley, CA.",
     "university of california berkeley", "university"),
    ("Institute of Cardiovascular Science, University College London, London, UK.",
     "university college london", "university"),
    ("Department of Medicine, Section of Hepatology, Rush University Medical Center, Chicago, IL, USA.",
     "rush university medical center", "hospital"),
    ("Department of Emergency Medicine, Hennepin County Medical Center, Minneapolis, Minnesota.",
     "hennepin county medical center", "hospital"),
    ("Kaiser Permanente Southern California, 100 S. Los Robles, Pasadena, CA, 91101, USA.",
     "kaiser permanente southern california", "hospital"),
    ("Department of Oncology, St. Jude Children's Research Hospital, Memphis, TN, USA.",
     "st jude children s research hospital", "hospital"),
    ("Division of Viral Diseases, Centers for Disease Control and Prevention, Atlanta, Georgia.",
     "centers for disease control and prevention", "government"),
    ("NIAID Clinical Genomics Program, NIH, Bethesda, MD, USA.", "national institutes of health", "government"),
    ("2 National Heart, Lung, and Blood Institute, Bethesda, Maryland.",
     "national heart lung and blood institute", "government"),
    ("VA Boston Healthcare System, Boston, MA, USA.", "va boston healthcare system", "government"),
    ("Physics Department, Brookhaven National Laboratory, Upton, NY USA.",
     "brookhaven national laboratory", "government"),
    ("Electrical Circuits Department, Federal University of Juiz de Fora (UFJF), Juiz de Fora, Brazil.",
     "federal university of juiz de fora", "university"),
    ("Eli Lilly and Company, Indianapolis, IN, USA.", "eli lilly", "industry"),
    ("Novo Nordisk A/S, Søborg, Denmark.", "novo nordisk", "industry"),
    ("Pfizer, Inc., New York, NY, USA.", "pfizer", "industry"),
    ("Real World Solutions, IQVIA, Durham, NC, USA.", "iqvia", "industry"),
    ("Regeneron Genetics Center, Tarrytown, NY, USA.", "regeneron genetics center", "industry"),
    ("Broad Institute of MIT and Harvard, Cambridge, MA 02142, USA.", "broad institute", "other"),
    ("Icelandic Heart Association, Kopavogur, Iceland.", "icelandic heart association", "other"),
])
def test_institution_name_and_type(text, key, kind):
    assert _inst(text) == (key, kind)


@pytest.mark.parametrize("text", [
    "Department of Medicine.",
    "Department of Medicine and.",
    "Division of Allergy, Pulmonary, and Critical Care Medicine, Department of Medicine.",
    "Departments of Pediatrics.",
    "Toronto, ON, Canada.",
])
def test_stub_affiliations_name_no_institution(text):
    assert _inst(text) is None


def test_placeholders_are_not_affiliations():
    assert describe("Authors' affiliations are listed at the end of the article.") == []
    assert describe("Due to the number of contributing authors, the affiliations are provided "
                    "in the Supplemental Material.") == []


def test_describe_keeps_each_semicolon_part():
    parts = describe("Dept A, Duke University, Durham, NC, USA; Dept B, University of Oxford, Oxford, UK")
    assert [(p.location.country, p.institution.key) for p in parts] == [
        ("USA", "duke university"), ("United Kingdom", "university of oxford")]
    assert all(p.informative for p in parts)


@pytest.mark.parametrize("name, kind", [
    ("National Institute of Mental Health", "government"),
    ("U.S. Food and Drug Administration", "government"),
    ("Walter Reed National Military Medical Center", "government"),
    ("Michael E. DeBakey VA Medical Center", "government"),
    ("Cleveland Clinic", "hospital"),
    ("Jefferson Health", "hospital"),
    ("Genentech, Inc.", "industry"),
    ("Harvard T.H. Chan School of Public Health", "university"),
    ("Karolinska Institutet", "university"),
    ("Los Angeles County Department of Public Health", "government"),
    ("Salk Institute for Biological Studies", "other"),
    ("Helmholtz Zentrum München-German Research Center for Environmental Health", "other"),
    ("Intermountain Healthcare", "hospital"),
])
def test_institution_type(name, kind):
    assert institution_type(name) == kind


def test_institution_key_groups_spellings():
    assert institution_key("The University of Iowa") == "university of iowa"
    assert institution_key("Saint Louis University School of Medicine") == "saint louis university"
    assert institution_key("Eli Lilly & Co.") == "eli lilly"
    assert institution_key("INSERM U1163") == "inserm"
    assert institution_key("US Centers for Disease Control and Prevention") == \
        "centers for disease control and prevention"
    assert institution_key("University of Texas", "Austin") == "university of texas austin"
    assert institution_key("University of Cambridge", "Cambridge") == "university of cambridge"


def test_a_trailing_and_is_not_part_of_the_name():
    parts = describe("Baker Institute for Animal Health, and.")
    assert parts[0].institution.name == "Baker Institute for Animal Health"
