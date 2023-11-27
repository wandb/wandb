import torch
from diffusers import PixArtAlphaPipeline
from wandb.integration.diffusers import autolog

autolog(init=dict(project="diffusers_logging", job_type="pixart-alpha"))

pipe = PixArtAlphaPipeline.from_pretrained(
    "PixArt-alpha/PixArt-XL-2-1024-MS", torch_dtype=torch.float16
)
pipe.enable_model_cpu_offload()

prompt = "A small cactus with a happy face in the Sahara desert."
image = pipe(prompt).images[0]
