import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from wandb import Api, util

reset_path = util.vendor_setup()

from wandb_gql import gql

_FETCH_PROJECT_TRIGGERS = gql(
    """
    query FetchProjectTriggers($projectName: String!, $entityName: String!) {
        project(name: $projectName, entityName: $entityName) {
            id
            triggers {
                id
                name
                createdAt
                enabled
                createdBy {
                    id
                    name
                }
                description
                scope {
                    __typename
                    ... on Project {
                        id
                        name
                    }
                    ... on ArtifactSequence {
                        id
                        name
                        project {
                            id
                            name
                        }
                    }
                    ... on ArtifactPortfolio {
                        id
                        name
                        project {
                            id
                            name
                        }
                    }
                }
                triggeringCondition {
                    __typename
                    ... on FilterEventTriggeringCondition {
                        eventType
                        filter
                    }
                }
                triggeredAction {
                    __typename
                    ... on QueueJobTriggeredAction {
                        queue {
                            id
                            name
                        }
                        template
                    }
                    ... on NotificationTriggeredAction {
                        integration {
                            id
                        }
                        title
                        message
                        severity
                    }
                    ... on GenericWebhookTriggeredAction {
                        integration {
                            __typename
                            ... on GenericWebhookIntegration {
                                id
                                name
                                urlEndpoint
                                accessTokenRef
                                secretRef
                                createdAt
                            }
                        }
                        requestPayload
                    }
                }
            }
        }
    }
    """
)

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")


def get_automations() -> Any:
    project_name = "wandb-registry-model"
    entity_name = "wandb_Y72QKAKNEFI3G"

    api = Api(
        overrides={"base_url": "https://api.wandb.ai"},
        api_key=os.environ["WANDB_API_KEY"],
    )

    results = api.client.execute(
        _FETCH_PROJECT_TRIGGERS,
        variable_values={
            "projectName": project_name,
            "entityName": entity_name,
        },
    )

    print(json.dumps(results, indent=2))

    # projects = api.projects(entity="wandb").convert_objects()
    # print(projects)


get_automations()
