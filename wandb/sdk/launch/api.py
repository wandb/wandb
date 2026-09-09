"""The public API extended with the operations of `wandb launch` and its agent."""

from __future__ import annotations

import json
import socket
from typing import Any

import wandb
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public.api import Api
from wandb.errors import CommError
from wandb.proto.wandb_api_pb2 import (
    ApiRequest,
    CreateRunQueueRequest,
    RunQueueOperationRequest,
    StopRunRequest,
)


class LaunchApi(Api):
    """`wandb.Api` plus the run queue and launch agent operations."""

    @normalize_exceptions
    def get_project_run_queues(self, entity: str, project: str) -> list[dict[str, str]]:
        query = """
        query ProjectRunQueues($entity: String!, $projectName: String!){
            project(entityName: $entity, name: $projectName) {
                runQueues {
                    id
                    name
                    createdBy
                    access
                }
            }
        }
        """
        res = self._service_api.execute_graphql(
            query, {"projectName": project, "entity": entity}
        )
        if res.get("project") is None:
            # circular dependency: (LAUNCH_DEFAULT_PROJECT = model-registry)
            if project == "model-registry":
                msg = (
                    f"Error fetching run queues for {entity} "
                    "check that you have access to this entity and project"
                )
            else:
                msg = (
                    f"Error fetching run queues for {entity}/{project} "
                    "check that you have access to this entity and project"
                )

            raise Exception(msg)

        project_run_queues: list[dict[str, str]] = res["project"]["runQueues"]
        return project_run_queues

    @normalize_exceptions
    def push_to_run_queue_by_name(
        self,
        entity: str,
        project: str,
        queue_name: str,
        run_spec: str,
        template_variables: dict[str, int | float | str] | None,
        priority: int | None = None,
    ) -> dict[str, Any] | None:
        mutation_params = """
            $entityName: String!,
            $projectName: String!,
            $queueName: String!,
            $runSpec: JSONString!
        """

        mutation_input = """
            entityName: $entityName,
            projectName: $projectName,
            queueName: $queueName,
            runSpec: $runSpec
        """

        variables: dict[str, Any] = {
            "entityName": entity,
            "projectName": project,
            "queueName": queue_name,
            "runSpec": run_spec,
        }
        if priority is not None:
            variables["priority"] = priority
            mutation_params += ", $priority: Int"
            mutation_input += ", priority: $priority"

        if template_variables is not None:
            variables.update({"templateVariableValues": json.dumps(template_variables)})
            mutation_params += ", $templateVariableValues: JSONString"
            mutation_input += ", templateVariableValues: $templateVariableValues"

        mutation = f"""
        mutation pushToRunQueueByName(
          {mutation_params}
        ) {{
            pushToRunQueueByName(
                input: {{
                    {mutation_input}
                }}
            ) {{
                runQueueItemId
                runSpec
            }}
        }}
        """

        try:
            result: dict[str, Any] | None = self._service_api.execute_graphql(
                mutation, variables
            ).get("pushToRunQueueByName")
        except Exception as e:
            if (
                'Cannot query field "runSpec" on type "PushToRunQueueByNamePayload"'
                not in str(e)
            ):
                return None
        else:
            if not result:
                return None
            if result.get("runSpec"):
                result["runSpec"] = json.loads(str(result["runSpec"]))
            return result

        mutation_no_runspec = """
        mutation pushToRunQueueByName(
            $entityName: String!,
            $projectName: String!,
            $queueName: String!,
            $runSpec: JSONString!,
        ) {
            pushToRunQueueByName(
                input: {
                    entityName: $entityName,
                    projectName: $projectName,
                    queueName: $queueName,
                    runSpec: $runSpec
                }
            ) {
                runQueueItemId
            }
        }
        """

        try:
            result = self._service_api.execute_graphql(
                mutation_no_runspec, variables
            ).get("pushToRunQueueByName")
        except Exception:
            result = None

        return result

    @normalize_exceptions
    def push_to_run_queue(
        self,
        queue_name: str,
        launch_spec: dict[str, str],
        template_variables: dict | None,
        project_queue: str,
        priority: int | None = None,
    ) -> dict[str, Any] | None:
        entity = launch_spec.get("queue_entity") or launch_spec["entity"]
        run_spec = json.dumps(launch_spec)

        push_result = self.push_to_run_queue_by_name(
            entity, project_queue, queue_name, run_spec, template_variables, priority
        )

        if push_result:
            return push_result

        if priority is not None:
            # Cannot proceed with legacy method if priority is set
            return None

        """ Legacy Method """
        queues_found = self.get_project_run_queues(entity, project_queue)
        matching_queues = [
            q
            for q in queues_found
            if q["name"] == queue_name
            # ensure user has access to queue
            and (
                # TODO: User created queues in the UI have USER access
                q["access"] in ["PROJECT", "USER"]
                or q["createdBy"] == self.default_entity
            )
        ]
        if not matching_queues:
            # in the case of a missing default queue. create it
            if queue_name == "default":
                wandb.termlog(
                    f"No default queue existing for entity: {entity} in project: {project_queue}, creating one."
                )
                create_queue_response = self._service_api.send_api_request(
                    ApiRequest(
                        run_queue_operation_request=RunQueueOperationRequest(
                            create_run_queue_request=CreateRunQueueRequest(
                                entity=launch_spec["entity"],
                                project=project_queue,
                                queue_name=queue_name,
                                access="PROJECT",
                            )
                        )
                    )
                )
                queue_result = create_queue_response.run_queue_operation_response.create_run_queue_response
                if not queue_result.success or not queue_result.queue_id:
                    wandb.termerror(
                        f"Unable to create default queue for entity: {entity} on project: {project_queue}. Run could not be added to a queue"
                    )
                    return None
                queue_id = queue_result.queue_id

            else:
                if project_queue == "model-registry":
                    _msg = f"Unable to push to run queue {queue_name}. Queue not found."
                else:
                    _msg = f"Unable to push to run queue {project_queue}/{queue_name}. Queue not found."
                wandb.termwarn(_msg)
                return None
        elif len(matching_queues) > 1:
            wandb.termerror(
                f"Unable to push to run queue {queue_name}. More than one queue found with this name."
            )
            return None
        else:
            queue_id = matching_queues[0]["id"]
        spec_json = json.dumps(launch_spec)
        variables = {"queueID": queue_id, "runSpec": spec_json}

        mutation_params = """
            $queueID: ID!,
            $runSpec: JSONString!
        """
        mutation_input = """
            queueID: $queueID,
            runSpec: $runSpec
        """
        if template_variables is not None:
            mutation_params += ", $templateVariableValues: JSONString"
            mutation_input += ", templateVariableValues: $templateVariableValues"
            variables.update({"templateVariableValues": json.dumps(template_variables)})

        mutation = f"""
        mutation pushToRunQueue(
            {mutation_params}
            ) {{
            pushToRunQueue(
                input: {{{mutation_input}}}
            ) {{
                runQueueItemId
            }}
        }}
        """

        response = self._service_api.execute_graphql(mutation, variables)
        if not response.get("pushToRunQueue"):
            raise CommError(f"Error pushing run queue item to queue {queue_name}.")

        result: dict[str, Any] | None = response["pushToRunQueue"]
        return result

    @normalize_exceptions
    def pop_from_run_queue(
        self,
        queue_name: str,
        entity: str | None = None,
        project: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        mutation = """
        mutation popFromRunQueue($entity: String!, $project: String!, $queueName: String!, $launchAgentId: ID)  {
            popFromRunQueue(input: {
                entityName: $entity,
                projectName: $project,
                queueName: $queueName,
                launchAgentId: $launchAgentId
            }) {
                runQueueItemId
                runSpec
            }
        }
        """
        response = self._service_api.execute_graphql(
            mutation,
            {
                "entity": entity,
                "project": project,
                "queueName": queue_name,
                "launchAgentId": agent_id,
            },
        )
        result: dict[str, Any] | None = response["popFromRunQueue"]
        return result

    @normalize_exceptions
    def ack_run_queue_item(self, item_id: str, run_id: str | None = None) -> bool:
        mutation = """
        mutation ackRunQueueItem($itemId: ID!, $runId: String!)  {
            ackRunQueueItem(input: { runQueueItemId: $itemId, runName: $runId }) {
                success
            }
        }
        """
        response = self._service_api.execute_graphql(
            mutation, {"itemId": item_id, "runId": str(run_id)}
        )
        if not response["ackRunQueueItem"]["success"]:
            raise CommError(
                "Error acking run queue item. Item may have already been acknowledged by another process"
            )
        result: bool = response["ackRunQueueItem"]["success"]
        return result

    @normalize_exceptions
    def fail_run_queue_item(
        self,
        run_queue_item_id: str,
        message: str,
        stage: str,
        file_paths: list[str] | None = None,
    ) -> bool:
        variables: dict[str, str | (list[str] | None)] = {
            "runQueueItemId": run_queue_item_id,
            "message": message,
            "stage": stage,
        }
        if file_paths is not None:
            variables["filePaths"] = file_paths
        mutation = """
        mutation failRunQueueItem($runQueueItemId: ID!, $message: String!, $stage: String!, $filePaths: [String!]) {
            failRunQueueItem(
                input: {
                    runQueueItemId: $runQueueItemId
                    message: $message
                    stage: $stage
                    filePaths: $filePaths
                }
            ) {
                success
            }
        }
        """
        response = self._service_api.execute_graphql(mutation, variables)
        result: bool = response["failRunQueueItem"]["success"]
        return result

    @normalize_exceptions
    def update_run_queue_item_warning(
        self,
        run_queue_item_id: str,
        message: str,
        stage: str,
        file_paths: list[str] | None = None,
    ) -> bool:
        mutation = """
        mutation updateRunQueueItemWarning($runQueueItemId: ID!, $message: String!, $stage: String!, $filePaths: [String!]) {
            updateRunQueueItemWarning(
                input: {
                    runQueueItemId: $runQueueItemId
                    message: $message
                    stage: $stage
                    filePaths: $filePaths
                }
            ) {
                success
            }
        }
        """
        response = self._service_api.execute_graphql(
            mutation,
            {
                "runQueueItemId": run_queue_item_id,
                "message": message,
                "stage": stage,
                "filePaths": file_paths,
            },
        )
        result: bool = response["updateRunQueueItemWarning"]["success"]
        return result

    @normalize_exceptions
    def create_launch_agent(
        self,
        entity: str,
        project: str,
        queues: list[str],
        agent_config: dict[str, Any],
        version: str,
    ) -> dict:
        project_queues = self.get_project_run_queues(entity, project)
        if not project_queues:
            # create default queue if it doesn't already exist
            response = self._service_api.send_api_request(
                ApiRequest(
                    run_queue_operation_request=RunQueueOperationRequest(
                        create_run_queue_request=CreateRunQueueRequest(
                            entity=entity,
                            project=project,
                            queue_name="default",
                            access="PROJECT",
                        )
                    )
                )
            )
            default = response.run_queue_operation_response.create_run_queue_response
            if not default.success or not default.queue_id:
                raise CommError(
                    f"Unable to create default queue for {entity}/{project}. No queues for agent to poll"
                )
            project_queues = [{"id": default.queue_id, "name": "default"}]
        polling_queue_ids = [
            q["id"] for q in project_queues if q["name"] in queues
        ]  # filter to poll specified queues
        if len(polling_queue_ids) != len(queues):
            raise CommError(
                f"Could not start launch agent: Not all of requested queues ({', '.join(queues)}) found. "
                f"Available queues for this project: {','.join([q['name'] for q in project_queues])}"
            )

        hostname = socket.gethostname()

        variables = {
            "entity": entity,
            "project": project,
            "queues": polling_queue_ids,
            "hostname": hostname,
            "agentConfig": json.dumps(agent_config),
            "version": version,
        }

        mutation_params = """
            $entity: String!,
            $project: String!,
            $queues: [ID!]!,
            $hostname: String!,
            $agentConfig: JSONString,
            $version: String
        """

        mutation_input = """
            entityName: $entity,
            projectName: $project,
            runQueues: $queues,
            hostname: $hostname,
            agentConfig: $agentConfig,
            version: $version
        """

        mutation = f"""
            mutation createLaunchAgent(
                {mutation_params}
            ) {{
                createLaunchAgent(
                    input: {{
                        {mutation_input}
                    }}
                ) {{
                    launchAgentId
                }}
            }}
            """
        result: dict = self._service_api.execute_graphql(mutation, variables)[
            "createLaunchAgent"
        ]
        return result

    @normalize_exceptions
    def update_launch_agent_status(
        self,
        agent_id: str,
        status: str,
    ) -> dict:
        mutation = """
            mutation updateLaunchAgent($agentId: ID!, $agentStatus: String){
                updateLaunchAgent(
                    input: {
                        launchAgentId: $agentId
                        agentStatus: $agentStatus
                    }
                ) {
                    success
                }
            }
            """
        result: dict = self._service_api.execute_graphql(
            mutation, {"agentId": agent_id, "agentStatus": status}
        )["updateLaunchAgent"]
        return result

    @normalize_exceptions
    def get_launch_agent(self, agent_id: str) -> dict:
        query = """
            query LaunchAgent($agentId: ID!) {
                launchAgent(id: $agentId) {
                    id
                    name
                    runQueues
                    hostname
                    agentStatus
                    stopPolling
                    heartbeatAt
                }
            }
            """
        result: dict = self._service_api.execute_graphql(query, {"agentId": agent_id})[
            "launchAgent"
        ]
        return result

    @normalize_exceptions
    def entity_is_team(self, entity: str) -> bool:
        query = """
            query EntityIsTeam($entity: String!) {
                entity(name: $entity) {
                    id
                    isTeam
                }
            }
            """
        res = self._service_api.execute_graphql(query, {"entity": entity})
        if res.get("entity") is None:
            raise Exception(
                f"Error fetching entity {entity} "
                "check that you have access to this entity"
            )

        is_team: bool = res["entity"]["isTeam"]
        return is_team

    @normalize_exceptions
    def check_stop_requested(
        self, project_name: str, entity_name: str, run_id: str
    ) -> bool:
        query = """
        query RunStoppedStatus($projectName: String, $entityName: String, $runId: String!) {
            project(name:$projectName, entityName:$entityName) {
                run(name:$runId) {
                    stopped
                }
            }
        }
        """
        response = self._service_api.execute_graphql(
            query,
            {"projectName": project_name, "entityName": entity_name, "runId": run_id},
        )

        project = response.get("project", None)
        if not project:
            return False
        run = project.get("run", None)
        if not run:
            return False

        status: bool = run["stopped"]
        return status

    @normalize_exceptions
    def get_run_state(self, entity: str, project: str, name: str) -> str:
        query = """
        query RunState(
            $project: String!,
            $entity: String!,
            $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    state
                }
            }
        }
        """
        res = self._service_api.execute_graphql(
            query, {"project": project, "entity": entity, "name": name}
        )
        if res.get("project") is None or res["project"].get("run") is None:
            raise CommError(f"Error fetching run state for {entity}/{project}/{name}.")
        run_state: str = res["project"]["run"]["state"]
        return run_state

    @normalize_exceptions
    def stop_run(self, run_id: str) -> bool:
        """Request that the run with the given storage ID stop."""
        self._service_api.send_api_request(
            ApiRequest(stop_run_request=StopRunRequest(storage_id=run_id))
        )
        return True
