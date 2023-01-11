import os
import sys
import time
from filecmp import dircmp

import wandb

# These should have bucket versioning enabled
GCS_BUCKET = "gs://wandb-experiments"
S3_BUCKET = "s3://kubeml"
PREFIX = wandb.util.generate_id()
GCS_NAME = f"gcs-artifact-{PREFIX}"
S3_NAME = f"s3-artifact-{PREFIX}"
GCS_REMOTE = f"{GCS_BUCKET}/artifact-versions/{PREFIX}"
S3_REMOTE = f"{S3_BUCKET}/artifact-versions/{PREFIX}"
ENTITY = "wandb"


def update_versions(version=1):
    root = f"./versions{version}"
    os.makedirs(root, exist_ok=True)
    with open(f"{root}/every.txt", "w") as f:
        f.write(f"{PREFIX} every version {version}")
    if version % 2 == 0:
        with open(f"{root}/even.txt", "w") as f:
            f.write(f"{PREFIX} even version {version}")
    else:
        with open(f"{root}/odd.txt", "w") as f:
            f.write(f"{PREFIX} odd version {version}")
    return root


def sync_buckets(root):
    # Sync up
    gs = (root, GCS_REMOTE)
    s3 = (root, S3_REMOTE)
    os.system("gsutil rsync %s %s" % gs)
    os.system("aws s3 sync %s %s" % s3)
    # Sync down
    gs = (GCS_REMOTE, root)
    s3 = (S3_REMOTE, root)
    os.system("gsutil rsync %s %s" % gs)
    os.system("aws s3 sync %s %s" % s3)


def log_artifacts():
    gcs_art = wandb.Artifact(name=GCS_NAME, type="dataset")
    s3_art = wandb.Artifact(name=S3_NAME, type="dataset")
    gcs_art.add_reference(GCS_REMOTE)
    s3_art.add_reference(S3_REMOTE)
    run = wandb.init(project="artifact-references", entity=ENTITY, reinit=True)
    run.log_artifact(gcs_art)
    run.log_artifact(s3_art)
    return gcs_art, s3_art


def download_artifacts(gcs_alias="v0", s3_alias="v0"):
    api = wandb.Api()
    gcs_art = api.artifact(
        name=f"{ENTITY}/artifact-references/{GCS_NAME}:{gcs_alias}", type="dataset"
    )
    s3_art = api.artifact(
        name=f"{ENTITY}/artifact-references/{S3_NAME}:{s3_alias}", type="dataset"
    )
    gcs_art.download()
    s3_art.download()
    return gcs_art, s3_art


def main(argv):
    v1_root = update_versions()
    sync_buckets(v1_root)
    log_artifacts()
    v2_root = update_versions(2)
    sync_buckets(v2_root)
    log_artifacts()

    print("Sleeping for arts to get processed...")
    time.sleep(1)

    gcs_v1_art, s3_v1_art = download_artifacts()
    gcs_v2_art, s3_v2_art = download_artifacts("v1", "v1")
    gcs_latest_art, s3_latest_art = download_artifacts("latest", "latest")

    v1_gcs_cmp = dircmp(gcs_v1_art.cache_dir, v1_root)
    v1_s3_cmp = dircmp(s3_v1_art.cache_dir, v1_root)

    v2_gcs_cmp = dircmp(gcs_v2_art.cache_dir, v2_root)
    v2_s3_cmp = dircmp(s3_v2_art.cache_dir, v2_root)

    latest_gcs_cmp = dircmp(gcs_latest_art.cache_dir, v2_root)
    latest_s3_cmp = dircmp(s3_latest_art.cache_dir, v2_root)

    print("v0 GCS")
    v1_gcs_cmp.report()

    print("v0 S3")
    v1_s3_cmp.report()

    print("v1 GCS")
    v2_gcs_cmp.report()

    print("v1 S3")
    v2_s3_cmp.report()

    print("latest GCS")
    latest_gcs_cmp.report()

    print("latest S3")
    latest_s3_cmp.report()

    assert v1_gcs_cmp.common == ["even.txt", "every.txt", "odd.txt"]
    assert v1_s3_cmp.common == ["even.txt", "every.txt", "odd.txt"]

    assert v2_gcs_cmp.common == ["even.txt", "every.txt", "odd.txt"]
    assert v2_s3_cmp.common == ["even.txt", "every.txt", "odd.txt"]

    assert latest_gcs_cmp.common == ["even.txt", "every.txt", "odd.txt"]
    assert latest_s3_cmp.common == ["even.txt", "every.txt", "odd.txt"]


if __name__ == "__main__":
    main(sys.argv)
