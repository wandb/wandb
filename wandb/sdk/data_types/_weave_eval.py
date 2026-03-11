"""Weave Evaluation Table integration.

Uploads EvalTable rows to the Weave trace server as an Evaluation, using raw
HTTP calls so the weave SDK is not required.
"""

from __future__ import annotations

import datetime
import io
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import EvalTable
    from wandb.sdk.wandb_run import Run as LocalRun

log = logging.getLogger(__name__)

# Weave trace server URL. Override for on-prem / dedicated-cloud deployments.
_TRACE_URL = os.environ.get("WEAVE_TRACE_SERVER_URL", "https://trace.wandb.ai")

# Stable content-hash digest for the load_PIL.Image.Image op in the weave SDK.
# This is the SHA256 of the serialised load-function source and is the same
# across all projects and weave SDK versions (as long as the source is unchanged).
_PIL_LOAD_OP_DIGEST = "e1nS8rg9KiOooLOkLsYf4NAIYGwv7xxeBZ7tZE9wmL0"


def _upload_bytes(
    project_id: str,
    filename: str,
    data: bytes,
    mime: str,
    auth: tuple[str, str],
) -> str:
    """Upload raw bytes to the Weave file store. Returns the SHA256 digest."""
    import requests

    resp = requests.post(
        f"{_TRACE_URL}/files/create",
        data={"project_id": project_id},
        files={"file": (filename, data, mime)},
        auth=auth,
    )
    resp.raise_for_status()
    return resp.json()["digest"]


def _cell_to_weave(
    cell: Any,
    project_id: str,
    entity: str,
    project: str,
    auth: tuple[str, str],
) -> Any:
    """Convert a wandb Table cell to its Weave-compatible JSON representation.

    Supported types and how they appear in the Weave UI:

    | Cell type          | Weave representation          | Renders in UI?          |
    |--------------------|-------------------------------|-------------------------|
    | wandb.Image        | CustomWeaveType (PIL.Image)    | Yes – image viewer      |
    | wandb.Audio        | dict with uploaded file digest | No native viewer        |
    | wandb.Video        | dict with uploaded file digest | No native viewer        |
    | wandb.Html         | dict with uploaded file digest | No native viewer        |
    | wandb.Histogram    | {"bins": [...], "values": [...]} | No (raw JSON)         |
    | wandb.Molecule     | dict with uploaded file digest | No native viewer        |
    | wandb.Object3D     | dict with uploaded file digest | No native viewer        |
    | int/float/str/bool | passed through as-is           | Yes                     |
    | None               | None                           | Yes                     |
    """
    # Lazy imports so we don't pull wandb into scope at module load
    from wandb.sdk.data_types.audio import Audio as WandbAudio
    from wandb.sdk.data_types.base_types.wb_value import WBValue
    from wandb.sdk.data_types.histogram import Histogram as WandbHistogram
    from wandb.sdk.data_types.html import Html as WandbHtml
    from wandb.sdk.data_types.image import Image as WandbImage
    from wandb.sdk.data_types.video import Video as WandbVideo

    if isinstance(cell, WandbImage):
        pil_img = cell._image
        if pil_img is None and cell._path:
            try:
                from PIL import Image as PILImage

                pil_img = PILImage.open(cell._path)
            except Exception:
                pass
        if pil_img is None:
            return str(cell)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        digest = _upload_bytes(
            project_id, "image.png", buf.getvalue(), "image/png", auth
        )
        return {
            "_type": "CustomWeaveType",
            "weave_type": {"type": "PIL.Image.Image"},
            "files": {"image.png": digest},
            "load_op": (
                f"weave:///{entity}/{project}/op/"
                f"load_PIL.Image.Image:{_PIL_LOAD_OP_DIGEST}"
            ),
        }

    if isinstance(cell, WandbAudio) and getattr(cell, "_path", None):
        with open(cell._path, "rb") as fh:
            data = fh.read()
        filename = os.path.basename(cell._path)
        mime = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"
        digest = _upload_bytes(project_id, filename, data, mime, auth)
        return {"_type": "wandb.Audio", "file": filename, "digest": digest}

    if isinstance(cell, WandbVideo) and getattr(cell, "_path", None):
        with open(cell._path, "rb") as fh:
            data = fh.read()
        filename = os.path.basename(cell._path)
        digest = _upload_bytes(project_id, filename, data, "video/mp4", auth)
        return {"_type": "wandb.Video", "file": filename, "digest": digest}

    if isinstance(cell, WandbHtml) and getattr(cell, "_path", None):
        with open(cell._path, "rb") as fh:
            data = fh.read()
        digest = _upload_bytes(project_id, "content.html", data, "text/html", auth)
        return {"_type": "wandb.Html", "digest": digest}

    if isinstance(cell, WandbHistogram):
        return {"_type": "wandb.Histogram", "bins": cell.bins, "values": cell.histogram}

    if isinstance(cell, WBValue):
        # Generic file-based WBValue (Molecule, Object3D, …): upload the backing file
        path = getattr(cell, "_path", None)
        if path:
            with open(path, "rb") as fh:
                data = fh.read()
            filename = os.path.basename(path)
            digest = _upload_bytes(
                project_id, filename, data, "application/octet-stream", auth
            )
            return {"_type": type(cell).__name__, "file": filename, "digest": digest}
        return str(cell)

    # Primitives (int, float, str, bool, None) and everything else pass through
    return cell


def _is_binary_summary(v: object) -> bool:
    """Return True if v is a valid {"true_count": int, "true_fraction": float} dict."""
    return (
        isinstance(v, dict)
        and set(v) == {"true_fraction", "true_count"}
        and isinstance(v["true_count"], int)
        and isinstance(v["true_fraction"], float)
    )


def _wrap_scores(scores: dict) -> dict:
    """Validate and normalise table_scores for the Weave Evaluation Scores panel.

    Accepted value types:
      - float  → wrapped as {"mean": X} for display
      - {"true_fraction": float, "true_count": int}  → passed through as-is

    Any other value type raises ValueError.
    """
    result = {}
    for k, v in scores.items():
        if isinstance(v, float):
            result[k] = {"mean": v}
        elif _is_binary_summary(v):
            result[k] = v
        else:
            raise ValueError(
                f"table_scores[{k!r}] has unsupported type {type(v).__name__!r}. "
                "Accepted: float, or {'true_count': int, 'true_fraction': float}."
            )
    return result


def log_eval_table_to_weave(table: EvalTable, run: LocalRun) -> None:
    """Upload an EvalTable to the Weave trace server as an Evaluation.

    Called automatically from EvalTable.to_json() when the table is logged via
    wandb.log().  This is a best-effort operation: HTTP errors are logged but do
    not prevent the normal wandb Table from being written.
    """
    try:
        _log_eval_table_to_weave(table, run)
    except Exception as exc:
        log.warning("EvalTable: failed to log to Weave trace server: %s", exc)


def _log_eval_table_to_weave(table: EvalTable, run: LocalRun) -> None:
    import requests

    import wandb

    project_id = f"{run.entity}/{run.project}"
    entity, project = run.entity, run.project
    run_id = run.id
    # Capture step before wandb.log() increments it
    step = run.step
    auth = ("api", wandb.Api().api_key)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    root_call_id = str(uuid.uuid4())
    trace_id = root_call_id

    col_index = {col: i for i, col in enumerate(table.columns)}
    input_cols = set(table.input_columns)
    output_cols = set(table.output_columns)
    score_cols = set(table.score_columns)
    # Columns not assigned to any category default to outputs
    extra_output_cols = {
        c for c in table.columns if c not in input_cols | output_cols | score_cols
    }
    all_output_cols = output_cols | extra_output_cols

    # table_inputs: merge step + any user-supplied eval-level inputs
    root_inputs: dict[str, Any] = {"step": step}
    root_inputs.update(table.table_inputs)

    # ── 1. Start root Evaluation.evaluate call ─────────────────────────────
    resp = requests.post(
        f"{_TRACE_URL}/v2/{entity}/{project}/call/start",
        json={
            "start": {
                "project_id": project_id,
                "id": root_call_id,
                "trace_id": trace_id,
                "op_name": "Evaluation.evaluate",
                # display_name overrides the "Trace" column in the UI while
                # op_name stays "Evaluation.evaluate" so the UI recognises it
                # as an evaluation.
                "display_name": table._log_key,
                "started_at": now,
                # imperative=True: UI walks the output freely, no scorer-ref gating
                "attributes": {"_weave_eval_meta": {"imperative": True}},
                "inputs": root_inputs,
                "wb_run_id": f"{entity}/{project}/{run_id}",
                "wb_run_step": step,
            }
        },
        auth=auth,
    )
    resp.raise_for_status()

    # ── 2. Convert and batch all rows as Evaluation.predict_and_score calls ─
    batch = []
    for row in table.data:
        inputs: dict[str, Any] = {}
        for col in input_cols:
            if col in col_index:
                inputs[col] = _cell_to_weave(
                    row[col_index[col]], project_id, entity, project, auth
                )

        outputs: dict[str, Any] = {}
        for col in all_output_cols:
            if col in col_index:
                outputs[col] = _cell_to_weave(
                    row[col_index[col]], project_id, entity, project, auth
                )

        scores: dict[str, Any] = {}
        for col in score_cols:
            if col in col_index:
                scores[col] = _cell_to_weave(
                    row[col_index[col]], project_id, entity, project, auth
                )

        batch.append(
            {
                "project_id": project_id,
                "id": str(uuid.uuid4()),
                "trace_id": trace_id,
                "parent_id": root_call_id,
                "op_name": "Evaluation.predict_and_score",
                "started_at": now,
                "ended_at": now,
                "attributes": {},
                "inputs": {"model": "model", "example": inputs},
                "output": {"output": outputs, "scores": scores, "model_latency": 0.0},
                "summary": {},
                "wb_run_id": f"{entity}/{project}/{run_id}",
                "wb_run_step": step,
                "wb_run_step_end": step,
            }
        )

    resp = requests.post(
        f"{_TRACE_URL}/v2/{entity}/{project}/calls/complete",
        json={"batch": batch},
        auth=auth,
    )
    resp.raise_for_status()

    # ── 3. Close the root call ──────────────────────────────────────────────
    # table_scores drive the Weave Evaluation UI "Scores" panel.
    # Because we use imperative=True, any numeric/bool values at any nesting
    # depth are recognised and displayed.
    root_output: dict[str, Any] = {"_n_rows": len(table.data)}
    root_output.update(_wrap_scores(table.table_scores))

    resp = requests.post(
        f"{_TRACE_URL}/v2/{entity}/{project}/call/end",
        json={
            "end": {
                "project_id": project_id,
                "id": root_call_id,
                "ended_at": now,
                "output": root_output,
                "summary": {},
                "wb_run_step_end": step,
            }
        },
        auth=auth,
    )
    resp.raise_for_status()
