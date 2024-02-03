import torch
from diffusers import DiffusionPipeline
from wandb.integration.diffusers import autolog

autolog()

pipeline = DiffusionPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5", torch_dtype=torch.float16
)
pipeline = pipeline.to("cuda")

prompt = ["a photograph of an astronaut riding a horse", "a photograph of a dragon"]
negative_prompt = ["ugly, deformed", "ugly, deformed"]
generator = torch.Generator(device="cuda").manual_seed(10)

image = pipeline(
    prompt,
    negative_prompt=negative_prompt,
    num_images_per_prompt=2,
    generator=generator,
    guidance_rescale=0.0,
    eta=0.0,
)
