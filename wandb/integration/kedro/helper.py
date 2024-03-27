import threading

thread_local_storage = threading.local()


def set_wandb_metadata(metadata):
    thread_local_storage.wandb_metadata = metadata


def get_wandb_metadata():
    return getattr(thread_local_storage, "wandb_metadata", None)
