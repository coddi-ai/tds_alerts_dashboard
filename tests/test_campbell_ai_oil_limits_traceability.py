"""Acceptance cases AC10-AC12: which reference an essay was compared against, and whose taxonomy.

Covers the three things C06 asked for: identical classification in chat and dashboard, an
approximated band that says it is approximated, and four taxonomies that stay separate.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from dashboard.components.oil_charts import (
    classify_four_limit_value,
    get_essay_limits_four,
)
from src.campbell_ai.data import PREDICTIVE_BANDS, DashboardDataRepository, predictive_band
from src.campbell_ai.oil_limits import (
    FOUR_LIMIT_ESSAY_STATES,
    LIMIT_BASIS_ALL,
    LIMIT_BASIS_AVERAGED,
    LIMIT_BASIS_EXACT,
    LIMIT_BASIS_MISSING,
    classify_four_limit,
    four_limit_reference,
)


def _days_ago(days: int) -> str:
    return (pd.Timestamp.today().normalize() - pd.Timedelta(days=days)).isoformat()


def _repository(tmp_path, *, samples: list[dict], limits: list[dict] | None):
    oil = tmp_path / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame(samples).to_parquet(oil / "classified.parquet", index=False)
    if limits is not None:
        pd.DataFrame(limits).to_parquet(oil / "stewart_limits_four.parquet", index=False)
    return DashboardDataRepository(tmp_path)


def _limit_row(essay: str, hour_range: str, lic, lim, lsm, lsc, *, version: str) -> dict:
    return {
        "client": "CDA",
        "machine": "camion",
        "component": "motor",
        "essay": essay,
        "oilHourRange": hour_range,
        "GroupElement": "Desgaste",
        "min_value": 0.0,
        "LIC": lic,
        "LIM": lim,
        "LSM": lsm,
        "LSC": lsc,
        "sample_count": 12,
        "calculation_date": version,
    }


def _sample(**essays) -> dict:
    row = {
        "unitId": "T_15",
        "sampleNumber": "S-1",
        "componentName": "motor",
        "componentNameNormalized": "motor",
        "machineName": "camion",
        "report_status": "Normal",
        "sampleDate": _days_ago(4),
        "severity_score": 0,
        "oilHourRange": "LT_1000",
        "limit_source": "oil_hour_stratified",
    }
    row.update(essays)
    return row


# ---------------------------------------------------------------------- AC10


@pytest.mark.parametrize(
    "value, expected",
    [
        (9.9, "Inferior Condenatorio"),   # < LIC
        (10.0, "Inferior Marginal"),      # == LIC
        (19.9, "Inferior Marginal"),      # < LIM
        (20.0, "Normal"),                 # == LIM
        (50.0, "Normal"),                 # == LSM
        (50.1, "Superior Marginal"),
        (60.0, "Superior Marginal"),      # == LSC
        (60.1, "Superior Condenatorio"),
    ],
)
def test_ac10_each_boundary_classifies_the_same_in_chat_and_dashboard(value, expected):
    """One sample must not read Normal in the dashboard and Marginal in the chat."""
    assert classify_four_limit(value, 10.0, 20.0, 50.0, 60.0) == expected
    # The dashboard entry point now delegates to the same function, so this is a real
    # guarantee rather than two copies that happen to agree today.
    assert classify_four_limit_value(value, 10.0, 20.0, 50.0, 60.0) == expected


def test_ac10_a_missing_lower_limit_is_never_a_lower_limit_of_zero():
    """Wear metals and additives have no LIC/LIM, and a low reading is then just Normal."""
    assert classify_four_limit(0.0, None, None, 50.0, 60.0) == "Normal"
    # Asymmetric nulls do not enable the lower side either.
    assert classify_four_limit(1.0, 10.0, None, 50.0, 60.0) == "Normal"
    assert classify_four_limit(1.0, None, 20.0, 50.0, 60.0) == "Normal"


def test_ac10_the_reference_travels_with_the_result(tmp_path):
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0)],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is True
    reference = payload["references"][0]
    assert reference["essay"] == "Hierro"
    assert reference["basis"] == LIMIT_BASIS_EXACT
    assert (reference["LSM"], reference["LSC"]) == (50.0, 60.0)
    assert reference["measured_value"] == 55.0
    assert reference["classification"] == "Superior Marginal"
    # Version in service, so an answer can be reproduced against the same calibration.
    assert payload["limit_versions"] == ["2026-08-05T11:00:00"]
    assert payload["essays_with_approximated_reference"] == 0
    # Provenance is reported without exposing a filesystem path.
    assert "stewart" not in json.dumps(payload)
    assert "golden" not in json.dumps(payload)


# ---------------------------------------------------------------------- AC11


def test_ac11_an_averaged_band_says_it_is_an_approximation(tmp_path):
    """The sample's oil-hour range has no calibration, so the band is averaged."""
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0, oilHourRange="GE_5000")],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 40.0, 50.0, version="2026-08-05T11:00:00"),
            _limit_row("Hierro", "GE_1000", None, None, 60.0, 70.0, version="2026-08-05T11:00:00"),
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    reference = payload["references"][0]
    assert reference["basis"] == LIMIT_BASIS_AVERAGED
    assert "APROXIMADA" in reference["basis_detail"]
    assert (reference["LSM"], reference["LSC"]) == (50.0, 60.0)  # avg(40,60), avg(50,70)
    assert payload["essays_with_approximated_reference"] == 1


def test_ac11_the_all_range_is_used_before_averaging():
    limits = {
        "Hierro": {
            "ALL": {"LIC": None, "LIM": None, "LSM": 45.0, "LSC": 55.0},
            "LT_1000": {"LIC": None, "LIM": None, "LSM": 40.0, "LSC": 50.0},
        }
    }

    thresholds, basis, provenance = four_limit_reference(limits, "Hierro", "GE_9000")

    assert basis == LIMIT_BASIS_ALL
    assert thresholds["LSM"] == 45.0
    assert provenance["source_ranges"] == ["ALL"]


def test_ac11_averaging_skips_null_lower_limits_instead_of_averaging_them_as_zero():
    limits = {
        "Calcio": {
            "LT_1000": {"LIC": 1000.0, "LIM": 1200.0, "LSM": 1800.0, "LSC": 1900.0},
            "GE_1000": {"LIC": None, "LIM": None, "LSM": 1200.0, "LSC": 1300.0},
        }
    }

    thresholds, basis, provenance = four_limit_reference(limits, "Calcio", "UNKNOWN")

    assert basis == LIMIT_BASIS_AVERAGED
    assert thresholds["LIC"] == 1000.0  # the single calibrated bucket, not avg(1000, 0)
    assert thresholds["LSM"] == 1500.0
    # Per field, so it is visible that only one bucket carried a lower limit.
    assert provenance["averaged_from"]["LIC"] == ["LT_1000"]
    assert provenance["averaged_from"]["LSM"] == ["GE_1000", "LT_1000"]


def test_ac11_a_band_without_an_upper_marginal_limit_is_no_band_at_all():
    """Nothing can be classified without LSM, so None is the honest answer."""
    limits = {"Hierro": {"LT_1000": {"LIC": None, "LIM": None, "LSM": None, "LSC": None}}}

    thresholds, basis, provenance = four_limit_reference(limits, "Hierro", "UNKNOWN")

    assert thresholds is None
    assert basis == LIMIT_BASIS_MISSING
    assert provenance == {}
    # The dashboard entry point agrees, because it is the same function.
    assert get_essay_limits_four(limits, "Hierro", "UNKNOWN") is None


def test_ac11_a_client_without_calibration_is_told_so(tmp_path):
    repository = _repository(tmp_path, samples=[_sample(Hierro=55.0)], limits=None)

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is False
    assert "falta de calibracion" in payload["detail"].lower()
    # No band means no claim about being in or out of limit.
    assert "references" not in payload


def test_ac11_a_refreshed_calibration_is_picked_up_by_version(tmp_path):
    """The cache is keyed by file generation, so replacing the file changes the answer."""
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0)],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )
    first = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    path = tmp_path / "oil" / "golden" / "cda" / "stewart_limits_four.parquet"
    pd.DataFrame(
        [
            _limit_row(
                "Hierro", "LT_1000", None, None, 80.0, 90.0, version="2026-09-01T09:00:00"
            )
        ]
    ).to_parquet(path, index=False)
    second = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert first["references"][0]["classification"] == "Superior Marginal"
    assert first["limit_versions"] == ["2026-08-05T11:00:00"]
    # Same reading, current calibration: no longer out of the marginal limit.
    assert second["references"][0]["classification"] == "Normal"
    assert second["limit_versions"] == ["2026-09-01T09:00:00"]


def test_a_unit_with_several_sampled_components_asks_which_one(tmp_path):
    """Limits are per component; mixing two in one table misattributes a reference."""
    transmission = _sample(Hierro=20.0)
    transmission.update(
        {
            "componentName": "transmision",
            "componentNameNormalized": "transmision",
            "sampleNumber": "S-2",
        }
    )
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0), transmission],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is False
    assert sorted(payload["components_found"]) == ["motor", "transmision"]
    assert "por componente" in payload["detail"]


# ---------------------------------------------------------------------- AC12


def test_ac12_the_four_taxonomies_stay_separate(tmp_path):
    """Essay state, component state, machine state and predictive band are four vocabularies."""
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0)],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))
    components = json.loads(repository.query_oil_components("CDA"))

    # Five essay states, and "Critico" is not one of them.
    assert list(payload["classification_states"]) == list(FOUR_LIMIT_ESSAY_STATES)
    assert "Critico" not in payload["classification_states"]
    # The component keeps its own three-value vocabulary.
    assert components["records"][0]["report_status"] in {"Normal", "Alerta", "Anormal"}


def test_ac12_removing_critico_from_oil_does_not_touch_the_predictive_band():
    """D02 is pending and is per domain: the predictive band legitimately has "Critico"."""
    band_labels = {label for _, label in PREDICTIVE_BANDS}

    assert "Critico" in band_labels
    assert predictive_band(90.0) == "Critico"
    # And that label is not part of the oil essay taxonomy.
    assert "Critico" not in FOUR_LIMIT_ESSAY_STATES


# ------------------------------------------- H03: canonical identity for limits


def test_h03_a_spelling_difference_does_not_look_like_a_missing_calibration(tmp_path):
    """The sample side folds whitespace and case; the limits lookup used the raw text.

    ENEX stores components both as "bastidor izquierdo" and "bastidor izquierdo ". With the
    raw key, the second spelling reported "no calibration" for bands that were right there.
    """
    spaced = _sample(Hierro=55.0)
    spaced.update({"componentName": "motor ", "componentNameNormalized": "motor "})
    repository = _repository(
        tmp_path,
        samples=[spaced],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is True
    assert payload["component_resolution"]["component_match"] == "canonical"
    assert payload["component_resolution"]["component_resolved"] == "motor"
    assert payload["references"][0]["classification"] == "Superior Marginal"


def test_h03_an_uppercase_machine_family_still_resolves(tmp_path):
    upper = _sample(Hierro=20.0)
    upper["machineName"] = "CAMION"
    repository = _repository(
        tmp_path,
        samples=[upper],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is True
    assert payload["component_resolution"]["machine_match"] == "canonical"


def test_h03_distinct_positions_are_never_merged(tmp_path):
    """Folding case and space must not join left and right, which are different positions."""
    from src.campbell_ai.oil_entities import resolve_catalog_key

    mapping = {"bastidor izquierdo": {}, "bastidor derecho": {}}

    assert resolve_catalog_key(mapping, "bastidor izquierdo ")[0] == "bastidor izquierdo"
    assert resolve_catalog_key(mapping, "bastidor derecho")[0] == "bastidor derecho"
    assert resolve_catalog_key(mapping, "mando final") == (None, "missing")


def test_h03_two_keys_that_fold_together_are_reported_as_ambiguous(tmp_path):
    """Picking one of them would attribute a reference to a position by guesswork."""
    from src.campbell_ai.oil_entities import resolve_catalog_key

    mapping = {"motor": {"a": 1}, "Motor ": {"b": 2}}

    key, status = resolve_catalog_key(mapping, "MOTOR")

    assert key is None
    assert status == "ambiguous"


def test_a01_a_collision_is_detected_even_when_one_spelling_matches_exactly(tmp_path):
    """A01, decided: a contradictory source is refused rather than resolved by spelling.

    Two stored keys that fold to the same identity are, by this contract, the same physical
    component. If they carry different bands the source contradicts itself, and letting an
    exact match win would make the reference depend on whether the sample happened to be
    written with a trailing space.
    """
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0)],   # component "motor", spelled exactly as a key
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00"),
            {
                **_limit_row(
                    "Hierro", "LT_1000", None, None, 70.0, 80.0, version="2026-08-05T11:00:00"
                ),
                "component": "Motor ",
            },
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is False
    assert payload["component_resolution"]["component_match"] == "ambiguous"
    assert "problema de la fuente" in payload["detail"]


def test_a01_the_same_bands_under_two_spellings_are_a_duplicate_not_a_contradiction(tmp_path):
    """Nothing to choose between them, so the answer is given and the defect is reported."""
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=55.0)],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00"),
            {
                **_limit_row(
                    "Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00"
                ),
                "component": "Motor ",
            },
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is True
    assert payload["component_resolution"]["component_match"] == "canonical_duplicate"
    assert payload["references"][0]["LSM"] == 50.0
    assert "conviene corregir la fuente" in payload["source_warning"]


def test_a01_the_policy_is_the_same_whichever_spelling_is_asked_for():
    """The point of deciding this: the answer must not depend on a stray space."""
    from src.campbell_ai.oil_entities import resolve_catalog_key

    contradictory = {"motor": {"a": 1}, "MOTOR ": {"a": 2}}
    for spelling in ("motor", "MOTOR ", " Motor", "MoToR"):
        assert resolve_catalog_key(contradictory, spelling) == (None, "ambiguous"), spelling

    # And with no collision, the ordinary paths are untouched.
    clean = {"motor": {"a": 1}, "transmision": {"b": 2}}
    assert resolve_catalog_key(clean, "motor") == ("motor", "exact")
    assert resolve_catalog_key(clean, "MOTOR ") == ("motor", "canonical")
    assert resolve_catalog_key(clean, "mando final") == (None, "missing")


def test_a01_no_calibration_in_service_has_a_collision():
    """The decision is about a hypothetical defect, not about current behaviour.

    Skipped where the calibration files are not present, because an empty check would be
    worse than an honest skip.
    """
    from pathlib import Path

    import pandas as pd

    from src.campbell_ai.oil_entities import canonical_name

    checked = 0
    for path in sorted(Path("data/oil/golden").glob("*/stewart_limits_four.parquet")):
        frame = pd.read_parquet(path)
        if frame.empty:
            continue
        checked += 1
        for column in ("machine", "component"):
            folded: dict[str, set[str]] = {}
            for value in frame[column].astype(str).unique():
                folded.setdefault(canonical_name(value), set()).add(value)
            collisions = {key: names for key, names in folded.items() if len(names) > 1}
            assert not collisions, (path.parent.name, column, collisions)
    if not checked:
        pytest.skip("sin archivos de calibracion presentes")


def test_h03_an_ambiguous_source_is_not_reported_as_missing_calibration(tmp_path):
    """No exact key, and two that fold together: choosing one would be a guess."""
    other_spelling = _sample(Hierro=55.0)
    other_spelling.update(
        {"componentName": "MOTOR", "componentNameNormalized": "MOTOR"}
    )
    repository = _repository(
        tmp_path,
        samples=[other_spelling],
        limits=[
            {
                **_limit_row(
                    "Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00"
                ),
                "component": "motor",
            },
            {
                **_limit_row(
                    "Hierro", "LT_1000", None, None, 70.0, 80.0, version="2026-08-05T11:00:00"
                ),
                "component": "Motor ",
            },
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))

    assert payload["limits_available"] is False
    assert payload["component_resolution"]["component_match"] == "ambiguous"
    # A source problem, and the wording says outright it is not an absent calibration.
    assert "problema de la fuente" in payload["detail"]
    assert "no como falta de calibracion" in payload["detail"]


# --------------------------------------- H04: provenance of an averaged band


def test_h04_an_averaged_band_carries_its_source_ranges_and_versions(tmp_path):
    """An approximation with no traceable origin cannot be audited or reproduced."""
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=18.0, oilHourRange="GE_9000")],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 10.0, 20.0, version="2026-08-01T00:00:00"),
            _limit_row("Hierro", "GE_1000", None, None, 20.0, 30.0, version="2026-08-02T00:00:00"),
        ],
    )

    payload = json.loads(repository.describe_oil_limits("CDA", unit_id="T_15"))
    reference = payload["references"][0]

    assert reference["basis"] == LIMIT_BASIS_AVERAGED
    assert (reference["LSM"], reference["LSC"]) == (15.0, 25.0)
    assert reference["source_ranges"] == ["GE_1000", "LT_1000"]
    # Two calibration dates went into it, so no single one may be cited.
    assert reference["limit_versions"] == ["2026-08-01T00:00:00", "2026-08-02T00:00:00"]
    assert reference["mixed_versions"] is True
    assert "limit_version" not in reference
    assert payload["note"].count("mixed_versions") == 1


def test_h04_a_single_version_is_still_reported_as_one(tmp_path):
    """Averaging bands calculated on the same day has one version, not a mixture."""
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=18.0, oilHourRange="GE_9000")],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 10.0, 20.0, version="2026-08-01T00:00:00"),
            _limit_row("Hierro", "GE_1000", None, None, 20.0, 30.0, version="2026-08-01T00:00:00"),
        ],
    )

    reference = json.loads(
        repository.describe_oil_limits("CDA", unit_id="T_15")
    )["references"][0]

    assert reference["limit_version"] == "2026-08-01T00:00:00"
    assert "mixed_versions" not in reference
    assert reference["source_ranges"] == ["GE_1000", "LT_1000"]


def test_h04_an_exact_band_reports_its_own_range_and_version(tmp_path):
    repository = _repository(
        tmp_path,
        samples=[_sample(Hierro=18.0)],
        limits=[
            _limit_row("Hierro", "LT_1000", None, None, 50.0, 60.0, version="2026-08-05T11:00:00")
        ],
    )

    reference = json.loads(
        repository.describe_oil_limits("CDA", unit_id="T_15")
    )["references"][0]

    assert reference["source_ranges"] == ["LT_1000"]
    assert reference["limit_version"] == "2026-08-05T11:00:00"
    assert "averaged_from" not in reference
