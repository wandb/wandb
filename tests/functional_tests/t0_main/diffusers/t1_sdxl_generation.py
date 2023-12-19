import torch
from diffusers import StableDiffusionXLImg2ImgPipeline, StableDiffusionXLPipeline
from wandb.integration.diffusers import autolog

autolog(init=dict(project="diffusers_logging", job_type="sdxl"))


generator = torch.Generator(device="cuda").manual_seed(100)

base_pipeline = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    variant="fp16",
    use_safetensors=True,
)

base_pipeline.enable_model_cpu_offload()

prompt = "A small cactus with a happy face in the Sahara desert."

num_inference_steps = 25

image = base_pipeline(
    prompt=prompt,
    generator=generator,
    guidance_scale=5.0,
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

image = refiner_pipeline(
    prompt=prompt, image=image[None, :], generator=generator
).images[0]
