import wandb

from PIL import Image as PILImage


import numpy as np

# set the parameters
duration = 1  # duration of the audio signal in seconds
sample_rate = 44100  # number of samples per second
frequency = 440  # frequency of the sine wave in Hz
amplitude = 0.5  # amplitude of the sine wave

# generate the audio signal
time = np.arange(0, duration, 1 / sample_rate)
audio_signal = amplitude * np.sin(2 * np.pi * frequency * time)

# create a new image with a red square
size = (256, 256)
red_image = PILImage.new("RGB", size, (255, 0, 0))
# create a new image with a green square
green_image = PILImage.new("RGB", size, (0, 255, 0))
# create a new image with a blue square
blue_image = PILImage.new("RGB", size, (0, 0, 255))
blue_image.save("blue.jpeg")


# from wandb.sdk.rich_types.image import Image
# from wandb.sdk.rich_types.audio import Audio
# run.log({"image": Image(PILImage.new("RGB", size, (255, 0, 0)))})
# run.log({"image": Image(PILImage.new("RGB", size, (0, 255, 0)))})
# run.log({"image": Image(PILImage.new("RGB", size, (0, 0, 255)))})
# run.log(
#     {"audio": Audio(audio_signal, sample_rate=sample_rate, caption="audio caption")}
# )


# for _ in range(3):
#     run.log(
#         {
#             "image": [
#                 Image(red_image),
#                 Image(green_image),
#                 Image("blue.jpeg"),
#                 # wandb.Audio(audio_signal, sample_rate=sample_rate, caption="audio caption"),
#             ]
#             # )
#         }
#     )

import os

if os.environ.get("OLD_HISTORY"):
    from wandb.data_types import Table
    from wandb.sdk.data_types.image import Image
else:
    from wandb.sdk.rich_types.image import Image
    from wandb.sdk.rich_types.table import Table


my_data = [
    # [0, Image(red_image), 0, 0],
    [1, Image("blue.jpeg"), 8, 0],
    # [2, Image(green_image), 7, 1],
    # [3, Image(blue_image), 1, 1],
    # [0, 2, 0, 0],
]

columns = ["id", "image", "prediction", "truth"]
test_table = Table(data=my_data, columns=columns)

run = wandb.init(project="test_media")
assert run
run.log({"table123": test_table})
# run.log({"image": Image("blue.jpeg")})
# run.log({"a": 1})
run.finish()
