import torch
from diffusers import AudioLDM2Pipeline
from wandb.integration.diffusers import autolog

autolog(init=dict(project="diffusers_logging", job_type="audio-ldm-2"))

pipe = AudioLDM2Pipeline.from_pretrained("cvssp/audioldm2", torch_dtype=torch.float16)
pipe = pipe.to("cuda")

# define the prompts
prompt = "The sound of a hammer hitting a wooden surface."
negative_prompt = "Low quality."

# set the seed for generator
generator = torch.Generator("cuda").manual_seed(0)

# run the generation
audio = pipe(
    prompt,
    negative_prompt=negative_prompt,
    num_inference_steps=200,
    audio_length_in_s=10.0,
    num_waveforms_per_prompt=3,
    generator=generator,
).audios
