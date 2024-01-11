import argparse
import datetime
import os
import tempfile
import time

import numpy as np
import pandas as pd
import tqdm
from astropy.time import Time

import wandb


def main(
    port: str = "",
    finish: bool = False,
    sleep: int = 0,
    num: int = 1,
    picture: int = 0,
    log_code: bool = False,
    offline: bool = False,
    symon: bool = False,
    alert: bool = False,
    nested_summary: bool = False,
    debounce: bool = False,
    table: bool = False,
    log_artifact: bool = False,
    use_artifact: bool = False,
    save: str = "",
    save_big: bool = False,
    tensorboard: bool = False,
    console: str = "off",  # auto, off, wrap, redirect
):
    if port:
        os.environ["WANDB_SERVICE"] = f"2-12345-tcp-localhost-{port}"

    if num > 0:
        run = wandb.init(
            # id="fogjfyft",
            # resume="allow",
            # project="core",
            # config={"core.yo.mahyo": 420},
            settings=wandb.Settings(
                init_timeout=600,
                mode="offline" if offline else "online",
                console=console,
                # _disable_machine_info=True,
                # program="lol.py",
                # _disable_stats=False,
                # _disable_stats=True,
                _stats_sample_rate_seconds=1,
                _stats_samples_to_average=1,
                _stats_disk_paths=["/System/Volumes/Data"],
                # _stats_disk_paths=["/System/Volumes/Data", "/dev", "/lol"],
                _stats_buffer_size=100 if symon else 0,
                # _async_upload_concurrency_limit=5,
            ),
            sync_tensorboard=tensorboard or None,
        )
        # print(run.settings)
        # print(run.settings.program_relpath, run.settings.program_abspath)

    print("WANDB_SERVICE: ", os.environ.get("WANDB_SERVICE"))

    if save:
        # run.save("1/*.py", policy="live")
        run.save("1/*.py", policy=save)
        # run.save("1/", policy=save)  # doesn't work! and probably shouldn't
        # run.save("1/run_symon.py", policy=save)
        # run.save("1/**", policy=save)

    if save_big:
        # 1 MB:
        # run.save("junk1MB.txt", policy="end")
        # 10 MB:
        run.save("junk10MB.txt", policy="end")
        # 100 MB:
        # run.save("junk.txt", policy="end")
        # 1GB
        # run.save("junk1GB.txt", policy="end")

    if num > 0:
        run.config["core"] = 1337
        # run.config.update({"core": 420}, allow_val_change=True)
        run.config["lol"] = {
            "+img": wandb.Image(
                np.random.randint(0, 255, size=(4, 4, 1), dtype=np.uint8)
            ),
            "+array": np.random.randint(0, 255, size=(4, 4, 1), dtype=np.uint8),
            "+table": wandb.Table(
                columns=["a", "b"],
                data=[[1, 2], [3, 4]],
            ),
            "+dict": {"a": 1, "b": 2},
            "+dict-list": {"a": [1], "b": [2]},
            "+list": [1, 2, 3],
            "+list-int-none": [1, 2, 3, None],
            "+list-int-str": [1, 2, 3, "None"],
            "+list-str": ["1", "2", "3"],
            "+list-str-none": ["1", "2", "3", None],
            "+list-booleans": [True, False, True],
            "+list-none": [None, None, None],
            "+list-diff-types": [1, 2, 3, "a", True],
            "+list-diff-types-none": [1, 2, 3, "a", True, None],
            "+list-dict": [{"a": 1}, {"b": 2}],
            "+list-empty-dict": [{}, {}],
            "+list-set": [{1}, {2}],
            "+list-dict-invalid": [{"a": 1}, {"b": 2}, "lol"],
            "+timestamp": datetime.datetime.now(),
            "+time": Time(datetime.datetime.now()),
            "+bool": True,
            "+none": None,
            "+set": {1, 2, 3},
            "+tuple": (1, 2, 3),
            "+dataframe": pd.DataFrame(
                columns=["a", "b"],
                data=[[1, 2], [3, 4]],
            ),
        }

        input_types = {
            "wb_type": "typedDict",
            "params": {
                "type_map": {
                    "core": {"wb_type": "number"},
                    "lol": {
                        "wb_type": "typedDict",
                        "params": {
                            "type_map": {
                                "+img": {"wb_type": "string"},
                                "+array": {
                                    "wb_type": "list",
                                    "params": {
                                        "element_type": {
                                            "wb_type": "list",
                                            "params": {
                                                "element_type": {
                                                    "wb_type": "list",
                                                    "params": {
                                                        "element_type": {
                                                            "wb_type": "number"
                                                        },
                                                        "length": 1,
                                                    },
                                                },
                                                "length": 4,
                                            },
                                        },
                                        "length": 4,
                                    },
                                },
                                "+table": {"wb_type": "string"},
                                "+dict": {
                                    "wb_type": "typedDict",
                                    "params": {
                                        "type_map": {
                                            "a": {"wb_type": "number"},
                                            "b": {"wb_type": "number"},
                                        }
                                    },
                                },
                                "+list": {
                                    "wb_type": "list",
                                    "params": {
                                        "element_type": {"wb_type": "number"},
                                        "length": 3,
                                    },
                                },
                                "+timestamp": {"wb_type": "string"},
                                "+time": {"wb_type": "string"},
                                "+bool": {"wb_type": "boolean"},
                                "+none": {"wb_type": "none"},
                                "+set": {
                                    "wb_type": "list",
                                    "params": {
                                        "element_type": {"wb_type": "number"},
                                        "length": 3,
                                    },
                                },
                                "+tuple": {
                                    "wb_type": "list",
                                    "params": {
                                        "element_type": {"wb_type": "number"},
                                        "length": 3,
                                    },
                                },
                                "+dataframe": {"wb_type": "string"},
                            }
                        },
                    },
                }
            },
        }
        output_types = {
            "wb_type": "typedDict",
            "params": {
                "type_map": {
                    "a": {"wb_type": "number"},
                    "b": {"wb_type": "number"},
                    "t": {"wb_type": "string"},
                    "picture_0": {
                        "wb_type": "typedDict",
                        "params": {
                            "type_map": {
                                "_type": {"wb_type": "string"},
                                "sha256": {"wb_type": "string"},
                                "size": {"wb_type": "number"},
                                "path": {"wb_type": "string"},
                                "format": {"wb_type": "string"},
                                "width": {"wb_type": "number"},
                                "height": {"wb_type": "number"},
                            }
                        },
                    },
                    "_timestamp": {"wb_type": "number"},
                    "_runtime": {"wb_type": "number"},
                    "_step": {"wb_type": "number"},
                }
            },
        }

        del input_types, output_types

    for i in tqdm.tqdm(range(num)):
        # run.log(dict(a=i, b=i+1), commit=False)
        # msg = "".join(
        #     f"MYYYYYYY OH MY HUNGRINESS LEVEL: {i}-{j}|"
        #     for j in range(3)
        # )
        # print(msg)
        data = dict(a=i, b=i + 1, t=datetime.datetime.now())
        for p in range(picture):
            img = np.random.randint(0, 255, size=(512, 512, 3), dtype=np.uint8)
            data[f"picture_{p}"] = wandb.Image(img)
        run.log(data)
        # time.sleep(0.2)
        # for k in tqdm.tqdm(range(10)):
        #     run.log(dict(c=k))
        #     time.sleep(0.1)

        if debounce:
            for k in range(10):
                run.config.update({"core": 1337 + k + 1}, allow_val_change=True)
                if k == 4:
                    run.config["shmexus"] = 101
                    time.sleep(10)

    time.sleep(sleep)

    if log_artifact:
        # from wandb.sdk.lib.runid import generate_id
        arti = wandb.Artifact(name="noxfile", type="nox")
        arti.add_file(local_path="noxfile.py")
        run.log_artifact(arti)

    if use_artifact:
        # during a run:
        # arti = run.use_artifact("noxfile:latest")
        # outside of a run:
        api = wandb.Api()
        arti = api.artifact("dimaduev/uncategorized/noxfile:latest")

        tmp_dir = tempfile.mkdtemp()
        print("downloading artifact to", tmp_dir)
        arti.download(root=tmp_dir)

    if table:
        tbl = wandb.Table(columns=["image", "label"])
        images = np.random.randint(100, 255, [2, 100, 100, 3], dtype=np.uint8)
        labels = ["panda", "gibbon"]
        [
            tbl.add_data(wandb.Image(image), label)
            for image, label in zip(images, labels)
        ]
        run.log({"classifier_out": tbl})

    if symon:
        system_metrics = run._system_metrics
        print(sorted(list(system_metrics.keys())))
        cpu = system_metrics["cpu"]
        # convert to dataframe [t, value]:
        cpu = pd.DataFrame.from_records(cpu, columns=["time", "percent"])
        print(cpu)

    if log_code:
        run.log_code(root="1")

    if nested_summary:
        summary = {
            "x": 42,
            "tru": {
                "core": 1337,
            },
        }
        run.summary.update(summary)

    if alert:
        run.alert(
            title="wazzup bro?",
            text="I'm just chilling",
            level=wandb.AlertLevel.WARN,
        )

    if tensorboard:
        import tensorflow as tf

        def create_model():
            return tf.keras.models.Sequential(
                [
                    tf.keras.layers.Flatten(input_shape=(28, 28)),
                    tf.keras.layers.Dense(512, activation="relu"),
                    tf.keras.layers.Dropout(0.2),
                    tf.keras.layers.Dense(10, activation="softmax"),
                ]
            )

        mnist = tf.keras.datasets.mnist

        (x_train, y_train), (x_test, y_test) = mnist.load_data()
        x_train, x_test = x_train / 255.0, x_test / 255.0

        model = create_model()
        model.compile(
            optimizer="adam",
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )

        tensorboard_callback = tf.keras.callbacks.TensorBoard(histogram_freq=1)

        model.fit(
            x=x_train,
            y=y_train,
            # epochs=5,
            epochs=1,
            validation_data=(x_test, y_test),
            callbacks=[tensorboard_callback],
        )

    if num > 0 and finish:
        run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--finish", action="store_true")
    parser.add_argument("-s", "--sleep", type=int, default=0)
    parser.add_argument("-p", "--picture", type=int, default=0)
    parser.add_argument("-i", "--num", type=int, default=1)
    parser.add_argument("-c", "--log-code", action="store_true")
    parser.add_argument("-np", "--port", type=str, default="")
    parser.add_argument("-o", "--offline", action="store_true")
    parser.add_argument("-sm", "--symon", action="store_true")
    parser.add_argument("-a", "--alert", action="store_true")
    parser.add_argument("-ns", "--nested-summary", action="store_true")
    parser.add_argument("-d", "--debounce", action="store_true")
    parser.add_argument("-t", "--table", action="store_true")
    parser.add_argument("-la", "--log-artifact", action="store_true")
    parser.add_argument("-ua", "--use-artifact", action="store_true")
    parser.add_argument("-sv", "--save", type=str, default="")
    parser.add_argument("-sb", "--save-big", action="store_true")
    parser.add_argument("-tb", "--tensorboard", action="store_true")
    parser.add_argument(
        "-cn",
        "--console",
        type=str,
        default="off",
        choices=["auto", "off", "wrap", "redirect"],
    )
    args = parser.parse_args()

    main(
        port=args.port,
        finish=args.finish,
        sleep=args.sleep,
        num=args.num,
        picture=args.picture,
        log_code=args.log_code,
        offline=args.offline,
        symon=args.symon,
        alert=args.alert,
        nested_summary=args.nested_summary,
        debounce=args.debounce,
        table=args.table,
        log_artifact=args.log_artifact,
        use_artifact=args.use_artifact,
        save=args.save,
        save_big=args.save_big,
        tensorboard=args.tensorboard,
        console=args.console,
    )
