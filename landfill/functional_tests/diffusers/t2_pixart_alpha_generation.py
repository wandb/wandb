import torch
from diffusers import PixArtAlphaPipeline

from wandb.integration.diffusers import autolog

autolog()

pipe = PixArtAlphaPipeline.from_pretrained(
    "PixArt-alpha/PixArt-XL-2-1024-MS", torch_dtype=torch.float16
)
pipe.enable_model_cpu_offload()

prompt = "A small cactus with a happy face in the Sahara desert."
generator = torch.Generator(device="cuda").manual_seed(10)
image = pipe(prompt, generator=generator).images[0]
