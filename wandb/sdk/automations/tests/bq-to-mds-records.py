from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent

bq_results_filepath = HERE / "bq-results-20240825-031207-1724555549715.jsonl"

bq2mds_colnames = {
    "user_trigger_id": "id",
    # "created_at",
    "created_by_user_id": "created_by",
    "user_trigger_name": "name",
    "user_trigger_description": "description",
    # "scope_type",
    # "scope_id",
    # "triggering_condition_type",
    # "triggering_condition_config",
    # "triggered_action_config",
    # "scope_project_id",
    "is_enabled": "enabled",
    # "triggering_event_type",  # TODO: is this redundant w/triggering_condition_type?
    # "triggered_action_type",  # TODO: is this contained inside triggered_action_config?
    # "webhook_id",
    # "target_queue_id",
    # "scope_artifact_collection_id",
}

expected_mds_colnames = [
    "id",
    "created_at",
    "updated_at",
    "created_by",
    "target_queue_id",
    "name",
    "description",
    "scope_type",
    "scope_id",
    "triggering_condition_type",
    "triggering_condition_config",
    "triggered_action_config",
    "scope_entity_id",
    "scope_project_id",
    "scope_artifact_collection_id",
    "enabled",
]

df = (
    pd.read_json(
        bq_results_filepath,
        lines=True,
        convert_axes=False,
        convert_dates=False,
        dtype=False,
    )
    .rename(columns=bq2mds_colnames)
    .filter(expected_mds_colnames)
    .to_json(
        bq_results_filepath.parent / "user_triggers.sample.jsonl",
        orient="records",
        lines=True,
    )
)
