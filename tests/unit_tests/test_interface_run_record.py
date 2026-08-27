import pytest


@pytest.mark.parametrize(
    ("resume", "expected"),
    [
        ("allow", True),
        ("must", True),
        ("auto", True),
        ("never", False),
        (None, False),
    ],
)
def test_make_run_sets_resume_intent(mock_run, mocked_interface, resume, expected):
    run = mock_run(settings={"resume": resume})

    proto = mocked_interface._make_run(run)

    assert proto.resume is expected
