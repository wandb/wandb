import wandb
from typing import List
from abc import ABC, abstractmethod


class WandbEvalTablesBuilder(ABC):
    """
    Utility class that contains useful methods to create W&B Tables,
    and log it to W&B.

    Use this to create evaluation table for classification, object detection,
    segmentation, etc. tasks. While training a neural network, the ability to
    visualize the model predictions on validation data can be useful to
    debug the model and more.

    This utility class can be used from within a custom Keras callback. The user
    will have to implement two methods - `add_ground_truth` to add the validation
    samples and `add_model_predictions` to log the model prediction on the samples.

    Example:
        ```
        class WandbClfEvalCallback(tf.keras.callbacks.Callback):
            def __init__(self,
                        validation_data,
                        num_samples=100):
                super().__init__()

                self.validation_data = validation_data
                self.tables_builder = WandbTablesBuilder()

            def on_train_begin(self, logs=None):
                self.tables_builder.init_data_table(
                    column_names = ["image_index", "images", "ground_truth"]
                )
                self.add_ground_truth()
                self.tables_builder.log_data_table()

            def on_epoch_end(self, epoch, logs=None):
                self.tables_builder.init_pred_table(
                    column_names = ["epoch", "image_index", "images",
                                    "ground_truth", "prediction"]
                )
                self.add_model_predictions(epoch)
                self.tables_builder.log_pred_table()

            def add_ground_truth(self):
                for idx, (image, label) in enumerate(self.validation_data):
                    self.tables_builder.data_table.add_data(
                        idx,
                        wandb.Image(image),
                        label
                    )

            def add_model_predictions(self, epoch):
                preds = self.model.predict(self.validation_data, verbose=0)

                data_table_ref = self.tables_builder.data_table_ref
                table_idxs = data_table_ref.get_index()

                for idx in table_idxs:
                    pred = preds[idx]
                    self.tables_builder.pred_table.add_data(
                        epoch,
                        data_table_ref.data[idx][0],
                        data_table_ref.data[idx][1],
                        data_table_ref.data[idx][2],
                        pred
                    )
        ```

    This utility class will take care of the following:
    - Initialize `data_table` for logging ground truth and
        `pred_table` for predictions.
    - The data uploaded to `data_table` is used as reference for the
        `pred_table`. The `data_table_ref` is how you can access the referenced
        data. Check out the example above to see how it's done.
    - Log the table to W&B as W&B artifacts.
    - Each new `pred_table` is logged as a new version with aliases.
    """
    def __init__(self):
        if wandb.run is None:
            raise wandb.Error("You must call wandb.init() before WandbEvalTablesBuilder()")

        with wandb.wandb_lib.telemetry.context(run=wandb.run) as tel:
            tel.feature.keras_wandb_eval_tables_builder = True

    @abstractmethod
    def add_ground_truth(self):
        """Use this method to write the logic for adding validation/training
        data to `data_table` initialized using `init_data_table` method.
        Example:
            ```
            for idx, data in enumerate(dataloader):
                self.data_table.add_data(
                    idx,
                    data
                )
            ```
        This method is called once `on_train_begin` or equivalent hook.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.add_ground_truth")

    @abstractmethod
    def add_model_predictions(self):
        """Use this method to write the logic for adding model prediction for
        validation/training data to `pred_table` initialized using
        `init_pred_table` method.
        Example:
            ```
            # Assuming the dataloader is not shuffling the samples.
            for idx, data in enumerate(dataloader):
                preds = model.predict(data)
                self.pred_table.add_data(
                    self.data_table_ref.data[idx][0],
                    self.data_table_ref.data[idx][1],
                    preds
                )
            ```
        This method is called `on_epoch_end` or equivalent hook.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.add_model_predictions")

    def init_data_table(self, column_names: List[str]):
        """Initialize the W&B Tables for validation data.
        Call this method `on_train_begin` or equivalent hook. This is followed by
        adding data to the table row or column wise.
        Args:
            column_names (list): Column names for W&B Tables.
        """
        self.data_table = wandb.Table(columns=column_names, allow_mixed_types=True)

    def init_pred_table(self, column_names: List[str]):
        """Initialize the W&B Tables for model evaluation.
        Call this method `on_epoch_end` or equivalent hook. This is followed by
        adding data to the table row or column wise.
        Args:
            column_names (list): Column names for W&B Tables.
        """
        self.pred_table = wandb.Table(columns=column_names)

    def log_data_table(self, 
                       name: str='val',
                       type: str='dataset',
                       table_name: str='val_data'):
        """Log the `data_table` as W&B artifact and call
        `use_artifact` on it so that the evaluation table can use the reference
        of already uploaded data (images, text, scalar, etc.).
        This allows the data to be uploaded just once.
        Args:
            name (str):  A human-readable name for this artifact, which is how 
                you can identify this artifact in the UI or reference 
                it in use_artifact calls. (default is 'val')
            type (str): The type of the artifact, which is used to organize and
                differentiate artifacts. (default is 'val_data')
            table_name (str): The name of the table as will be displayed in the UI.
        """
        data_artifact = wandb.Artifact(name, type=type)
        data_artifact.add(self.data_table, table_name)

        # Calling `use_artifact` uploads the data to W&B.
        wandb.run.use_artifact(data_artifact)
        data_artifact.wait()

        # We get the reference table.
        self.data_table_ref = data_artifact.get(table_name)

    def log_pred_table(self,
                       type: str='evaluation',
                       table_name: str='eval_data',
                       aliases: List[str] = ["latest"]):
        """Log the W&B Tables for model evaluation.
        The table will be logged multiple times creating new version. Use this
        to compare models at different intervals interactively.
        Args:
            type (str): The type of the artifact, which is used to organize and
                differentiate artifacts. (default is 'val_data')
            table_name (str): The name of the table as will be displayed in the UI.
            aliases (List[str]): List of aliases for the pediction table.
        """
        pred_artifact = wandb.Artifact(
            f'run_{wandb.run.id}_pred', type=type)
        pred_artifact.add(self.pred_table, table_name)
        wandb.run.log_artifact(pred_artifact, aliases=aliases)
