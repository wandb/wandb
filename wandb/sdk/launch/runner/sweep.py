""" Sweeps using Launch. 

SweepRun(AbstractRun)
SweepAgentRun(AbstractRun)
SweepAdvisorRun(AbstractRun)

SweepRunner(AbstractRunner)

ClassicSweepRun(AbstractRun)
ClassicSweepController(AbstractRun)

"""

import logging
from typing import Any, Callable, Dict, Optional, Tuple, Union

import numpy as np

from wandb.sdk.launch.runner.abstract import (
    AbstractBuilder,
    AbstractRun,
    AbstractRunner,
    Status,
)
from wandb.sdk.launch._project_spec import LaunchProject

from wandb.errors import LaunchError

_logger = logging.getLogger(__name__)


class SweepRun(AbstractRun):
    def __init__(
        self,
        sweep_id: str,
        random_state: Union[np.random.RandomState, int] = 42,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        _logger.debug("Created SweepRun for sweep_id: %s", sweep_id)
        self._sweep_id: str = sweep_id
        self._random_state: int = random_state

    def random_state():


class ClassicSweepAgentRun(SweepRun):
    """
    Args:
        name: Name of the run.
        state: State of the run.
        config: `dict` representation of the run's wandb.config.
        summaryMetrics: `dict` of summary statistics for the run.
        history: List of dicts containing the arguments to calls of wandb.log made during the run.
        search_info: Dict containing information produced by the search algorithm.
        early_terminate_info: Dict containing information produced by the early terminate algorithm.
        stopped: Whether the run was stopped in the sweep
        shouldStop: Whether the run should stop in the sweep
        heartbeat_at: The last time the backend received a heart beat from the run
        exitcode: The exitcode of the process that trained the run
        running: Whether the run is currently running
    """

    def __init__(
        self,
        agent_id: str,
        config: Any, # Ray Trial object, Config Dict, 
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._agent_id: str = agent_id
        self.config: Dict = config

        # name: Optional[str] = None
        # summary_metrics: Optional[dict] = Field(
        #     default_factory=lambda: {}, alias="summaryMetrics"
        # )
        # history: List[dict] = Field(default_factory=lambda: [], alias="sampledHistory")
        # config: dict = Field(default_factory=lambda: {})
        # search_info: Optional[Dict] = None
        # early_terminate_info: Optional[Dict] = None
        # stopped: bool = False
        # should_stop: bool = Field(default=False, alias="shouldStop")
        # heartbeat_at: Optional[datetime.datetime] = Field(default=None, alias="heartbeatAt")
        # exitcode: Optional[int] = None
        # running: Optional[bool] = None

    @property
    def id(self) -> str:
        return f"{self._sweep_id}-runner-{self._agent_id}"

    def wait(self) -> bool:
        """Wait for the run to finish, returning True if the run succeeded and false otherwise.
        Note that in some cases, we may wait until the remote job completes rather than until the W&B run completes.
        """
        pass

    def get_status(self) -> Status:
        """Get status of the run."""
        pass

    def cancel(self) -> None:
        """Cancel the run (interrupts the command subprocess, cancels the run, etc).
        Cancels the run and waits for it to terminate. The W&B run status may not be
        set correctly upon run cancellation.
        """
        pass


class SweepAdvisorRun(SweepRun):
    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

    @property
    def id(self) -> str:
        return f"{self._sweep_id}-advisor"

class SweepLaunchRunner(AbstractRunner):

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._controller_run: Optional[SweepAdvisorRun] = None
        self._agent_runs: Dict[str, SweepAgentRun] = {}
        pass

    def _run_advisor(self) -> Optional[SweepRun]:
        pass

    def _run_agent(self) -> Optional[SweepRun]:
        pass

    def run(
        self,
        launch_project: LaunchProject,
        builder: AbstractBuilder,
        registry_config: Dict[str, Any],
    ) -> Optional[AbstractRun]: # noqa: C901

        # Run a controller if none found

        # Populate table with agents if none found

        return 
