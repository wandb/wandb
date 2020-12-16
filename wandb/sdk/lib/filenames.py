#
CONFIG_FNAME = "config.yaml"
OUTPUT_FNAME = "output.log"
DIFF_FNAME = "diff.patch"
SUMMARY_FNAME = "wandb-summary.json"
METADATA_FNAME = "wandb-metadata.json"
REQUIREMENTS_FNAME = "requirements.txt"
HISTORY_FNAME = "wandb-history.jsonl"
EVENTS_FNAME = "wandb-events.jsonl"
JOBSPEC_FNAME = "wandb-jobspec.json"


def is_wandb_file(name):
    return (
        name.startswith("wandb")
        or name == METADATA_FNAME
        or name == CONFIG_FNAME
        or name == REQUIREMENTS_FNAME
        or name == OUTPUT_FNAME
        or name == DIFF_FNAME
    )
