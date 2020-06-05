import random
import os
import sys
from filecmp import dircmp

import wandb

# These should have bucket versioning enabled
GCS_BUCKET = "gs://wandb-experiments"
S3_BUCKET = "s3://kubeml"
PREFIX = wandb.util.generate_id()
GCS_NAME = "gcs-artifact-%s" % PREFIX
S3_NAME = "s3-artifact-%s" % PREFIX
GCS_REMOTE = '%s/artifact-versions/%s' % (GCS_BUCKET, PREFIX)
S3_REMOTE = '%s/artifact-versions/%s' % (S3_BUCKET, PREFIX)
ENTITY = "wandb"

def update_versions(version=1):
    root = './versions/%s' % version
    os.makedirs(root, exist_ok=True)
    with open('%s/every.txt' % root, 'w') as f:
        f.write('every version '+str(version))
    if version % 2 == 0:
        with open('%s/even.txt' % root, 'w') as f:
            f.write('even version '+str(version))
    else:
        with open('%s/odd.txt' % root, 'w') as f:
            f.write('odd version '+str(version))
    return root

def sync_buckets(root):
    os.system('gsutil rsync %s %s' % (root, GCS_REMOTE))
    os.system('aws s3 sync %s %s' % (root, S3_REMOTE))

def log_artifacts():
    gcs_art = wandb.Artifact(name=GCS_NAME, type="dataset")
    s3_art = wandb.Artifact(name=S3_NAME, type="dataset")
    gcs_art.add_reference(GCS_REMOTE)
    s3_art.add_reference(S3_REMOTE)
    run = wandb.init(project="artifact-references", entity=ENTITY, reinit=True)
    run.log_artifact(gcs_art)
    run.log_artifact(s3_art)
    return gcs_art, s3_art

def download_artifacts(gcs_alias="v1", s3_alias="v1"):
    api = wandb.Api()
    api.artifact(type="dataset", name="vanpelt/refcheck/gs-ref:v3")
    gcs_art = api.artifact(name="%s/artifact-references/%s:%s" %(ENTITY, GCS_NAME, gcs_alias), type="dataset")
    s3_art = api.artifact(name="%s/artifact-references/%s:%s" %(ENTITY, S3_NAME, s3_alias), type="dataset")
    gcs_art.download()
    s3_art.download()
    return gcs_art, s3_art

v1_root = update_versions()
sync_buckets(v1_root)
log_artifacts()
v2_root = update_versions(2)
sync_buckets(v2_root)
log_artifacts()

gcs_v1_art, s3_v1_art = download_artifacts()
gcs_v2_art, s3_v2_art = download_artifacts("v2", "v2")
gcs_latest_art, s3_latest_art = download_artifacts("latest", "latest")


v1_gcs_cmp = dircmp(gcs_v1_art.cache_dir, v1_root)
v1_s3_cmp = dircmp(s3_v1_art.cache_dir, v1_root)

v2_gcs_cmp = dircmp(gcs_v2_art.cache_dir, v2_root)
v2_s3_cmp = dircmp(s3_v2_art.cache_dir, v2_root)

latest_gcs_cmp = dircmp(gcs_latest_art.cache_dir, v2_root)
latest_s3_cmp = dircmp(s3_latest_art.cache_dir, v2_root)

print("v1 GCS")
v1_gcs_cmp.report()

print("v1 S3")
v1_s3_cmp.report()

print("v2 GCS")
v2_gcs_cmp.report()

print("v2 S3")
v2_s3_cmp.report()

print("latest GCS")
latest_gcs_cmp.report()

print("latest S3")
latest_s3_cmp.report()

# assert v1_gcs_cmp.common == []
