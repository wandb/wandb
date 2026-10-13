PTH_NAME = "wandb_provenance_bootstrap.pth"
PTH_LINE = (
    'import os; os.getenv("WANDB_X_PROVENANCE_LEVEL") in ("0", "1") and '
    '__import__("wandb.sdk.provenance.bootstrap", fromlist=["install"]).install()\n'
)
