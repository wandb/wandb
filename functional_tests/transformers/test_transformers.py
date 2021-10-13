import os
import transformers
import datasets
from transformers import (
    Trainer,
    TrainingArguments,
    AutoTokenizer,
    AutoModelForSequenceClassification,
)
from datasets import load_dataset, load_metric, Dataset
import numpy as np

os.environ["WANDB_PROJECT"] = "integrations_testing"
transformers.logging.set_verbosity_error()
datasets.logging.set_verbosity_error()


def tokenize_function(examples):
    return tokenizer(examples["text"], padding=True, truncation=True, max_length=100)


model_name = "google/mobilebert-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_name, num_labels=2)

n_text = 50
dummy_text = "The dog walked on the moon! " * n_text
dummy_dict = {"text": [dummy_text] * n_text, "label": [1] * n_text}
dataset = Dataset.from_dict(dummy_dict)
tokenized_dataset = dataset.map(tokenize_function, batched=False)
tokenized_dataset = tokenized_dataset.remove_columns(["text"])
tokenized_dataset.set_format("torch")

metric = load_metric("accuracy")


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    return metric.compute(predictions=predictions, references=labels)


training_args = TrainingArguments(
    "test_trainer",
    evaluation_strategy="epoch",
    num_train_epochs=2,
    per_device_train_batch_size=32,
    per_device_eval_batch_size=32,
    logging_strategy="steps",
    logging_steps=1,
    report_to="wandb",
    run_name="testing",
)

model = AutoModelForSequenceClassification.from_pretrained(model_name)
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset,
    eval_dataset=tokenized_dataset,
    compute_metrics=compute_metrics,
)

trainer.train()
wandb.finish()
