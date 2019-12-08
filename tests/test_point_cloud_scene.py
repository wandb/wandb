import wandb
import numpy as np

wandb.init()

wandb.log(
    {
        "point_scene": wandb.Object3D(
            {
                "type": "scene/v1",
                "points": np.array([[0.4, 1, 1.3], [1, 1, 1], [1.2, 1, 1.2]]),
                "boxes": np.array(
                    [
                        [
                            # Size 2 unit cube
                            [0, 0, 0],
                            [0, 0, 2],
                            [0, 0, 2],
                            [0, 2, 0],
                            [2, 0, 0],
                            [0, 2, 2],
                            [2, 2, 0],
                            [2, 0, 2],
                            [2, 2, 2],
                        ]
                    ]
                ),
                "center": [1, 1, 1],
            }
        )
    }
)

