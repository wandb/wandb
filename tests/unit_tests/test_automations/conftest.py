from pytest import mark

pytestmark = [
    mark.wandb_core_only,  # Nothing here makes live requests, avoid testing twice
]
