import json

import wandb


def get_table_from_summary(run, summary: dict, key_path: list[str]) -> wandb.Table:
    table_path = summary
    for key in key_path:
        table_path = table_path[key]
    table_path = table_path["path"]
    table_path = f"{run.dir}/{table_path}"
    table_json = json.load(open(table_path))
    return wandb.Table(data=table_json["data"], columns=table_json["columns"])


def test_log_nested_plot(wandb_init, wandb_backend_spy):
    with wandb_init() as run:
        plot1 = wandb.plot.line_series(
            xs=[0, 1, 2, 3, 4],
            ys=[[123, 333, 111, 42, 533]],
            keys=["metric_A"],
        )
        plot2 = wandb.plot.line_series(
            xs=[4, 3, 2, 1, 0],
            ys=[[10, 20, 30, 40, 50]],
            keys=["metric_B"],
        )

        run.log(
            {
                "layer1": {
                    "layer2": {"layer3": plot1},
                    "layer4": {"layer5": plot2},
                }
            }
        )
        run.finish()

        with wandb_backend_spy.freeze() as snapshot:
            summary = snapshot.summary(run_id=run.id)

            # Verify the table was set in the config and summary
            assert "layer3_table" in summary["layer1"]["layer2"]
            assert "layer5_table" in summary["layer1"]["layer4"]

            for plot, key_path in [
                (plot1, ["layer1", "layer2", "layer3_table"]),
                (plot2, ["layer1", "layer4", "layer5_table"]),
            ]:
                table = get_table_from_summary(run, summary, key_path)
                assert table == plot.table


def test_log_nested_table(wandb_init, wandb_backend_spy):
    with wandb_init() as run:
        table1 = wandb.Table(columns=["a"], data=[[1]])
        table2 = wandb.Table(columns=["b"], data=[[2]])
        run.log(
            {
                "layer1": {
                    "layer2": {"layer3": table1},
                    "layer4": {"layer5": table2},
                }
            }
        )
        run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)

        assert "layer3" in summary["layer1"]["layer2"]
        assert "layer5" in summary["layer1"]["layer4"]

        for table, key_path in [
            (table1, ["layer1", "layer2", "layer3"]),
            (table2, ["layer1", "layer4", "layer5"]),
        ]:
            table = get_table_from_summary(run, summary, key_path)
            assert table == table


def test_log_nested_visualize(wandb_init, wandb_backend_spy):
    with wandb_init() as run:
        table1 = wandb.Table(columns=["a"], data=[[1]])
        table2 = wandb.Table(columns=["b"], data=[[2]])

        visualize1 = wandb.visualize(
            "wandb/confusion_matrix/v1",
            table1,
        )
        visualize2 = wandb.visualize(
            "wandb/confusion_matrix/v1",
            table2,
        )
        run.log(
            {
                "layer1": {
                    "layer2": {"layer3": visualize1},
                    "layer4": {"layer5": visualize2},
                }
            }
        )
        run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)

        assert "layer3" in summary["layer1"]["layer2"]
        assert "layer5" in summary["layer1"]["layer4"]

        for visualize, key_path in [
            (visualize1, ["layer1", "layer2", "layer3"]),
            (visualize2, ["layer1", "layer4", "layer5"]),
        ]:
            table = get_table_from_summary(run, summary, key_path)
            assert table == visualize.table
