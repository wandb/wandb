from wandb.apis.public.service_api import ServiceApi
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk import wandb_setup

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


def stub_server_features_query(
    wandb_backend_spy: WandbBackendSpy,
    *,
    enabled: list[pb.ServerFeature.ValueType],
) -> None:
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.once(
            content={
                "data": {
                    "serverInfo": {
                        "features": [
                            {
                                "name": pb.ServerFeature.Name(feature),
                                "isEnabled": True,
                            }
                            for feature in enabled
                        ]
                    }
                }
            }
        ),
    )


def test_feature_flags(wandb_backend_spy: WandbBackendSpy):
    stub_server_features_query(
        wandb_backend_spy,
        enabled=[pb.ServerFeature.CLIENT_IDS],
    )

    api = ServiceApi(wandb_setup.singleton().settings)
    enabled = api.feature_enabled(pb.ServerFeature.CLIENT_IDS)

    assert enabled


def test_feature_flags_timeout(wandb_backend_spy: WandbBackendSpy):
    stub_server_features_query(
        wandb_backend_spy,
        enabled=[pb.ServerFeature.CLIENT_IDS],
    )

    # Should return False on timeout.
    api = ServiceApi(wandb_setup.singleton().settings)
    enabled = api.feature_enabled(pb.ServerFeature.CLIENT_IDS, timeout=0)

    assert not enabled


def test_feature_flags_error(wandb_backend_spy: WandbBackendSpy):
    gql = wandb_backend_spy.gql
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.once(content={}, status=400),
    )

    # Should return False on error.
    api = ServiceApi(wandb_setup.singleton().settings)
    enabled = api.feature_enabled(pb.ServerFeature.CLIENT_IDS)

    assert not enabled
