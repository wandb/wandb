"""
metric user tests.
"""


def test_metric_none(user_test):
    run = user_test.get_run()
    run.log(dict(this=1))
    run.log(dict(that=2))

    r = user_test.get_records()
    assert len(r.records) == 2
    assert len(r.history) == 2
    assert len(r.summary) == 0
