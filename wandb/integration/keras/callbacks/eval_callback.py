from typing import List, Optional, Dict

import tensorflow as tf
from tqdm.auto import tqdm

from .tables_builder import WandbTablesBuilder


class WandbEvalCallback(WandbTablesBuilder):
    def __init__(
        self,
        validation_dataset: tf.data.Dataset,
        max_batches: int,
        data_columns: List[str],
        prediction_columns: List[str],
        metrics: Optional[List[tf.keras.metrics.Metric]] = None,
    ):
        super().__init__()

        self.validation_dataset = validation_dataset.take(max_batches)
        self.max_batches = max_batches
        self.metrics = metrics

        data_table_columns = ["Index"] + data_columns
        pred_table_columns = ["Epoch"] + data_columns + prediction_columns
        pred_table_columns = (
            pred_table_columns + [type(metric).__name__ for metric in metrics]
            if metrics is not None
            else pred_table_columns
        )
        super().__init__(
            data_table_columns=data_table_columns,
            pred_table_columns=pred_table_columns,
        )

    def _get_batch_size(self, data) -> int:
        return self.unpack_data(data)[0].shape[0]

    def unpack_data(self, data):
        """Unpack the data from the dataset into a format that can be used for
        prediction, evaludation and visualization.

        Returns:
            Tuple: (inputs, ground_truths)
        """
        raise NotImplementedError(f"{self.__class__.__name__}.unpack_data")

    def visualize_data(self, data):
        """Visualize the data in a row of W&B Tables.

        Returns:
            List: List of objects to be added to the row of W&B Tables.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.visualize_data")

    def visualize_outputs(self, model_outputs):
        """Visualize the model outputs in a row of W&B Tables.

        Returns:
            List: List of objects to be added to the row of W&B Tables.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.visualize_outputs")

    def add_ground_truth(self, logs: Optional[Dict[str, float]] = None) -> None:
        index = 0
        pbar = tqdm(
            next(iter(self.validation_dataset)),
            total=self.max_batches,
            desc="generating data table",
        )
        for data in pbar:
            batch_size = self._get_batch_size(data)
            for _ in range(batch_size):
                self.data_table.add_data(index, *self.visualize_data(data))
                index += 1

    def add_model_predictions(
        self, epoch: int, logs: Optional[Dict[str, float]] = None
    ) -> None:
        index = 0
        pbar = tqdm(
            next(iter(self.validation_dataset)),
            total=self.max_batches,
            desc="generating predictions and evaluating model",
        )

        for data in pbar:
            inputs, ground_truths = self.unpack_data(data)
            model_outputs = self.model.predict(inputs)
            batched_metric_results = [
                metric(ground_truths, model_outputs) for metric in self.metrics
            ]
            batch_size = model_outputs.shape[0]
            for batch_idx in range(batch_size):
                data_table_reference_items = [
                    self.data_table_ref.data[index][col_idx]
                    for col_idx in self.data_table_columns
                ]
                self.pred_table.add_data(
                    epoch,
                    *data_table_reference_items,
                    *self.visualize_outputs(model_outputs[index]),
                    *batched_metric_results[batch_idx],
                )
