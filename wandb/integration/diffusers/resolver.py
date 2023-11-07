import logging
from typing import Any, Dict, Sequence

import wandb
from wandb.sdk.integration_utils.auto_logging import Response
from wandb.sdk.lib.runid import generate_id


logger = logging.getLogger(__name__)


class DiffusersPipelineResolver:
    autolog_id = None

    def __call__(
        self,
        args: Sequence[Any],
        kwargs: Dict[str, Any],
        response: Response,
        start_time: float,
        time_elapsed: float,
    ) -> Any:
        pass

        try:
            pipeline, input_data = args[:2]
            pipeline_configs = dict(pipeline.config)
            table = wandb.Table(columns=["Architecture"], data=[pipeline_configs])
            return {"text-to-image": table}
        except Exception as e:
            logger.warning(e)
        return None
