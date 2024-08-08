#!/usr/bin/env python

import os

import lightning as l
import torch
import wandb
from pl_base import FakeCIFAR10, SimpleNet, TableLoggingCallback
from wandb.integration.lightning.fabric import WandbLogger


def test_fabric_logging():
    # Create a WandbLogger instance
    logger = WandbLogger(project="fabric-test_fabric_logging")

    # Log custom hyperparameters and configurations
    lr = 0.001
    batch_size = 16
    num_epochs = 1
    classes = (
        "plane",
        "car",
        "bird",
        "cat",
        "deer",
        "dog",
        "frog",
        "horse",
        "ship",
        "truck",
    )
    log_images_after_n_batches = 200

    logger.log_hyperparams(
        {
            "lr": lr,
            "batch_size": batch_size,
            "num_epochs": num_epochs,
            "classes": classes,
            "log_images_after_n_batches": log_images_after_n_batches,
        }
    )

    # Save Data to Weights and Biases Artifacts
    root_folder = "data"

    # Replace the original dataset loading code with the fake data generation
    num_samples = batch_size * 10
    train_dataset = FakeCIFAR10(num_samples, os.path.join(root_folder, "train"))
    test_dataset = FakeCIFAR10(num_samples, os.path.join(root_folder, "test"))

    # Save the generated datasets
    train_dataset.save()
    test_dataset.save()

    data_art = wandb.Artifact(name="cifar10", type="dataset")
    data_art.add_dir(os.path.join(root_folder))
    logger.experiment.log_artifact(data_art)

    # Configure our Model and Training
    model = SimpleNet()
    optimizer = torch.optim.SGD(model.parameters(), lr=lr)

    # Load our model, datasources, and loggers into PyTorch Fabric
    tlc = TableLoggingCallback(logger)
    fabric = l.Fabric(loggers=[logger], callbacks=[tlc])
    fabric.launch()

    model, optimizer = fabric.setup(model, optimizer)
    train_dataloader = fabric.setup_dataloaders(
        torch.utils.data.DataLoader(train_dataset, batch_size=batch_size)
    )
    test_dataloader = fabric.setup_dataloaders(
        torch.utils.data.DataLoader(test_dataset, batch_size=batch_size)
    )

    # Training and test loop
    logger.watch(model)
    model.train()

    for epoch in range(num_epochs):
        # Training Loop
        fabric.print(f"Epoch: {epoch}")
        cum_loss = 0
        for batch in train_dataloader:
            inputs, labels = batch
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = torch.nn.functional.cross_entropy(outputs, labels)
            cum_loss += loss.item()
            fabric.backward(loss)
            optimizer.step()
            fabric.log_dict({"loss": loss.item()})

        fabric.log_dict({"avg_loss": cum_loss / len(train_dataloader)})

        # Validation Loop
        correct = 0
        total = 0
        class_correct = list(0.0 for i in range(10))
        class_total = list(0.0 for i in range(10))
        with torch.no_grad():
            for batch_ctr, batch in enumerate(test_dataloader):
                images, labels = batch
                outputs = model(images)
                _, predicted = torch.max(outputs, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
                c = (predicted == labels).squeeze()
                for i in range(batch[0].size(0)):
                    label = labels[i]
                    class_correct[label] += c[i].item()
                    class_total[label] += 1

                if batch_ctr % log_images_after_n_batches == 0:
                    predictions = [classes[prediction] for prediction in predicted]
                    label_names = [classes[truth] for truth in labels]
                    loggable_images = [image for image in images]
                    captions = [
                        f"pred: {pred}\\nlabel: {truth}"
                        for pred, truth in zip(predictions, label_names)
                    ]
                    logger.log_image(
                        key="test_image_batch",
                        images=loggable_images,
                        step=None,
                        caption=captions,
                    )
                    fabric.call(
                        "on_test_batch_end",
                        images=loggable_images,
                        predictions=predictions,
                        ground_truths=label_names,
                    )

        test_acc = 100 * correct / total
        class_acc = {
            f"{classes[i]}_acc": 100 * class_correct[i] / class_total[i]
            for i in range(10)
            if class_total[i] > 0
        }
        loggable_dict = {"test_acc": test_acc}
        loggable_dict.update(class_acc)
        fabric.log_dict(loggable_dict)
        fabric.call("on_model_epoch_end")

    # Finish the experiment
    logger.experiment.finish()


if __name__ == "__main__":
    test_fabric_logging()
