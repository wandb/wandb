import click


@click.group("import", help="Commands for importing data from other systems")
def importer():
    pass


@importer.command("mlflow", help="Import from MLFlow")
@click.option("--mlflow-tracking-uri", help="MLFlow Tracking URI")
@click.option(
    "--target-entity", required=True, help="Override default entity to import data into"
)
@click.option(
    "--target-project",
    required=True,
    help="Override default project to import data into",
)
def mlflow(mlflow_tracking_uri, target_entity, target_project):
    from wandb.apis.importers import MlflowImporter

    importer = MlflowImporter(mlflow_tracking_uri=mlflow_tracking_uri)
    overrides = {
        "entity": target_entity,
        "project": target_project,
    }

    importer.import_all_parallel(overrides=overrides)
