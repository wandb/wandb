import os

import pandas as pd
from transfomers.tokenization_utils_base import PreTrainedTokenizerBase
from transformers import Trainer
from transformers.integrations import WandbCallback
from transformers.trainer_utils import EvalPrediction


def has_exisiting_wandb_callback(trainer: Trainer):
    for item in trainer.callback_handler.callbacks:
        if isinstance(item, WandbCallback):
            return True
    return False


def decode_predictions(tokenizer: PreTrainedTokenizerBase, predictions: EvalPrediction):
    labels = tokenizer.batch_decode(predictions.label_ids)
    prediction_text = tokenizer.batch_decode(predictions.predictions.argmax(axis=-1))
    return {"labels": labels, "predictions": prediction_text}


class WandbCustomCallback(WandbCallback):
    """Custom WandbCallback to log model predictions during training.

    This callback logs model predictions and labels to a wandb.Table at each logging step during training.
    It allows to visualize the model predictions as the training progresses.

    Attributes:
        trainer (Trainer): The Hugging Face Trainer instance.
        tokenizer (AutoTokenizer): The tokenizer associated with the model.
        sample_dataset (Dataset): A subset of the validation dataset for generating predictions.
        num_samples (int, optional): Number of samples to select from the validation dataset for generating predictions. Defaults to 100.
    """

    def __init__(self, trainer, tokenizer, val_dataset, num_samples=100, freq=2):
        """Initializes the WandbPredictionProgressCallback instance.

        Args:
            trainer (Trainer): The Hugging Face Trainer instance.
            tokenizer (AutoTokenizer): The tokenizer associated with the model.
            val_dataset (Dataset): The validation dataset.
            num_samples (int, optional): Number of samples to select from the validation dataset for generating predictions. Defaults to 100.
            freq (int, optional): Control the frequency of logging. Defaults to 2.
        """
        super().__init__()
        self.trainer = trainer
        self.tokenizer = tokenizer
        self.sample_dataset = val_dataset.select(range(num_samples))
        self.freq = freq

        #  we need to know if a wandb callback already exists
        if has_exisiting_wandb_callback(trainer):
            # if it does, we need to remove it
            trainer.callback_handler.pop_callback(WandbCallback)

    def on_evaluate(self, args, state, control, **kwargs):
        """
        This method is called at the end of the evaluation loop.
        Override this method to add custom behavior for logging at the end of the evaluation loop.
        This method should not modify the model, tokenizer, optimizer, or scheduler.
        """
        # control the frequency of logging by logging the predictions every `freq` epochs
        if state.epoch % self.freq == 0:
            # generate predictions
            predictions = self.trainer.predict(self.sample_dataset)
            # decode predictions and labels
            predictions = decode_predictions(self.tokenizer, predictions)
            # add predictions to a wandb.Table
            predictions_df = pd.DataFrame(predictions)
            predictions_df["epoch"] = state.epoch
            records_table = self._wandb.Table(dataframe=predictions_df)
            # log the table to wandb
            self._wandb.log({"sample_predictions": records_table})
