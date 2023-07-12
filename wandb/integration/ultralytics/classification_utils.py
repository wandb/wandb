from typing import Dict, List, Optional, Tuple, Union

import wandb

from ultralytics.yolo.engine.results import Results


def plot_classification_predictions(
    result: Results, table: Optional[wandb.Table] = None
):
    result = result.to("cpu")
    probabilities = result.probs
    probabilities_list = probabilities.data.numpy().tolist()
    class_id_to_label = {int(k): str(v) for k, v in result.names.items()}
    image = wandb.Image(result.orig_img[:, :, ::-1])
    top_5_categories = [
        class_id_to_label[int(class_idx)] for class_idx in list(probabilities.top5)
    ]
    top_5_confindeces = [
        probabilities_list[int(class_idx)] for class_idx in list(probabilities.top5)
    ]
    probability_dict = {
        class_id_to_label[int(class_idx)]: probability
        for class_idx, probability in enumerate(probabilities_list)
    }
    if table is not None:
        table.add_data(
            image,
            class_id_to_label[int(probabilities.top1)],
            probabilities.top1conf,
            top_5_categories,
            top_5_confindeces,
            probability_dict,
            result.speed,
        )
        return table
    return probabilities, top_5_categories, top_5_confindeces, probability_dict
