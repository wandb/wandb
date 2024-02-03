import torch
from diffusers import AudioLDM2Pipeline
from wandb.integration.diffusers import autolog

autolog()

pipe = AudioLDM2Pipeline.from_pretrained("cvssp/audioldm2", torch_dtype=torch.float16)
pipe = pipe.to("cuda")

prompt = "The sound of a hammer hitting a wooden surface."
negative_prompt = "Low quality."
generator = torch.Generator("cuda").manual_seed(10)

audio = pipe(
    prompt,
    negative_prompt=negative_prompt,
    num_inference_steps=200,
    audio_length_in_s=10.0,
    num_waveforms_per_prompt=3,
    generator=generator,
).audios
