# http://app.wandb.ai/nbaryd/client-standalone_tests/runs/w1iqzmdw?workspace=user-

import numpy as np
import wandb

point_cloud_1 = np.array([[0, 0, 0, 1],
                          [0, 0, 1, 13],
                          [0, 1, 0, 2],
                          [0, 1, 0, 4]])

point_cloud_2 = np.array([[0, 0, 0],
                          [0, 0, 1],
                          [0, 1, 0],
                          [0, 1, 0]])

point_cloud_3 = np.array([[0, 0, 0, 200, 100,  70],
                          [0, 0, 1, 100, 200, 100],
                          [0, 1, 0, 100, 400, 300],
                          [0, 1, 0,  40, 100, 100]])


wandb.init()
wandb.log({"Clouds": [wandb.Object3D(point_cloud_1), wandb.Object3D(point_cloud_2)],
           "Colored_Cloud": [wandb.Object3D(point_cloud_3)],
           "gltf": wandb.Object3D(open("tests/fixtures/Box.gltf")),
           "obj": wandb.Object3D(open("tests/fixtures/cube.obj"))})
