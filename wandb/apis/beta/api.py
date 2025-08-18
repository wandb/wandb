from __future__ import annotations

import wandb
from wandb.sdk import wandb_login, wandb_setup
from wandb.sdk.backend.backend import Backend
from wandb.sdk.lib import runid
from wandb.sdk.wandb_settings import Settings

from .runs import Run


class Api:
    def __init__(self, settings: Settings | None = None) -> None:
        wl: wandb_setup._WandbSetup | None = None
        settings = settings or Settings()

        # abuse run_id
        settings.run_id = runid.generate_id()

        try:
            wl = wandb_setup.singleton()

            if settings._noop or settings._offline:
                return

            wandb_login._login(
                anonymous=settings.anonymous,
                host=settings.base_url,
                force=settings.force,
                _disable_warning=True,
                _silent=settings.quiet or settings.silent,
            )

            self._logger.info("starting backend")

            service = wl.ensure_service()
            self._logger.info("sending inform_init_api request")
            service.inform_init_api(
                settings=settings.to_proto(),
                stream_id=settings.run_id,  # type: ignore
            )

            self.backend = Backend(settings=settings, service=service)
            self.backend.ensure_launched()
            self._logger.info("backend started and connected")

            self.settings = settings

        except KeyboardInterrupt as e:
            if wl:
                wl._get_logger().warning("interrupted", exc_info=e)

            raise

        except Exception as e:
            if wl:
                wl._get_logger().exception("error in wandb.init()", exc_info=e)

            wandb._sentry.reraise(e)

    @property
    def _logger(self) -> wandb_setup.Logger:
        return wandb_setup.singleton()._get_logger()

    def run(
        self,
        run_id: str,
        *,
        entity: str | None = None,
        project: str | None = None,
    ) -> Run:
        entity = entity or self.settings.entity
        project = project or self.settings.project

        handle = self.backend.interface.deliver_api_run_request(
            entiry=entity, project=project, run_id=run_id
        )
        result = handle.wait_or(timeout=5)

        response = result.response.api_response.value_json

        run = Run(entity=entity, project=project, run_id=run_id)
        run._from_api_run_response(response)

        return run
