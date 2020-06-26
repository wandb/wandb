import wandb
import numpy as np

wandb.init(project="lidar-scene-test")


N_POINT = 1000
points = np.random.rand(N_POINT, 3) * 5 - 2.5

wandb.log(
        {
            "point_scene": wandb.Object3D(
                {
                    "type": "lidar/beta",
                    "vectors": np.array([
                        [[1, 1, 1], [1, 2, 1]],
                        [[1, 1, 1], [1, 1, 2]],
                        [[1, 1, 1], [2, 2, 2]]
                    ]),
                    "points": points,
                    "boxes": np.array(
                        [
                            {
                                "corners": [
                                    [0,0,0],
                                    [0,1,0],
                                    [0,0,1],
                                    [1,0,0],
                                    [1,1,0],
                                    [0,1,1],
                                    [1,0,1],
                                    [1,1,1]
                                ],
                                # "label": "Tree",
                                "color": [123,321,111],
                            },
                            {
                                "corners": [
                                    [0,0,0],
                                    [0,2,0],
                                    [0,0,2],
                                    [2,0,0],
                                    [2,2,0],
                                    [0,2,2],
                                    [2,0,2],
                                    [2,2,2]
                                ],
                                # "label": "Card",
                                "color": [111,321,0],
                            }
                        ]
                    ),
                }
            )
        }
    )

