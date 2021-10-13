import wandb.data_types as data_types


def get_types():
    classes = map(data_types.__dict__.get, data_types.__all__)
    types = []
    for cls in classes:
        if hasattr(cls, "_log_type") and cls._log_type is not None:
            types.append(cls._log_type)
    # add table-file type because this is a special case
    # that does not have a matching _log_type for artifacts
    # and files
    types.append("table-file")
    return types


WANDB_TYPES = get_types()


def metric_is_wandb_dict(metric):
    return "_type" in list(metric.keys()) and metric["_type"] in WANDB_TYPES
