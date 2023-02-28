# from wandb.sdk.launch.environment.aws_environment import (
#     AwsEnvironment,
# )
# from wandb.sdk.launch.registry.elastic_container_registry import (
#     ElasticContainerRegistry,
# )
# config_source = dict(
#    #  region="us-east-2",
#     profile="default",
#     kubernetes_secret="hello",
# )
# aws_env = AwsEnvironment.from_default()
# ecr_reg = ElasticContainerRegistry("ben-launch-registry", aws_env)
# print(ecr_reg.uri)
# print(ecr_reg.get_username_password())
import logging
import sys

from wandb.sdk.launch.environment.gcp_environment import GcpEnvironment

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.DEBUG,
)

gcp_env = GcpEnvironment("us-central1", "smle-enterprise-hackathon")


# # gcp_env.upload_file("tox.ini", "gs://launch-test/tox.ini")
# gcp_env.upload_dir("test-results", "gs://launch-test/tests")
