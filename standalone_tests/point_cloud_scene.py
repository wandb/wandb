import os
import numpy as np
import wandb

os.environ.setdefault("WANDB_PROJECT", "lidar-scene-test")
wandb.init()


N_POINT = 1000
points = np.random.rand(N_POINT, 3) * 5 - 2.5


def make_scene(vecs):
    return wandb.Object3D(
        {
            "type": "lidar/beta",
            "vectors": np.array(vecs),
            "points": points,
            "boxes": np.array(
                    [
                        {
                            "corners": [
                                [0, 0, 0],
                                [0, 1, 0],
                                [0, 0, 1],
                                [1, 0, 0],
                                [1, 1, 0],
                                [0, 1, 1],
                                [1, 0, 1],
                                [1, 1, 1]
                            ],
                            # "label": "Tree",
                            "color": [123, 321, 111],
                        },
                        {
                            "corners": [
                                [0, 0, 0],
                                [0, 2, 0],
                                [0, 0, 2],
                                [2, 0, 0],
                                [2, 2, 0],
                                [0, 2, 2],
                                [2, 0, 2],
                                [2, 2, 2]
                            ],
                            # "label": "Card",
                            "color": [111, 321, 0],
                        }
                    ]
            ),
        }
    )

def main():
    vectors = [{"start": [1, 1, 1], "end": [1, 1.5, 1]},
            {"start": [1, 1, 1], "end": [1, 1, 1.5]},
            {"start": [1, 1, 1], "end": [1.2, 1.5, 1.5]}]

    vectors_2 = [
        {
            "start": [2, 2, 2],
            "end": [1, 1.5, 1],
            "color": [255, 255, 0]
        },
        {
            "start": [2, 2, 2],
            "end":[1, 1, 1.5],
            "color": [255, 255, 0],
        },
        {
            "start": [2, 2, 2],
            "end": [1.2, 1.5, 1.5],
            "color": [255, 255, 0]
        }]

    vectors_all = vectors + vectors_2

    wandb.log({
        "separate_vectors": [make_scene([v]) for v in vectors],
        "color_vectors": make_scene(vectors_2),
        "all_vectors": make_scene(vectors_all)
    })

if __name__ == '__main__':
    main()
