from pathlib import Path

from pytest import fixture

from wandb.sdk.automations.legacy import LegacyAutomation, LegacyAutomationAdapter

HERE = Path(__file__).parent


def read_records() -> list[LegacyAutomation]:
    # with (HERE / "bq-results-20240825-031207-1724555549715.jsonl").open() as f:
    with (HERE / "user_triggers.sample.jsonl").open() as f:
        records = [
            LegacyAutomationAdapter.validate_json(jsonline)
            # AutomationLegacy.model_validate_json(jsonline)
            for line in f
            if (jsonline := line.strip())
        ]
    return records


@fixture
def sample_rows() -> list[LegacyAutomation]:
    records = read_records()
    return records


def test_legacy_automations(sample_rows):
    for record in sample_rows:
        print(
            record.triggering_condition_type,
            record.triggering_condition_config.payload,
        )
