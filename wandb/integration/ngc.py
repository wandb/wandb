import os


def active():
    return job_id() and run_id()


def job_id():
    return os.getenv("NGC_JOB_ID")


def run_id():
    return os.getenv("NGC_RUN_ID")


def dataset_info():
    return os.getenv("NGC_DATASETS_INFO")
