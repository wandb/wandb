import torch
from diffusers import StableCascadeCombinedPipeline
from wandb.integration.diffusers import autolog

pipeline_log_config = (
    dict(
        api_module="diffusers",
        pipeline=StableCascadeCombinedPipeline,
        kwarg_logging=["prompt", "negative_prompt"],
    )
    if not autolog.check_pipeline_support(StableCascadeCombinedPipeline)
    else dict()
)
autolog(init=dict(project="diffusers_logging", job_type="test"), **pipeline_log_config)

pipe = StableCascadeCombinedPipeline.from_pretrained(
    "stabilityai/stable-cascade", torch_dtype=torch.bfloat16
)
pipe.enable_model_cpu_offload()
prompt = "an image of a shiba inu, donning a spacesuit and helmet"
images = pipe(prompt=prompt)
