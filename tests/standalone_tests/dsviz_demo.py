import os
import pickle
import shutil
import time

import numpy as np
import wandb
from PIL import Image

WANDB_PROJECT_ENV = os.environ.get("WANDB_PROJECT")
if WANDB_PROJECT_ENV is None:
    WANDB_PROJECT = "test__" + str(round(time.time()) % 1000000)
else:
    WANDB_PROJECT = WANDB_PROJECT_ENV
os.environ["WANDB_PROJECT"] = WANDB_PROJECT

WANDB_SILENT_ENV = os.environ.get("WANDB_SILENT")
if WANDB_SILENT_ENV is None:
    WANDB_SILENT = "true"
else:
    WANDB_SILENT = WANDB_SILENT_ENV
os.environ["WANDB_SILENT"] = WANDB_SILENT

NUM_EXAMPLES = 10
DL_URL = "https://raw.githubusercontent.com/wandb/dsviz-demo/master/bdd20_small.tgz"  # "https://storage.googleapis.com/l2kzone/bdd100k.tgz"
LOCAL_FOLDER_NAME = "bdd20_small"  # "bdd100k"
LOCAL_ASSET_NAME = f"{LOCAL_FOLDER_NAME}.tgz"


BDD_CLASSES = [
    "road",
    "sidewalk",
    "building",
    "wall",
    "fence",
    "pole",
    "traffic light",
    "traffic sign",
    "vegetation",
    "terrain",
    "sky",
    "person",
    "rider",
    "car",
    "truck",
    "bus",
    "train",
    "motorcycle",
    "bicycle",
    "void",
]
BDD_IDS = list(range(len(BDD_CLASSES) - 1)) + [255]
BDD_ID_MAP = {id: ndx for ndx, id in enumerate(BDD_IDS)}

n_classes = len(BDD_CLASSES)
bdd_dir = os.path.join(".", LOCAL_FOLDER_NAME, "seg")
train_dir = os.path.join(bdd_dir, "images", "train")
color_labels_dir = os.path.join(bdd_dir, "color_labels", "train")
labels_dir = os.path.join(bdd_dir, "labels", "train")

train_ids = None


def cleanup():
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")

    if os.path.isdir(LOCAL_FOLDER_NAME):
        shutil.rmtree(LOCAL_FOLDER_NAME)

    if os.path.isdir("wandb"):
        shutil.rmtree("wandb")

    if os.path.isfile(LOCAL_ASSET_NAME):
        os.remove(LOCAL_ASSET_NAME)

    if os.path.isfile("model.pkl"):
        os.remove("model.pkl")


def download_data():
    global train_ids
    if not os.path.exists(LOCAL_ASSET_NAME):
        os.system(f"curl {DL_URL} --output {LOCAL_ASSET_NAME}")

    if not os.path.exists(LOCAL_FOLDER_NAME):
        os.system(f"tar xzf {LOCAL_ASSET_NAME}")

    train_ids = [
        name.split(".")[0] for name in os.listdir(train_dir) if name.split(".")[0] != ""
    ]


def _check_train_ids():
    if train_ids is None:
        raise Exception(
            "Please download the data using download_data() before attempting to access it."
        )


def get_train_image_path(ndx):
    _check_train_ids()
    return os.path.join(train_dir, train_ids[ndx] + ".jpg")


def get_color_label_image_path(ndx):
    _check_train_ids()
    return os.path.join(color_labels_dir, train_ids[ndx] + "_train_color.png")


def get_label_image_path(ndx):
    _check_train_ids()
    return os.path.join(labels_dir, train_ids[ndx] + "_train_id.png")


def get_dominant_id_ndx(np_image):
    if isinstance(np_image, wandb.Image):
        np_image = np.array(np_image.image)
    return BDD_ID_MAP[np.argmax(np.bincount(np_image.astype(int).flatten()))]


def clean_artifacts_dir():
    if os.path.isdir("artifacts"):
        shutil.rmtree("artifacts")


def mask_to_bounding(np_image):
    if isinstance(np_image, wandb.Image):
        np_image = np.array(np_image.image)

    data = []
    for id_num in BDD_IDS:
        matches = np_image == id_num
        col_count = np.where(matches.sum(axis=0))[0]
        row_count = np.where(matches.sum(axis=1))[0]

        if len(col_count) > 1 and len(row_count) > 1:
            min_x = col_count[0] / np_image.shape[1]
            max_x = col_count[-1] / np_image.shape[1]
            min_y = row_count[0] / np_image.shape[0]
            max_y = row_count[-1] / np_image.shape[0]

            data.append(
                {
                    "position": {
                        "minX": min_x,
                        "maxX": max_x,
                        "minY": min_y,
                        "maxY": max_y,
                    },
                    "class_id": id_num,
                }
            )
    return data


def get_scaled_train_image(ndx, factor=2):
    return Image.open(get_train_image_path(ndx)).reduce(factor)


def get_scaled_mask_label(ndx, factor=2):
    return np.array(Image.open(get_label_image_path(ndx)).reduce(factor))


def get_scaled_bounding_boxes(ndx, factor=2):
    return mask_to_bounding(
        np.array(Image.open(get_label_image_path(ndx)).reduce(factor))
    )


def get_scaled_color_mask(ndx, factor=2):
    return Image.open(get_color_label_image_path(ndx)).reduce(factor)


def get_dominant_class(label_mask):
    return BDD_CLASSES[get_dominant_id_ndx(label_mask)]


class ExampleSegmentationModel:
    def __init__(self, n_classes):
        self.n_classes = n_classes

    def train(self, images, masks):
        self.min = images.min()
        self.max = images.max()
        images = (images - self.min) / (self.max - self.min)
        step = 1.0 / n_classes
        self.quantiles = list(
            np.quantile(images, [i * step for i in range(self.n_classes)])
        )
        self.quantiles.append(1.0)
        self.outshape = masks.shape

    def predict(self, images):
        results = np.zeros((images.shape[0], self.outshape[1], self.outshape[2]))
        images = ((images - self.min) / (self.max - self.min)).mean(axis=3)
        for i in range(self.n_classes):
            results[
                (self.quantiles[i] < images) & (images <= self.quantiles[i + 1])
            ] = BDD_IDS[i]
        return results

    def save(self, file_path):
        with open(file_path, "wb") as file:
            pickle.dump(self, file)

    @staticmethod
    def load(file_path):
        model = None
        with open(file_path, "rb") as file:
            model = pickle.load(file)
        return model


def iou(mask_a, mask_b, class_id):
    return np.nan_to_num(
        ((mask_a == class_id) & (mask_b == class_id)).sum(axis=(1, 2))
        / ((mask_a == class_id) | (mask_b == class_id)).sum(axis=(1, 2)),
        0,
        0,
        0,
    )


def score_model(model, x_data, mask_data, n_classes):
    results = model.predict(x_data)
    return np.array([iou(results, mask_data, i) for i in BDD_IDS]).T, results


def make_datasets(data_table, n_classes):
    n_samples = len(data_table.data)
    # n_classes = len(BDD_CLASSES)
    height = data_table.data[0][1].image.height
    width = data_table.data[0][1].image.width

    train_data = np.array(
        [
            np.array(data_table.data[i][1].image).reshape(height, width, 3)
            for i in range(n_samples)
        ]
    )
    mask_data = np.array(
        [
            np.array(data_table.data[i][3].image).reshape(height, width)
            for i in range(n_samples)
        ]
    )
    return train_data, mask_data


def main():
    try:
        # Download the data if not already
        download_data()

        # Initialize the run
        with wandb.init(
            project=WANDB_PROJECT,  # The project to register this Run to
            job_type="create_dataset",  # The type of this Run. Runs of the same type can be grouped together in the UI
            config={  # Custom configuration parameters which you might want to tune or adjust for the Run
                "num_examples": NUM_EXAMPLES,  # The number of raw samples to include.
                "scale_factor": 2,  # The scaling factor for the images
            },
        ) as run:

            # Setup a WandB Classes object. This will give additional metadata for visuals
            class_set = wandb.Classes(
                [{"name": name, "id": id} for name, id in zip(BDD_CLASSES, BDD_IDS)]
            )

            # Setup a WandB Table object to hold our dataset
            table = wandb.Table(
                columns=[
                    "id",
                    "train_image",
                    "colored_image",
                    "label_mask",
                    "dominant_class",
                ]
            )

            # Fill up the table
            for ndx in range(run.config["num_examples"]):

                # First, we will build a wandb.Image to act as our raw example object
                #    classes: the classes which map to masks and/or box metadata
                #    masks: the mask metadata. In this case, we use a 2d array where each cell corresponds to the label (this comes directlyfrom the dataset)
                #    boxes: the bounding box metadata. For example sake, we create bounding boxes by looking at the mask data and creating boxes which fully encolose each class.
                #           The data is an array of objects like:
                #                 "position": {
                #                             "minX": minX,
                #                             "maxX": maxX,
                #                             "minY": minY,
                #                             "maxY": maxY,
                #                         },
                #                         "class_id" : id_num,
                #                     }
                example = wandb.Image(
                    get_scaled_train_image(ndx, run.config.scale_factor),
                    classes=class_set,
                    masks={
                        "ground_truth": {
                            "mask_data": get_scaled_mask_label(
                                ndx, run.config.scale_factor
                            )
                        },
                    },
                    boxes={
                        "ground_truth": {
                            "box_data": get_scaled_bounding_boxes(
                                ndx, run.config.scale_factor
                            )
                        }
                    },
                )

                # Next, we create two additional images which may be helpful during analysis. Notice that the additional metadata is optional.
                color_label = wandb.Image(
                    get_scaled_color_mask(ndx, run.config.scale_factor)
                )
                label_mask = wandb.Image(
                    get_scaled_mask_label(ndx, run.config.scale_factor)
                )

                # Finally, we add a row of our newly constructed data.
                table.add_data(
                    train_ids[ndx],
                    example,
                    color_label,
                    label_mask,
                    get_dominant_class(label_mask),
                )

            # Create an Artifact (versioned folder)
            artifact = wandb.Artifact(name="raw_data", type="dataset")

            # add the table to the artifact
            artifact.add(table, "raw_examples")

            # Finally, log the artifact
            run.log_artifact(artifact)
        print("Step 1/5 Complete")

        # This step should look familiar by now:
        with wandb.init(
            project=WANDB_PROJECT,
            job_type="split_dataset",
            config={
                "train_pct": 0.7,
            },
        ) as run:

            # Get the latest version of the artifact. Notice the name alias follows this convention: "<ARTIFACT_NAME>:<VERSION>"
            # when version is set to "latest", then the latest version will always be used. However, you can pin to a version by
            # using an alias such as "raw_data:v0"
            dataset_artifact = run.use_artifact("raw_data:latest")

            # Next, we "get" the table by the same name that we saved it in the last run.
            data_table = dataset_artifact.get("raw_examples")

            # Now we can build two separate artifacts for later use. We will first split the raw table into two parts,
            # then create two different artifacts, each of which will hold our new tables. We create two artifacts so that
            # in future runs, we can selectively decide which subsets of data to download.

            # Create the tables
            train_count = int(len(data_table.data) * run.config.train_pct)
            train_table = wandb.Table(
                columns=data_table.columns, data=data_table.data[:train_count]
            )
            test_table = wandb.Table(
                columns=data_table.columns, data=data_table.data[train_count:]
            )

            # Create the artifacts
            train_artifact = wandb.Artifact("train_data", "dataset")
            test_artifact = wandb.Artifact("test_data", "dataset")

            # Save the tables to the artifacts
            train_artifact.add(train_table, "train_table")
            test_artifact.add(test_table, "test_table")

            # Log the artifacts out as outputs of the run
            run.log_artifact(train_artifact)
            run.log_artifact(test_artifact)
        print("Step 2/5 Complete")

        # Again, create a run.
        with wandb.init(project=WANDB_PROJECT, job_type="model_train") as run:

            # Similar to before, we will load in the artifact and asset we need. In this case, the training data
            train_artifact = run.use_artifact("train_data:latest")
            train_table = train_artifact.get("train_table")

            # Next, we split out the labels and train the model
            train_data, mask_data = make_datasets(train_table, n_classes)
            model = ExampleSegmentationModel(n_classes)
            model.train(train_data, mask_data)

            # Finally we score the model. Behind the scenes, we score each mask on it's IOU score.
            scores, results = score_model(model, train_data, mask_data, n_classes)

            # Let's create a new table. Notice that we create many columns - an evaluation score for each class type.
            results_table = wandb.Table(
                columns=["id", "pred_mask", "dominant_pred"] + BDD_CLASSES,
                # Data construction is similar to before, but we now use the predicted masks and bound boxes.
                data=[
                    [
                        train_table.data[ndx][0],
                        wandb.Image(
                            train_table.data[ndx][1],
                            masks={
                                "train_predicted_truth": {
                                    "mask_data": results[ndx],
                                },
                            },
                            boxes={
                                "ground_truth": {
                                    "box_data": mask_to_bounding(results[ndx])
                                }
                            },
                        ),
                        BDD_CLASSES[get_dominant_id_ndx(results[ndx])],
                    ]
                    + list(row)
                    for ndx, row in enumerate(scores)
                ],
            )

            # We create an artifact, add the table, and log it as part of the run.
            results_artifact = wandb.Artifact("train_results", "dataset")
            results_artifact.add(results_table, "train_iou_score_table")
            run.log_artifact(results_artifact)

            # Finally, let's save the model as a flat file and add that to it's own artifact.
            model.save("model.pkl")
            model_artifact = wandb.Artifact("trained_model", "model")
            model_artifact.add_file("model.pkl")
            run.log_artifact(model_artifact)
        print("Step 3/5 Complete")

        with wandb.init(project=WANDB_PROJECT, job_type="model_eval") as run:

            # Retrieve the test data
            test_artifact = run.use_artifact("test_data:latest")
            test_table = test_artifact.get("test_table")
            test_data, mask_data = make_datasets(test_table, n_classes)

            # Download the saved model file.
            model_artifact = run.use_artifact("trained_model:latest")
            path = model_artifact.get_path("model.pkl").download()

            # Load the model from the file and score it
            model = ExampleSegmentationModel.load(path)
            scores, results = score_model(model, test_data, mask_data, n_classes)

            # Create a predicted score table similar to step 3.
            results_artifact = wandb.Artifact("test_results", "dataset")
            data = [
                [
                    test_table.data[ndx][0],
                    wandb.Image(
                        test_table.data[ndx][1],
                        masks={
                            "test_predicted_truth": {
                                "mask_data": results[ndx],
                            },
                        },
                        boxes={
                            "ground_truth": {"box_data": mask_to_bounding(results[ndx])}
                        },
                    ),
                    BDD_CLASSES[get_dominant_id_ndx(results[ndx])],
                ]
                + list(row)
                for ndx, row in enumerate(scores)
            ]

            # And log out the results.
            results_artifact.add(
                wandb.Table(
                    ["id", "pred_mask_test", "dominant_pred_test"] + BDD_CLASSES,
                    data=data,
                ),
                "test_iou_score_table",
            )
            run.log_artifact(results_artifact)
        print("Step 4/5 Complete")

        with wandb.init(project=WANDB_PROJECT, job_type="model_result_analysis") as run:

            # Retrieve the original raw dataset
            dataset_artifact = run.use_artifact("raw_data:latest")
            data_table = dataset_artifact.get("raw_examples")

            # Retrieve the train and test score tables
            train_artifact = run.use_artifact("train_results:latest")
            train_table = train_artifact.get("train_iou_score_table")

            test_artifact = run.use_artifact("test_results:latest")
            test_table = test_artifact.get("test_iou_score_table")

            # Join the tables on ID column and log them as outputs.
            train_results = wandb.JoinedTable(train_table, data_table, "id")
            test_results = wandb.JoinedTable(test_table, data_table, "id")
            artifact = wandb.Artifact("summary_results", "dataset")
            artifact.add(train_results, "train_results")
            artifact.add(test_results, "test_results")
            run.log_artifact(artifact)
        print("Step 5/5 Complete")

        if WANDB_PROJECT_ENV is not None:
            os.environ["WANDB_PROJECT"] = WANDB_PROJECT_ENV

        if WANDB_SILENT_ENV is not None:
            os.environ["WANDB_SILENT"] = WANDB_SILENT_ENV
    finally:
        cleanup()


if __name__ == "__main__":
    main()
