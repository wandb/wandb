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
                        {
                            "x": 0,
                            "y": 0,
                            "height": 3,
                            "width": 2,
                            "depth": 1,
                        },
                        {
                            "x": 0.3,
                            "y": 0,
                            "height": 0.2,
                            "width": 0.2,
                            "depth": 4,
                        }
                    ]
                )
            }
        )
    }
)

