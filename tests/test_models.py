from chopscout.models import deterministic_project_name


def test_project_name():
    assert deterministic_project_name("My Break!.wav", 171.6) == "My_Break_172"
