import wandb
import numpy as np

wandb.init()

wandb.log(
    {
        "point_scene": wandb.Object3D(
            {
                "type": "lidar/beta",
                "points": np.array([[0.4, 1, 1.3], [1, 1, 1], [1.2, 1, 1.2]]),
                "boxes": np.array(
                    [
                        [
                            [0,0,0],
                            [0,1,0],
                            [0,0,1],
                            [1,0,0],
                            [1,1,0],
                            [0,1,1],
                            [1,0,1],
                            [1,1,1]
                        ]
                    ]
                ),
            }
        )
    }
)

