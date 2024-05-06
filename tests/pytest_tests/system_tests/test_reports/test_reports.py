import wandb.apis.reports.v2 as wr


def test_load_report_from_url(user):
    created_report = wr.Report(
        project="test",
        blocks=[wr.H1("Heading"), wr.P("Text")],
    ).save()
    loaded_report = wr.Report.from_url(created_report.url)

    attrs = [
        "id",
        "blocks",
        "_discussion_threads",
        "_panel_settings",
        "_ref",
        "_authors",
    ]
    for attr in attrs:
        assert getattr(created_report, attr) == getattr(loaded_report, attr)
