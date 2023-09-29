from typing import Any, Optional

import numpy as np
from ultralytics.engine.results import Results
from ultralytics.models.yolo.classify import ClassificationPredictor

import wandb


def plot_classification_predictions(
    result: Results, model_name: str, table: Optional[wandb.Table] = None
):
    """Plot classification prediction results to a `wandb.Table` if the table is passed otherwise return the data."""
    result = result.to("cpu")
    probabilities = result.probs
    probabilities_list = probabilities.data.numpy().tolist()
    class_id_to_label = {int(k): str(v) for k, v in result.names.items()}
    table_row = [
        model_name,
        wandb.Image(result.orig_img),
        class_id_to_label[int(probabilities.top1)],
        probabilities.top1conf,
        [class_id_to_label[int(class_idx)] for class_idx in list(probabilities.top5)],
        [probabilities_list[int(class_idx)] for class_idx in list(probabilities.top5)],
        {
            class_id_to_label[int(class_idx)]: probability
            for class_idx, probability in enumerate(probabilities_list)
        },
        result.speed,
    ]
    if table is not None:
        table.add_data(*table_row)
        return table
    return class_id_to_label, table_row


def plot_classification_validation_results(
    dataloader: Any,
    model_name: str,
    predictor: ClassificationPredictor,
    table: wandb.Table,
    max_validation_batches: int,
    epoch: Optional[int] = None,
):
    """Plot classification results to a `wandb.Table`."""
    data_idx = 0
    predictor.args.save = False
    predictor.args.show = False
    for batch_idx, batch in enumerate(dataloader):
        image_batch = batch["img"].numpy()
        ground_truth = batch["cls"].numpy().tolist()
        for img_idx in range(image_batch.shape[0]):
            image = np.transpose(image_batch[img_idx], (1, 2, 0))
            prediction_result = predictor(image, show=False)[0]
            class_id_to_label, table_row = plot_classification_predictions(
                prediction_result, model_name
            )
            table_row = [data_idx, batch_idx] + table_row[1:]
            table_row.insert(3, class_id_to_label[ground_truth[img_idx]])
            table_row = [epoch] + table_row if epoch is not None else table_row
            table_row = [model_name] + table_row
            table.add_data(*table_row)
            data_idx += 1
        if batch_idx + 1 == max_validation_batches:
            break
    return table
