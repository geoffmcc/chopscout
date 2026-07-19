from chopscout.models import deterministic_project_name


def test_project_name():
    assert deterministic_project_name("My Break!.wav", 171.6) == "My_Break_172"


def test_tempo_hypothesis_is_a_reserved_ranked_candidate_model():
    from chopscout.models import TempoHypothesis

    hypothesis = TempoHypothesis(bpm=172.0, confidence=0.8)
    assert hypothesis.bpm == 172.0
    assert hypothesis.confidence == 0.8
    assert hypothesis.label == "main"


def test_export_settings_has_no_unimplemented_fields():
    from dataclasses import fields

    from chopscout.models import ExportSettings

    names = {item.name for item in fields(ExportSettings)}
    assert "trim_silence" not in names
