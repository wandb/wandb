import json


def add_wandb_visualization(run, mlpipeline_ui_metadata_path):
    """NOTE: To use this, you must modify your component to have an output called `mlpipeline_ui_metadata_path` AND call `wandb.init` yourself inside that component.

    Example usage:

    def my_component(..., mlpipeline_ui_metadata_path: OutputPath()):
        import wandb
        from wandb.integration.kfp.helpers import add_wandb_visualization

        with wandb.init() as run:
            add_wandb_visualization(run, mlpipeline_ui_metadata_path)

            ... # the rest of your code here
    """

    def get_iframe_html(run):
        return f'<iframe src="{run.url}?kfp=true" style="border:none;width:100%;height:100%;min-width:900px;min-height:600px;"></iframe>'

    iframe_html = get_iframe_html(run)
    metadata = {
        "outputs": [{"type": "markdown", "storage": "inline", "source": iframe_html}]
    }

    with open(mlpipeline_ui_metadata_path, "w") as metadata_file:
        json.dump(metadata, metadata_file)
