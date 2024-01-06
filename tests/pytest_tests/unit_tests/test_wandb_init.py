from unittest.mock import MagicMock, patch

import pytest
import wandb
from wandb.errors import Error
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.wandb_init import _WandbInit


def test_init(test_settings):
    class MyExitError(Exception):
        pass

    with patch("wandb.sdk.wandb_init._WandbInit", autospec=True) as mocked_wandbinit:
        with patch("wandb.sdk.wandb_init.logger", autospec=True), patch(
            "wandb.sdk.wandb_init.getcaller", autospec=True
        ), patch("os._exit", side_effect=MyExitError("")), patch(
            "wandb._sentry.exception", autospec=True
        ), patch(
            "wandb._assert_is_user_process", side_effect=lambda: None
        ):
            instance = mocked_wandbinit.return_value
            instance.settings = test_settings(
                {"_except_exit": True, "problem": "fatal"}
            )
            instance.setup.side_effect = lambda *_: None
            instance.init.side_effect = Exception("test")
            with pytest.raises(MyExitError):
                wandb.init()


def test_init_reinit(test_settings):
    with patch("wandb.sdk.wandb_init.logger", autospec=True), patch(
        "wandb.sdk.wandb_init.trigger", autospec=True
    ), patch("wandb.sdk.wandb_init.Mailbox", autospec=True), patch(
        "wandb.sdk.wandb_init.Run",
        MagicMock(_run_obj=pb.RunRecord(), _launch_artifact_mapping={}),
    ) as mocked_run, patch(
        "wandb.sdk.wandb_init.Backend", autospec=True
    ) as mocked_backend:
        backend_instance = mocked_backend.return_value
        backend_instance._multiprocessing = MagicMock()

        handle_mock = MagicMock(
            wait=MagicMock(
                side_effect=lambda *args, **kwargs: pb.Result(
                    run_result=pb.RunUpdateResult(
                        run=pb.RunRecord(), error=pb.ErrorInfo()
                    )
                )
            )
        )
        interface_instance = MagicMock(
            deliver_run=MagicMock(side_effect=lambda _: handle_mock)
        )
        backend_instance.interface = interface_instance

        run_instance = mocked_run.return_value

        wandbinit = _WandbInit()
        wandbinit.kwargs = {}
        wandbinit.settings = test_settings({"reinit": True})
        wandbinit.init_artifact_config = {}
        wandbinit._reporter = MagicMock()
        last_run_instance = MagicMock()
        wandbinit._wl = MagicMock(
            _global_run_stack=[last_run_instance],
            _get_manager=MagicMock(side_effect=lambda: MagicMock()),
        )

        with patch("wandb.sdk.wandb_init.ipython", autospec=True), patch(
            "wandb.sdk.wandb_settings._get_python_type", side_effect=lambda: "jupyter"
        ):
            wandbinit.init()

        assert interface_instance.publish_header.call_count == 1
        assert interface_instance.deliver_run.call_count == 1
        assert interface_instance.deliver_run_start.call_count == 1
        assert backend_instance.ensure_launched.call_count == 1
        assert run_instance._on_start.call_count == 1
        assert run_instance._on_init.call_count == 1
        assert last_run_instance.finish.call_count == 1


def test_init_internal_error(test_settings):
    with patch("wandb.sdk.wandb_init.logger", autospec=True), patch(
        "wandb.sdk.wandb_init.trigger", autospec=True
    ), patch("wandb.sdk.wandb_init.Mailbox", autospec=True), patch(
        "wandb.sdk.wandb_init.Backend", autospec=True
    ) as mocked_backend:
        backend_instance = mocked_backend.return_value
        backend_instance._multiprocessing = MagicMock()

        handle_mock = MagicMock(
            wait=MagicMock(
                side_effect=lambda *args, **kwargs: pb.Result(
                    run_result=pb.RunUpdateResult(error=pb.ErrorInfo())
                )
            )
        )
        interface_instance = MagicMock(
            deliver_run=MagicMock(side_effect=lambda _: handle_mock)
        )
        backend_instance.interface = interface_instance

        wandbinit = _WandbInit()
        wandbinit.kwargs = {}
        wandbinit.settings = test_settings()
        wandbinit._reporter = MagicMock()
        wandbinit._wl = MagicMock(
            _get_manager=MagicMock(side_effect=lambda: MagicMock()),
        )

        with patch("wandb.sdk.wandb_init.wandb.run", return_value=None):
            with pytest.raises(Error):
                wandbinit.init()

        assert interface_instance.publish_header.call_count == 1
        assert interface_instance.deliver_run.call_count == 1
        assert backend_instance.ensure_launched.call_count == 1
        assert interface_instance.deliver_run_start.call_count == 0
