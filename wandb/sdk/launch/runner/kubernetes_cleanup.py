"""Kubernetes resource cleanup for orphaned auxiliary resources.

This module handles periodic cleanup of auxiliary resources (services, deployments,
network policies, etc.) that may be left behind after an agent restart or crash.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Set

import kubernetes_asyncio
from kubernetes_asyncio.client import ApiException

import wandb
from wandb.sdk.launch.runner import kubernetes_runner
from wandb.sdk.launch.utils import LOG_PREFIX, get_kube_context_and_api_client

_logger = logging.getLogger(__name__)


class KubernetesResourceCleanup:
    """Manages cleanup of orphaned Kubernetes resources.

    This class handles cleanup of orphaned auxiliary resources (services, deployments, etc.)
    that were left behind after an agent restart or crash.

    The cleanup process:
    1. Scans monitored namespaces
    2. Identifies auxiliary resources without active primary Jobs
    3. Deletes resources older than a minimum age threshold
    """

    def __init__(
        self,
        minimum_resource_age_seconds: int = 900,  # 15 minutes
        monitored_namespaces: Optional[str] = None,
    ):
        """Initialize the cleanup manager.

        Args:
            minimum_resource_age_seconds: Minimum age before resource deletion (default: 900)
            monitored_namespaces: Comma-separated list of namespaces to monitor
                                 (default: reads from WANDB_LAUNCH_MONITORED_NAMESPACES env var,
                                  or "default,wandb" if not set)
        """
        self._minimum_age = minimum_resource_age_seconds

        # Parse monitored namespaces from parameter or environment variable
        if monitored_namespaces is None:
            monitored_namespaces = os.environ.get(
                "WANDB_LAUNCH_MONITORED_NAMESPACES", "default,wandb"
            )

        self._monitored_namespaces: Set[str] = set(
            ns.strip() for ns in monitored_namespaces.split(",") if ns.strip()
        )

        wandb.termlog(
            f"{LOG_PREFIX}Initialized resource cleanup with min_age={minimum_resource_age_seconds}s, "
            f"namespaces={sorted(self._monitored_namespaces)}"
        )

    async def run_cleanup_cycle(self) -> None:
        """Execute one cleanup cycle across all monitored namespaces.

        This method is called periodically by the agent's main loop.
        """
        if not self._monitored_namespaces:
            _logger.debug("No namespaces to clean, skipping cycle")
            return

        wandb.termlog(
            f"{LOG_PREFIX}Starting cleanup cycle for {len(self._monitored_namespaces)} namespace(s): "
            f"{', '.join(sorted(self._monitored_namespaces))}"
        )

        for namespace in self._monitored_namespaces:
            try:
                await self._cleanup_namespace(namespace)
            except Exception as e:
                _logger.warning(
                    f"Failed to clean namespace {namespace}: {e}", exc_info=True
                )

        wandb.termlog(f"{LOG_PREFIX}Cleanup cycle completed")

    async def _cleanup_namespace(self, namespace: str) -> None:
        """Clean orphaned resources in a single namespace.

        Args:
            namespace: Kubernetes namespace to clean
        """
        wandb.termlog(f"{LOG_PREFIX}[cleanup] start namespace cleanup for {namespace}")

        # Initialize Kubernetes clients
        try:
            wandb.termlog(f"{LOG_PREFIX}[cleanup] acquiring kube context/api client")
            _, api_client = await get_kube_context_and_api_client(
                kubernetes_asyncio, {}
            )
            wandb.termlog(f"{LOG_PREFIX}[cleanup] acquired api client: {api_client}")
        except Exception as e:
            _logger.warning(f"Failed to get Kubernetes API client: {e}")
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] aborting {namespace} cleanup due to kube client error: {e}"
            )
            return

        batch_api = kubernetes_asyncio.client.BatchV1Api(api_client)
        core_api = kubernetes_asyncio.client.CoreV1Api(api_client)
        apps_api = kubernetes_asyncio.client.AppsV1Api(api_client)
        network_api = kubernetes_asyncio.client.NetworkingV1Api(api_client)

        # Get all active primary Jobs (those with run-id labels)
        wandb.termlog(f"{LOG_PREFIX}[cleanup] fetching active run ids in {namespace}")
        active_run_ids = await self._get_active_job_run_ids(batch_api, namespace)
        if active_run_ids is None:
            # Failed to get active jobs - skip this namespace for safety
            _logger.warning(
                f"Unable to retrieve active jobs from {namespace}, "
                "skipping cleanup to avoid deleting active resources"
            )
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] skipping cleanup for {namespace}: active jobs unknown"
            )
            return

        if active_run_ids:
            _logger.debug(
                f"Found {len(active_run_ids)} active job(s) in {namespace}: "
                f"{', '.join(sorted(active_run_ids))}"
            )
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] active jobs in {namespace}: {sorted(active_run_ids)}"
            )
        else:
            _logger.debug(f"No active jobs found in {namespace}")
            wandb.termlog(f"{LOG_PREFIX}[cleanup] no active jobs in {namespace}")

        # Find all orphaned auxiliary resources
        wandb.termlog(
            f"{LOG_PREFIX}[cleanup] scanning {namespace} for orphaned resources"
        )
        orphaned_uuids = await self._find_orphaned_uuids(
            core_api,
            apps_api,
            network_api,
            batch_api,
            namespace,
            active_run_ids,
        )

        if not orphaned_uuids:
            _logger.debug(f"No orphaned resources found in {namespace}")
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] no orphaned resources detected in {namespace}"
            )
            return

        wandb.termlog(
            f"{LOG_PREFIX}Found {len(orphaned_uuids)} orphaned resource group(s) in {namespace}"
        )

        # Delete all resources for each orphaned UUID concurrently
        async def delete_uuid(uuid_val: str) -> None:
            """Delete resources for a single UUID."""
            try:
                await kubernetes_runner.delete_auxiliary_resources_by_label(
                    apps_api,
                    core_api,
                    network_api,
                    batch_api,
                    namespace,
                    uuid_val,
                )
                wandb.termlog(
                    f"{LOG_PREFIX}Cleaned up orphaned resources with UUID {uuid_val} in {namespace}"
                )
            except Exception as e:
                _logger.warning(
                    f"Failed to cleanup UUID {uuid_val} in {namespace}: {e}"
                )
                wandb.termlog(
                    f"{LOG_PREFIX}[cleanup] failed cleanup for UUID {uuid_val} in {namespace}: {e}"
                )

        # execute deletions concurrently
        wandb.termlog(
            f"{LOG_PREFIX}[cleanup] deleting {len(orphaned_uuids)} orphaned resource group(s) in {namespace}"
        )
        await asyncio.gather(*[delete_uuid(uuid_val) for uuid_val in orphaned_uuids])
        wandb.termlog(f"{LOG_PREFIX}[cleanup] completed cleanup for {namespace}")

    async def _get_active_job_run_ids(
        self, batch_api: "kubernetes_asyncio.client.BatchV1Api", namespace: str
    ) -> Optional[Set[str]]:
        """Get run-ids of all active primary Jobs in a namespace.

        Uses dual-source detection:
        1. Kubernetes Jobs (authoritative source - what's actually running)
        2. Agent's job tracker (includes jobs being launched but not yet in K8s)

        Args:
            batch_api: Kubernetes Batch API client
            namespace: Kubernetes namespace

        Returns:
            Set of active run-ids, or None if Kubernetes query failed
        """
        active_run_ids = set()

        # Source 1: Query Kubernetes for active Jobs
        wandb.termlog(f"{LOG_PREFIX}[cleanup] listing jobs in {namespace}")
        try:
            jobs = await batch_api.list_namespaced_job(
                namespace=namespace,
                label_selector="wandb.ai/resource-role=primary",
            )

            for job in jobs.items:
                run_id = job.metadata.labels.get("wandb.ai/run-id")
                if run_id:
                    active_run_ids.add(run_id)
                    wandb.termlog(
                        f"{LOG_PREFIX}[cleanup] active job detected run-id={run_id} namespace={namespace}"
                    )

        except ApiException as e:
            _logger.warning(
                f"Failed to list jobs in {namespace}: {e}. "
                "Skipping cleanup for this namespace for safety."
            )
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] ApiException listing jobs in {namespace}: {e}"
            )
            return None
        except Exception as e:
            _logger.warning(
                f"Unexpected error listing jobs in {namespace}: {e}", exc_info=True
            )
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] unexpected error listing jobs in {namespace}: {e}"
            )
            return None

        # Source 2: Get run-ids from agent's job tracker (for launching jobs)
        # This catches the window where auxiliary resources exist but Job doesn't yet
        try:
            from wandb.sdk.launch.agent.agent import LaunchAgent

            if LaunchAgent.initialized():
                agent_run_ids = LaunchAgent.get_active_run_ids()
                if agent_run_ids:
                    active_run_ids.update(agent_run_ids)
                    _logger.debug(
                        f"Added {len(agent_run_ids)} run-ids from agent job tracker"
                    )
                    wandb.termlog(
                        f"{LOG_PREFIX}[cleanup] agent tracker run ids: {sorted(agent_run_ids)}"
                    )
        except Exception as e:
            # Agent job tracker is optional - don't fail if unavailable
            _logger.debug(f"Could not get agent job tracker run-ids: {e}")
            wandb.termlog(f"{LOG_PREFIX}[cleanup] agent tracker unavailable: {e}")

        return active_run_ids

    async def _scan_resource_type(
        self,
        api_client,
        resource_type: str,
        namespace: str,
        active_run_ids: Set[str],
    ) -> Set[str]:
        """Scan a single resource type for orphaned UUIDs.

        Args:
            api_client: Kubernetes API client
            resource_type: Type of resource to scan
            namespace: Kubernetes namespace to scan
            active_run_ids: Set of run-ids with active primary Jobs

        Returns:
            Set of orphaned UUIDs found in this resource type
        """
        wandb.termlog(
            f"{LOG_PREFIX}[cleanup] scanning resource type={resource_type} namespace={namespace}"
        )
        found_orphaned = set()
        try:
            list_method = getattr(api_client, f"list_namespaced_{resource_type}")
            resources = await list_method(
                namespace=namespace,
                label_selector="wandb.ai/auxiliary-resource",
            )

            for resource in resources.items:
                uuid_val = resource.metadata.labels.get("wandb.ai/auxiliary-resource")
                if not uuid_val:
                    wandb.termlog(
                        f"{LOG_PREFIX}[cleanup] resource type={resource_type} missing auxiliary label: {resource.metadata.name}"
                    )
                    continue

                # Check if the run-id for this resource has an active Job
                run_id = resource.metadata.labels.get("wandb.ai/run-id")
                if not run_id:
                    # Resource has no run-id label - shouldn't happen, but skip for safety
                    _logger.warning(
                        f"Resource {resource_type} {resource.metadata.name} "
                        f"has auxiliary-resource label but no run-id label"
                    )
                    continue

                # Skip if has active primary Job
                if run_id in active_run_ids:
                    wandb.termlog(
                        f"{LOG_PREFIX}[cleanup] resource type={resource_type} uuid={uuid_val} run-id={run_id} still active"
                    )
                    continue

                # Check age (safety buffer)
                creation_time = resource.metadata.creation_timestamp
                if creation_time:
                    age = (datetime.now(timezone.utc) - creation_time).total_seconds()
                    if age < self._minimum_age:
                        _logger.debug(
                            f"Skipping {resource_type} {resource.metadata.name} "
                            f"(age: {age:.0f}s < {self._minimum_age}s)"
                        )
                        wandb.termlog(
                            f"{LOG_PREFIX}[cleanup] skipping {resource_type}/{resource.metadata.name} uuid={uuid_val} age={age:.0f}s (<{self._minimum_age}s)"
                        )
                        continue

                # This UUID is orphaned
                found_orphaned.add(uuid_val)
                wandb.termlog(
                    f"{LOG_PREFIX}[cleanup] found orphaned uuid={uuid_val} resource_type={resource_type} namespace={namespace}"
                )

        except (AttributeError, ApiException) as e:
            _logger.warning(f"Failed to scan {resource_type} in {namespace}: {e}")
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] failed scan resource_type={resource_type} namespace={namespace}: {e}"
            )
        except Exception as e:
            _logger.warning(
                f"Unexpected error scanning {resource_type} in {namespace}: {e}",
                exc_info=True,
            )
            wandb.termlog(
                f"{LOG_PREFIX}[cleanup] unexpected error scan resource_type={resource_type} namespace={namespace}: {e}"
            )

        return found_orphaned

    async def _find_orphaned_uuids(
        self,
        core_api: "kubernetes_asyncio.client.CoreV1Api",
        apps_api: "kubernetes_asyncio.client.AppsV1Api",
        network_api: "kubernetes_asyncio.client.NetworkingV1Api",
        batch_api: "kubernetes_asyncio.client.BatchV1Api",
        namespace: str,
        active_run_ids: Set[str],
    ) -> Set[str]:
        """Find UUIDs of orphaned auxiliary resources.

        Args:
            core_api: Kubernetes Core API client
            apps_api: Kubernetes Apps API client
            network_api: Kubernetes Networking API client
            batch_api: Kubernetes Batch API client
            namespace: Kubernetes namespace
            active_run_ids: Set of run-ids with active primary Jobs

        Returns:
            Set of orphaned UUIDs
        """
        resource_types = [
            (core_api, "service"),
            (batch_api, "job"),
            (core_api, "pod"),
            (core_api, "secret"),
            (apps_api, "deployment"),
            (network_api, "network_policy"),
        ]

        wandb.termlog(
            f"{LOG_PREFIX}[cleanup] concurrently scanning resource types in {namespace}"
        )
        results = await asyncio.gather(
            *[
                self._scan_resource_type(
                    api_client, resource_type, namespace, active_run_ids
                )
                for api_client, resource_type in resource_types
            ]
        )

        orphaned_uuids = set()
        for uuid_set in results:
            orphaned_uuids.update(uuid_set)
        wandb.termlog(
            f"{LOG_PREFIX}[cleanup] scan finished for {namespace}, orphaned uuids={sorted(orphaned_uuids)}"
        )

        return orphaned_uuids
