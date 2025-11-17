"""Kubernetes resource cleanup for orphaned auxiliary resources.

This module handles periodic cleanup of auxiliary resources (services, deployments,
network policies, etc.) that may be left behind after an agent restart or crash.
"""

import logging
import os
from typing import Optional

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

        self._monitored_namespaces: set[str] = set(
            ns.strip() for ns in monitored_namespaces.split(",") if ns.strip()
        )

        _logger.info(
            f"Initialized resource cleanup with min_age={minimum_resource_age_seconds}s, "
            f"namespaces={sorted(self._monitored_namespaces)}"
        )

    async def run_cleanup_cycle(self) -> None:
        """Execute one cleanup cycle across all monitored namespaces.

        This method is called periodically by the agent's main loop.
        todo: impl this.
        """
        if not self._monitored_namespaces:
            _logger.debug("No namespaces to clean, skipping cycle")
            return

        _logger.info(
            f"Starting cleanup cycle for {len(self._monitored_namespaces)} namespace(s): "
            f"{', '.join(sorted(self._monitored_namespaces))}"
        )

        pass
