import wandb.data_types as data_types


def get_types():
    classes = map(data_types.__dict__.get, data_types.__all__)
    types = []
    print(classes)
    for cls in classes:
        if hasattr(cls, "log_type") and cls.log_type is not None:
            print("log", cls.__name__, cls.log_type)
            types.append(cls.log_type)
        elif hasattr(cls, "artifact_type"):
            print("arti", cls.__name__, cls.artifact_type)
            types.append(cls.artifact_type)
    return types


WANDB_TYPES = get_types()


def metric_is_wandb_dict(metric):
    if "_type" in list(metric.keys()) and metric["_type"] in WANDB_TYPES:
        return True
    return False
