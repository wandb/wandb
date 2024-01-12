import random

import torch
from diffusers import PixArtAlphaPipeline
from wandb.integration.diffusers import autolog


def autogenerate_seed():
    max_seed = int(1024 * 1024 * 1024)
    seed = random.randint(1, max_seed)
    seed = -seed if seed < 0 else seed
    seed = seed % max_seed
    return seed

autolog()

pipe = PixArtAlphaPipeline.from_pretrained(
    "PixArt-alpha/PixArt-XL-2-1024-MS", torch_dtype=torch.float16
)
pipe.enable_model_cpu_offload()

prompt = "A small cactus with a happy face in the Sahara desert."
generator = torch.Generator(device="cuda").manual_seed(autogenerate_seed())
image = pipe(prompt, generator=generator).images[0]
