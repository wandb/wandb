import torch
from diffusers import StableDiffusionXLImg2ImgPipeline, StableDiffusionXLPipeline
from wandb.integration.diffusers import autolog

autolog()

base_pipeline = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    variant="fp16",
    use_safetensors=True,
)
base_pipeline.enable_model_cpu_offload()

prompt = "A small cactus with a happy face in the Sahara desert."
generator_base = torch.Generator(device="cuda").manual_seed(10)
image = base_pipeline(
    prompt=prompt,
    generator=generator_base,
    guidance_scale=5.0,
    output_type="latent",
).images[0]

refiner_pipeline = StableDiffusionXLImg2ImgPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-refiner-1.0",
    text_encoder_2=base_pipeline.text_encoder_2,
    vae=base_pipeline.vae,
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
)
refiner_pipeline.enable_model_cpu_offload()

generator_refiner = torch.Generator(device="cuda").manual_seed(10)
image = refiner_pipeline(
    prompt=prompt, image=image[None, :], generator=generator_refiner
).images[0]
