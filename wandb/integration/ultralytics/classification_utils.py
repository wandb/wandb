from typing import Any, Optional

import numpy as np
from tqdm.auto import tqdm
from ultralytics.engine.results import Results
from ultralytics.models.yolo.classify import ClassificationPredictor

import wandb


def plot_classification_predictions(
    result: Results,
    model_name: str,
    table: Optional[wandb.Table] = None,
    original_image: Optional[np.array] = None,
):
    """Plot classification prediction results to a `wandb.Table` if the table is passed otherwise return the data."""
    result = result.to("cpu")
    probabilities = result.probs
    probabilities_list = probabilities.data.numpy().tolist()
    class_id_to_label = {int(k): str(v) for k, v in result.names.items()}
    original_image = (
        wandb.Image(original_image)
        if original_image is not None
        else wandb.Image(result.orig_img)
    )
    table_row = [
        model_name,
        original_image,
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
) -> wandb.Table:
    """Plot classification results to a `wandb.Table`."""
    data_idx = 0
    num_dataloader_batches = len(dataloader.dataset) // dataloader.batch_size
    max_validation_batches = min(max_validation_batches, num_dataloader_batches)
    for batch_idx, batch in enumerate(dataloader):
        image_batch = [
            image for image in np.transpose(batch["img"].numpy(), (0, 2, 3, 1))
        ]
        ground_truth = batch["cls"].numpy().tolist()
        progress_bar_result_iterable = tqdm(
            range(max_validation_batches),
            desc=f"Generating Visualizations for batch-{batch_idx + 1}/{max_validation_batches}",
        )
        for img_idx in progress_bar_result_iterable:
            try:
                prediction_result = predictor(image_batch[img_idx])[0]
                class_id_to_label, table_row = plot_classification_predictions(
                    prediction_result, model_name, original_image=image_batch[img_idx]
                )
                table_row = [data_idx, batch_idx] + table_row[1:]
                table_row.insert(3, class_id_to_label[ground_truth[img_idx]])
                table_row = [epoch] + table_row if epoch is not None else table_row
                table_row = [model_name] + table_row
                table.add_data(*table_row)
                data_idx += 1
            except Exception:
                pass
        if batch_idx + 1 == max_validation_batches:
            break
    return table
