from cloud_api import RunRequest, POIKATSU_DEMO_HTML

def test_poikatsu_mode_request_is_accepted():
    request = RunRequest(mode="poikatsu_demo", goal="safe survey dry run")
    assert request.mode == "poikatsu_demo"

def test_poikatsu_demo_has_three_questions_and_no_submit():
    assert 'name="q1"' in POIKATSU_DEMO_HTML
    assert 'name="q2"' in POIKATSU_DEMO_HTML
    assert 'name="q3"' in POIKATSU_DEMO_HTML
    assert 'type="submit"' not in POIKATSU_DEMO_HTML
