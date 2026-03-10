"""Unit tests for the Kubeflow Pipelines (kfp) v2 integration."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("kfp", minversion="2.0.0")

from kfp import dsl
from kfp.compiler import Compiler
from kfp.dsl import Artifact, Dataset, Input, Output
from wandb.integration.kfp import wandb_log
from wandb.integration.kfp.helpers import add_wandb_visualization
from wandb.integration.kfp.kfp_patch import (
    _KFP_V2,
    full_path_exists,
    patch_kfp,
    unpatch,
    unpatch_kfp,
)
from wandb.integration.kfp.kfp_patch import patch as kfp_patch_fn
from wandb.integration.kfp.wandb_logging import wandb_log_v2

# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------


class TestVersionDetection:
    def test_kfp_v2_detected(self):
        assert _KFP_V2 is True

    def test_wandb_log_is_v2(self):
        """wandb_log should be aliased to wandb_log_v2 when kfp>=2."""
        assert wandb_log is wandb_log_v2


# ---------------------------------------------------------------------------
# Decorator basics (signature, naming, attributes)
# ---------------------------------------------------------------------------


class TestWandbLogV2Decorator:
    def test_decorator_no_parens(self):
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        assert hasattr(add, "_wandb_logged")
        assert add._wandb_logged is True

    def test_decorator_with_parens(self):
        @wandb_log()
        def add(a: float, b: float) -> float:
            return a + b

        assert add._wandb_logged is True

    def test_preserves_function_name(self):
        @wandb_log
        def my_component(x: int) -> int:
            return x * 2

        assert my_component.__name__ == "my_component"

    def test_preserves_signature(self):
        import inspect

        @wandb_log
        def compute(a: float, b: float, c: float = 1.0) -> float:
            return a + b + c

        sig = inspect.signature(compute)
        params = list(sig.parameters.keys())
        assert params == ["a", "b", "c"]
        assert sig.parameters["c"].default == 1.0

    def test_preserves_annotations(self):
        @wandb_log
        def typed_fn(x: int, y: str) -> float:
            return float(x)

        assert typed_fn.__annotations__["x"] is int
        assert typed_fn.__annotations__["y"] is str
        assert typed_fn.__annotations__["return"] is float

    def test_getfullargspec_sees_params(self):
        """KFP executor uses getfullargspec; wrapper must expose real params."""
        import inspect

        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        spec = inspect.getfullargspec(add)
        assert "a" in spec.annotations
        assert "b" in spec.annotations


# ---------------------------------------------------------------------------
# Decorator runtime behavior (scalar I/O)
# ---------------------------------------------------------------------------


class TestWandbLogV2ScalarIO:
    @staticmethod
    def _mock_init():
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init = MagicMock()
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)
        return mock_init, mock_run

    @patch("wandb.init")
    def test_scalar_inputs_logged_to_config(self, mock_init):
        mock_init_obj, mock_run = self._mock_init()
        mock_init.side_effect = mock_init_obj.side_effect
        mock_init.return_value = mock_init_obj.return_value

        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        result = add(a=3.0, b=4.0)
        assert result == 7.0
        assert mock_run.config["a"] == 3.0
        assert mock_run.config["b"] == 4.0

    @patch("wandb.init")
    def test_scalar_output_logged(self, mock_init):
        mock_init_obj, mock_run = self._mock_init()
        mock_init.side_effect = mock_init_obj.side_effect
        mock_init.return_value = mock_init_obj.return_value

        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        add(a=1.0, b=2.0)
        mock_run.log.assert_called_once_with({"add": 3.0})

    @patch("wandb.init")
    def test_namedtuple_output_logged(self, mock_init):
        from typing import NamedTuple

        mock_init_obj, mock_run = self._mock_init()
        mock_init.side_effect = mock_init_obj.side_effect
        mock_init.return_value = mock_init_obj.return_value

        class Outputs(NamedTuple):
            sum: float
            product: float

        @wandb_log
        def compute(a: float, b: float) -> Outputs:
            return Outputs(sum=a + b, product=a * b)

        result = compute(a=3.0, b=4.0)
        assert result.sum == 7.0
        assert result.product == 12.0
        logged = [c[0][0] for c in mock_run.log.call_args_list]
        assert {"compute.sum": 7.0} in logged
        assert {"compute.product": 12.0} in logged

    @patch("wandb.init")
    def test_no_return_no_log(self, mock_init):
        mock_init_obj, mock_run = self._mock_init()
        mock_init.side_effect = mock_init_obj.side_effect
        mock_init.return_value = mock_init_obj.return_value

        @wandb_log
        def side_effect(msg: str) -> None:
            pass

        side_effect(msg="hello")
        mock_run.log.assert_not_called()

    @patch("wandb.init")
    def test_finished_run_skips_log(self, mock_init):
        """If user code closes the run, decorator should not crash."""
        mock_run = MagicMock()
        mock_run._is_finished = True
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        result = add(a=1.0, b=2.0)
        assert result == 3.0
        mock_run.log.assert_not_called()

    @patch("wandb.init")
    def test_default_args_applied(self, mock_init):
        mock_init_obj, mock_run = self._mock_init()
        mock_init.side_effect = mock_init_obj.side_effect
        mock_init.return_value = mock_init_obj.return_value

        @wandb_log
        def with_defaults(a: float, b: float = 10.0) -> float:
            return a + b

        result = with_defaults(a=5.0)
        assert result == 15.0
        assert mock_run.config["a"] == 5.0
        assert mock_run.config["b"] == 10.0


# ---------------------------------------------------------------------------
# Decorator runtime behavior (env vars, grouping)
# ---------------------------------------------------------------------------


class TestWandbLogV2EnvVars:
    @patch("wandb.init")
    def test_wandb_group_from_kfp_run_name(self, mock_init):
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def noop(x: int) -> int:
            return x

        with patch.dict(os.environ, {"KFP_RUN_NAME": "my-pipeline-run"}, clear=False):
            noop(x=1)

        call_kwargs = mock_init.call_args[1]
        assert call_kwargs["group"] == "my-pipeline-run"
        assert call_kwargs["job_type"] == "noop"

    @patch("wandb.init")
    def test_wandb_group_from_argo_workflow(self, mock_init):
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def noop(x: int) -> int:
            return x

        with patch.dict(os.environ, {"ARGO_WORKFLOW_NAME": "wf-12345"}, clear=False):
            noop(x=1)

        call_kwargs = mock_init.call_args[1]
        assert call_kwargs["group"] == "wf-12345"

    @patch("wandb.init")
    def test_wandb_run_group_takes_priority(self, mock_init):
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def noop(x: int) -> int:
            return x

        with patch.dict(
            os.environ,
            {
                "WANDB_RUN_GROUP": "explicit-group",
                "KFP_RUN_NAME": "kfp-run",
                "ARGO_WORKFLOW_NAME": "argo-wf",
            },
            clear=False,
        ):
            noop(x=1)

        call_kwargs = mock_init.call_args[1]
        assert call_kwargs["group"] == "explicit-group"

    @patch("wandb.init")
    def test_kubeflow_url_in_config(self, mock_init):
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def noop(x: int) -> int:
            return x

        with patch.dict(
            os.environ, {"WANDB_KUBEFLOW_URL": "https://kf.example.com"}, clear=False
        ):
            noop(x=1)

        assert mock_run.config["LINK_TO_KUBEFLOW"] == "https://kf.example.com"

    @patch("wandb.init")
    def test_no_kubeflow_url_no_config_entry(self, mock_init):
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def noop(x: int) -> int:
            return x

        env = {k: v for k, v in os.environ.items() if k != "WANDB_KUBEFLOW_URL"}
        with patch.dict(os.environ, env, clear=True):
            noop(x=1)

        assert "LINK_TO_KUBEFLOW" not in mock_run.config


# ---------------------------------------------------------------------------
# Decorator with KFP v2 artifact annotations
# ---------------------------------------------------------------------------


class TestWandbLogV2Artifacts:
    def test_classify_input_artifact(self):
        """Functions with Input[Artifact] should classify as input_artifacts."""

        @wandb_log
        def process(data: Input[Dataset], x: float) -> float:
            return x

        assert process._wandb_logged is True
        assert process.__name__ == "process"

    def test_classify_output_artifact(self):
        """Functions with Output[Artifact] should classify as output_artifacts."""

        @wandb_log
        def produce(x: float, out: Output[Artifact]) -> None:
            pass

        assert produce._wandb_logged is True

    def test_classify_mixed_annotations(self):
        """Both scalar and artifact annotations should be handled."""

        @wandb_log
        def mixed(
            scalar_in: float,
            data_in: Input[Dataset],
            result_out: Output[Artifact],
        ) -> float:
            return scalar_in * 2

        assert mixed._wandb_logged is True

    @patch("wandb.init")
    def test_input_artifact_logging(self, mock_init, tmp_path):
        """Input artifacts with valid paths should be logged via use_artifact."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def process(data: Input[Dataset], x: float) -> float:
            return x

        artifact_file = tmp_path / "data.csv"
        artifact_file.write_text("a,b\n1,2\n")
        mock_artifact_value = MagicMock()
        mock_artifact_value.path = str(artifact_file)
        mock_artifact_value.uri = f"gs://bucket/{artifact_file.name}"

        process(data=mock_artifact_value, x=42.0)

        mock_run.use_artifact.assert_called_once()
        mock_run.log.assert_called_once_with({"process": 42.0})

    @patch("wandb.init")
    def test_output_artifact_logging(self, mock_init, tmp_path):
        """Output artifacts with valid paths should be logged via log_artifact."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def produce(x: float, model: Output[Artifact]) -> None:
            pass

        artifact_file = tmp_path / "model.pkl"
        artifact_file.write_text("model-data")
        mock_artifact_value = MagicMock()
        mock_artifact_value.path = str(artifact_file)
        mock_artifact_value.uri = f"gs://bucket/{artifact_file.name}"

        produce(x=1.0, model=mock_artifact_value)

        mock_run.log_artifact.assert_called_once()

    @patch("wandb.init")
    def test_artifact_without_path_skips(self, mock_init):
        """Artifacts without valid paths should not crash."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def process(data: Input[Dataset], x: float) -> float:
            return x

        mock_artifact_value = MagicMock()
        mock_artifact_value.path = "/nonexistent/path/data.csv"
        mock_artifact_value.uri = "gs://bucket/data.csv"

        result = process(data=mock_artifact_value, x=5.0)

        assert result == 5.0
        mock_run.use_artifact.assert_not_called()

    @patch("wandb.init")
    def test_string_path_artifact_input(self, mock_init, tmp_path):
        """InputPath-style string paths should also be handled as artifacts."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        from kfp.dsl import InputPath

        @wandb_log
        def process(data_path: InputPath("Dataset"), x: float) -> float:
            return x

        artifact_file = tmp_path / "input.txt"
        artifact_file.write_text("data")

        process(data_path=str(artifact_file), x=10.0)
        mock_run.use_artifact.assert_called_once()

    @patch("wandb.init")
    def test_artifact_exception_is_warned_not_raised(self, mock_init, tmp_path):
        """If artifact logging fails, it should warn but not crash."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def process(data: Input[Dataset], x: float) -> float:
            return x

        artifact_file = tmp_path / "data.csv"
        artifact_file.write_text("a,b\n1,2\n")
        mock_artifact_value = MagicMock()
        mock_artifact_value.path = str(artifact_file)
        mock_artifact_value.uri = "gs://bucket/data.csv"

        mock_run.use_artifact.side_effect = RuntimeError("network error")

        with patch("wandb.termwarn") as mock_warn:
            result = process(data=mock_artifact_value, x=7.0)

        assert result == 7.0
        mock_warn.assert_called_once()
        assert "Failed to log input artifact" in mock_warn.call_args[0][0]

    @patch("wandb.init")
    def test_output_artifact_exception_warned(self, mock_init, tmp_path):
        """If output artifact logging fails, it should warn but not crash."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def produce(x: float, model: Output[Artifact]) -> None:
            pass

        artifact_file = tmp_path / "model.pkl"
        artifact_file.write_text("model-data")
        mock_artifact_value = MagicMock()
        mock_artifact_value.path = str(artifact_file)
        mock_artifact_value.uri = "gs://bucket/model.pkl"

        mock_run.log_artifact.side_effect = RuntimeError("upload failed")

        with patch("wandb.termwarn") as mock_warn:
            produce(x=1.0, model=mock_artifact_value)

        mock_warn.assert_called_once()
        assert "Failed to log output artifact" in mock_warn.call_args[0][0]

    @patch("wandb.init")
    def test_non_path_artifact_value_skipped(self, mock_init):
        """Non-artifact, non-string values passed to artifact params are skipped."""
        mock_run = MagicMock()
        mock_run._is_finished = False
        mock_run.config = {}
        mock_init.return_value.__enter__ = MagicMock(return_value=mock_run)
        mock_init.return_value.__exit__ = MagicMock(return_value=False)

        @wandb_log
        def process(data: Input[Dataset], x: float) -> float:
            return x

        result = process(data=12345, x=3.0)
        assert result == 3.0
        mock_run.use_artifact.assert_not_called()


# ---------------------------------------------------------------------------
# KFP v2 patching tests
# ---------------------------------------------------------------------------


class TestKfpV2Patching:
    def test_patch_unpatch_cycle(self):
        unpatch_kfp()
        patch_kfp()

    def test_wandb_logged_flag_triggers_wandb_in_packages(self):
        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        spec = add.component_spec
        impl = spec.implementation.container
        cmd = " ".join(impl.command)
        assert "wandb" in cmd

    def test_plain_component_no_wandb_injection(self):
        @dsl.component(base_image="python:3.11-slim")
        def plain_add(a: float, b: float) -> float:
            return a + b

        spec = plain_add.component_spec
        impl = spec.implementation.container
        cmd = " ".join(impl.command)
        assert "wandb_log" not in cmd

    def test_wandb_log_preserved_in_source(self):
        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def my_fn(x: float) -> float:
            return x * 2

        spec = my_fn.component_spec
        impl = spec.implementation.container
        source = " ".join(impl.command)
        assert "@wandb_log" in source
        assert "def my_fn" in source

    def test_user_packages_preserved(self):
        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["numpy", "pandas"],
        )
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        cmd = " ".join(add.component_spec.implementation.container.command)
        assert "numpy" in cmd
        assert "pandas" in cmd
        assert "wandb" in cmd

    def test_decorator_source_includes_helpers(self):
        """Injected source should contain the full wandb_log decorator."""

        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def fn(a: float) -> float:
            return a

        source = " ".join(fn.component_spec.implementation.container.command)
        assert "import wandb" in source
        assert "def wandb_log(" in source

    def test_wandb_not_added_twice(self):
        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["wandb>=0.15.0"],
        )
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        cmd = " ".join(add.component_spec.implementation.container.command)
        assert cmd.count("'wandb'") <= 1


# ---------------------------------------------------------------------------
# Pipeline compilation tests
# ---------------------------------------------------------------------------


class TestPipelineCompilation:
    def test_compile_pipeline_with_wandb_log(self, tmp_path):
        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def add(a: float, b: float) -> float:
            return a + b

        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def double(x: float) -> float:
            return x * 2

        @dsl.pipeline(name="test-pipeline")
        def test_pipeline(a: float, b: float):
            add_task = add(a=a, b=b)
            double(x=add_task.output)

        output = tmp_path / "pipeline.yaml"
        Compiler().compile(pipeline_func=test_pipeline, package_path=str(output))

        assert output.exists()
        content = output.read_text()
        assert "comp-add" in content
        assert "comp-double" in content

    def test_compile_mixed_pipeline(self, tmp_path):
        """Pipeline with both wandb-logged and plain components."""

        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def logged_add(a: float, b: float) -> float:
            return a + b

        @dsl.component(base_image="python:3.11-slim")
        def plain_multiply(x: float, y: float) -> float:
            return x * y

        @dsl.pipeline(name="mixed-pipeline")
        def mixed_pipeline(a: float, b: float):
            s = logged_add(a=a, b=b)
            plain_multiply(x=s.output, y=2.0)

        output = tmp_path / "mixed.yaml"
        Compiler().compile(pipeline_func=mixed_pipeline, package_path=str(output))
        assert output.exists()

    def test_compile_pipeline_with_artifacts(self, tmp_path):
        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def produce(x: float, out_data: Output[Artifact]) -> None:
            with open(out_data.path, "w") as f:
                f.write(str(x))

        @dsl.component(base_image="python:3.11-slim")
        @wandb_log
        def consume(in_data: Input[Artifact]) -> float:
            with open(in_data.path) as f:
                return float(f.read())

        @dsl.pipeline(name="artifact-pipeline")
        def artifact_pipeline(x: float):
            p = produce(x=x)
            consume(in_data=p.outputs["out_data"])

        output = tmp_path / "artifact_pipeline.yaml"
        Compiler().compile(pipeline_func=artifact_pipeline, package_path=str(output))
        assert output.exists()


# ---------------------------------------------------------------------------
# helpers.py
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_add_wandb_visualization(self, tmp_path):
        mock_run = MagicMock()
        mock_run.url = "https://wandb.ai/user/project/runs/abc123"

        metadata_path = str(tmp_path / "mlpipeline_ui_metadata.json")
        add_wandb_visualization(mock_run, metadata_path)

        with open(metadata_path) as f:
            metadata = json.load(f)

        assert "outputs" in metadata
        assert len(metadata["outputs"]) == 1
        output = metadata["outputs"][0]
        assert output["type"] == "markdown"
        assert output["storage"] == "inline"
        assert "iframe" in output["source"]
        assert mock_run.url in output["source"]
        assert "kfp=true" in output["source"]


# ---------------------------------------------------------------------------
# kfp_patch utility functions
# ---------------------------------------------------------------------------


class TestKfpPatchUtilities:
    def test_full_path_exists_for_valid_path(self):
        assert full_path_exists("kfp.dsl.component_factory") is True

    def test_full_path_exists_for_invalid_path(self):
        assert full_path_exists("kfp.nonexistent.module") is False

    def test_unpatch_nonexistent_module(self):
        unpatch("some.module.that.doesnt.exist")

    def test_multiple_patch_unpatch_cycles(self):
        for _ in range(3):
            unpatch_kfp()
            patch_kfp()

    def test_patch_is_idempotent(self):
        patch_kfp()
        patch_kfp()
        unpatch_kfp()
        patch_kfp()

    def test_patch_reports_error_for_bad_path(self):
        """Patching a nonexistent function path should report error."""

        def fake_func():
            pass

        fake_func.__name__ = "nonexistent_func"
        result = kfp_patch_fn("kfp.nonexistent_module", fake_func)
        assert result is False
