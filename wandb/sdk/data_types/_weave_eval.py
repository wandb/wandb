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

# Per-run model ref cache.  Cleared whenever the run ID changes (i.e. wandb.init
# was called again).  The model object is published lazily on the first EvalTable
# log of each run, derived from wandb.run.config.
_model_cache_run_id: str | None = None
_model_cache_ref: str | None = None

# Dataset cache: maps a SHA-256 of the raw input rows to (dataset_ref, [row_refs]).
# Cleared on new run so we don't accumulate entries across a long-running process.
_dataset_cache: dict[str, tuple[str, list[str]]] = {}
_dataset_cache_run_id: str | None = None

# Evaluation object cache: maps input_rows_hash to the published Evaluation object ref.
# Keyed on dataset hash so sweep runs on the same dataset share one Evaluation object,
# enabling the Weave Compare tab to group them.  Cleared on new run like other caches.
_eval_ref_cache: dict[str, str] = {}
_eval_ref_cache_run_id: str | None = None


def _hash_input_rows(
    table: EvalTable,
    col_index: dict[str, int],
    input_cols: set[str],
) -> str:
    """Stable SHA-256 of the raw input column data across all rows."""
    import hashlib

    from wandb.sdk.data_types.image import Image as WandbImage

    hasher = hashlib.sha256()
    for row in table.data:
        row_hash: dict[str, str] = {}
        for col in sorted(input_cols):
            if col not in col_index:
                continue
            cell = row[col_index[col]]
            if isinstance(cell, WandbImage):
                pil = cell._image
                if pil is not None:
                    row_hash[col] = hashlib.sha256(pil.tobytes()).hexdigest()
                elif getattr(cell, "_path", None):
                    with open(cell._path, "rb") as f:
                        row_hash[col] = hashlib.sha256(f.read()).hexdigest()
                else:
                    row_hash[col] = repr(cell)
            else:
                row_hash[col] = repr(cell)
        hasher.update(repr(row_hash).encode())
    return hasher.hexdigest()


def _ensure_dataset(
    input_rows_hash: str,
    table: EvalTable,
    col_index: dict[str, int],
    input_cols: set[str],
    run: LocalRun,
    auth: tuple[str, str],
    entity: str,
    project: str,
    project_id: str,
) -> tuple[str, list[dict], list[str]]:
    """Return (cache_status, converted_input_rows, row_refs).

    converted_input_rows is always populated (never empty) so the caller can
    safely use inline dicts for call inputs regardless of cache status.
    Weave ref strings are intentionally not used as call inputs because the
    Weave UI requires example to be an inline dict for results rendering.

    cache_status is one of:
      "client"  — in-memory hit, no upload
      "server"  — /obj/read hit, no upload
      "miss"    — uploaded images + table + dataset object to server
    """
    import concurrent.futures

    import requests

    global _dataset_cache, _dataset_cache_run_id

    if _dataset_cache_run_id != run.id:
        _dataset_cache.clear()
        _dataset_cache_run_id = run.id

    dataset_object_id = f"eval-inputs-{input_rows_hash[:12]}"

    # ── 1. Always convert input cells in parallel ─────────────────────────────
    # This must happen unconditionally so converted_rows is always a list of
    # dicts (never empty), which is required for inline call inputs.
    # For text cells this is a no-op (no HTTP); for images the server deduplicates
    # identical uploads, so re-conversion on cache hits incurs only network overhead.
    work = [
        (i, col, row[col_index[col]])
        for i, row in enumerate(table.data)
        for col in input_cols
        if col in col_index
    ]
    converted_rows: list[dict] = [{} for _ in table.data]
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(32, (os.cpu_count() or 1) + 4) // 2)
    ) as executor:
        future_to_pos = {
            executor.submit(_cell_to_weave, cell, project_id, entity, project, auth): (
                i,
                col,
            )
            for i, col, cell in work
        }
        for future in concurrent.futures.as_completed(future_to_pos):
            i, col = future_to_pos[future]
            converted_rows[i][col] = future.result()

    # ── 2. Client cache hit: skip upload ──────────────────────────────────────
    if input_rows_hash in _dataset_cache:
        _dataset_ref, row_refs = _dataset_cache[input_rows_hash]
        return "client", converted_rows, row_refs

    # ── 3. Server cache hit: skip upload ──────────────────────────────────────
    try:
        read_resp = requests.post(
            f"{_TRACE_URL}/obj/read",
            json={
                "project_id": project_id,
                "object_id": dataset_object_id,
                "digest": "latest",
            },
            auth=auth,
        )
        if read_resp.status_code == 200:
            obj_val = read_resp.json().get("obj", {}).get("val", {})
            stored_row_digests = obj_val.get("_row_digests")
            object_digest = read_resp.json()["obj"]["digest"]
            if stored_row_digests:
                row_refs = [
                    f"weave:///{entity}/{project}/object/{dataset_object_id}:{object_digest}/attr/rows/id/{rd}"
                    for rd in stored_row_digests
                ]
                _dataset_cache[input_rows_hash] = (
                    f"weave:///{entity}/{project}/object/{dataset_object_id}:{object_digest}",
                    row_refs,
                )
                return "server", converted_rows, row_refs
        else:
            log.debug(
                "EvalTable: /obj/read returned %d for %s: %s",
                read_resp.status_code,
                dataset_object_id,
                read_resp.text[:200],
            )
    except Exception as e:
        log.debug("EvalTable: /obj/read failed: %s", e)

    # ── 4. Cache miss: upload table + dataset object ───────────────────────────
    resp = requests.post(
        f"{_TRACE_URL}/table/create",
        json={"table": {"project_id": project_id, "rows": converted_rows}},
        auth=auth,
    )
    resp.raise_for_status()
    table_digest = resp.json()["digest"]
    row_digests = resp.json()["row_digests"]

    resp = requests.post(
        f"{_TRACE_URL}/obj/create",
        json={
            "obj": {
                "project_id": project_id,
                "object_id": dataset_object_id,
                "val": {
                    "_type": "Dataset",
                    "rows": f"weave:///{entity}/{project}/table/{table_digest}",
                    "_row_digests": row_digests,
                },
            }
        },
        auth=auth,
    )
    resp.raise_for_status()
    object_digest = resp.json()["digest"]

    row_refs = [
        f"weave:///{entity}/{project}/object/{dataset_object_id}:{object_digest}/attr/rows/id/{rd}"
        for rd in row_digests
    ]
    _dataset_cache[input_rows_hash] = (
        f"weave:///{entity}/{project}/object/{dataset_object_id}:{object_digest}",
        row_refs,
    )
    return "miss", converted_rows, row_refs


def _ensure_model_ref(
    run: LocalRun,
    auth: tuple[str, str],
    entity: str,
    project: str,
    project_id: str,
) -> str:
    """Lazily publish a Model object from the current run config and cache its ref.

    The object is named after the run ID so each run gets its own versioned
    model.  Because the trace server is content-addressed, identical configs
    produce the same digest and are deduplicated automatically.
    """
    import requests

    global _model_cache_run_id, _model_cache_ref

    if _model_cache_run_id == run.id and _model_cache_ref is not None:
        return _model_cache_ref

    val = {"_type": "Model", **dict(run.config)}
    resp = requests.post(
        f"{_TRACE_URL}/obj/create",
        json={
            "obj": {
                "project_id": project_id,
                "object_id": f"run-{run.id}-model",
                "val": val,
            }
        },
        auth=auth,
    )
    resp.raise_for_status()
    digest = resp.json()["digest"]
    _model_cache_run_id = run.id
    _model_cache_ref = f"weave:///{entity}/{project}/object/run-{run.id}-model:{digest}"
    return _model_cache_ref


def _ensure_eval_ref(
    input_rows_hash: str,
    dataset_ref: str,
    run: LocalRun,
    auth: tuple[str, str],
    entity: str,
    project: str,
    project_id: str,
) -> str:
    """Publish an Evaluation object keyed on the dataset content-hash and cache its ref.

    Keying on the dataset hash (not the run ID) means multiple sweep runs that evaluate
    the same dataset share one Evaluation object, enabling the Weave Compare tab.
    """
    import requests

    global _eval_ref_cache, _eval_ref_cache_run_id

    if _eval_ref_cache_run_id != run.id:
        _eval_ref_cache.clear()
        _eval_ref_cache_run_id = run.id

    if input_rows_hash in _eval_ref_cache:
        return _eval_ref_cache[input_rows_hash]

    eval_object_id = f"eval-{input_rows_hash[:12]}"
    resp = requests.post(
        f"{_TRACE_URL}/obj/create",
        json={
            "obj": {
                "project_id": project_id,
                "object_id": eval_object_id,
                "val": {
                    "_type": "Evaluation",
                    "_bases": ["Object", "BaseModel"],
                    "dataset": dataset_ref,
                    "scorers": [],
                    "trials": 1,
                    "metadata": {"_weave_eval_meta": {"imperative": True}},
                    "name": None,
                    "description": None,
                },
            }
        },
        auth=auth,
    )
    resp.raise_for_status()
    digest = resp.json()["digest"]
    ref = f"weave:///{entity}/{project}/object/{eval_object_id}:{digest}"
    _eval_ref_cache[input_rows_hash] = ref
    return ref


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
        import traceback

        log.warning(
            "EvalTable: failed to log to Weave trace server: %s\n%s",
            exc,
            traceback.format_exc(),
        )


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

    model_ref = _ensure_model_ref(run, auth, entity, project, project_id)

    # table_inputs: merge step + any user-supplied eval-level inputs
    root_inputs: dict[str, Any] = {"model": model_ref, "step": step}
    root_inputs.update(table.table_inputs)

    # ── 1. Start root Evaluation.evaluate call ─────────────────────────────
    resp = requests.post(
        f"{_TRACE_URL}/v2/{entity}/{project}/call/start",
        json={
            "start": {
                "project_id": project_id,
                "id": root_call_id,
                "trace_id": trace_id,
                # Full URI format required so the compare selector's op_name
                # LIKE filter matches.  The "imperative" sentinel stands in for
                # a real content-hash since we never publish this as an op object.
                # parseSpanName() in the UI strips the prefix back to
                # "Evaluation.evaluate" for display.
                "op_name": f"weave:///{entity}/{project}/op/Evaluation.evaluate:imperative",
                # display_name overrides the "Trace" column in the UI while
                # op_name carries the correct URI so the compare selector finds it.
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

    # ── 2. Build batch: dataset publish (cache-backed) + per-row calls ────────
    import concurrent.futures

    input_rows_hash = _hash_input_rows(table, col_index, input_cols)
    _dataset_status, converted_input_rows, _row_refs = _ensure_dataset(
        input_rows_hash,
        table,
        col_index,
        input_cols,
        run,
        auth,
        entity,
        project,
        project_id,
    )
    dataset_ref = _dataset_cache[input_rows_hash][0]
    try:
        _ensure_eval_ref(
            input_rows_hash, dataset_ref, run, auth, entity, project, project_id
        )
    except Exception as e:
        log.debug("EvalTable: failed to publish Evaluation object: %s", e)

    # Fan out all output + score cell conversions in parallel.
    output_work = [
        (i, "output", col, row[col_index[col]])
        for i, row in enumerate(table.data)
        for col in all_output_cols
        if col in col_index
    ]
    score_work = [
        (i, "score", col, row[col_index[col]])
        for i, row in enumerate(table.data)
        for col in score_cols
        if col in col_index
    ]
    all_cell_work = output_work + score_work

    # results[i] = {"output": {col: val, ...}, "score": {col: val, ...}}
    results: list[dict[str, dict]] = [{"output": {}, "score": {}} for _ in table.data]
    _max_workers = max(1, min(32, (os.cpu_count() or 1) + 4) // 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=_max_workers) as executor:
        future_to_pos = {
            executor.submit(_cell_to_weave, cell, project_id, entity, project, auth): (
                i,
                kind,
                col,
            )
            for i, kind, col, cell in all_cell_work
        }
        for future in concurrent.futures.as_completed(future_to_pos):
            i, kind, col = future_to_pos[future]
            results[i][kind][col] = future.result()

    batch = []
    for i, _ in enumerate(table.data):
        # Always use the inline dict for call inputs — Weave ref strings must not
        # be used here because `inputs` must be a JSON object, not a URI string.
        example = converted_input_rows[i]
        outputs = results[i]["output"]
        scores = results[i]["score"]

        pas_id = str(uuid.uuid4())
        predict_id = str(uuid.uuid4())

        # predict_and_score must come before its predict child in the batch
        # so the parent exists when the server processes the child.
        batch.append(
            {
                "project_id": project_id,
                "id": pas_id,
                "trace_id": trace_id,
                "parent_id": root_call_id,
                "op_name": "Evaluation.predict_and_score",
                "started_at": now,
                "ended_at": now,
                "attributes": {},
                "inputs": {"model": model_ref, "example": example},
                "output": {"output": outputs, "scores": scores, "model_latency": 0.0},
                "summary": {},
                "wb_run_id": f"{entity}/{project}/{run_id}",
                "wb_run_step": step,
                "wb_run_step_end": step,
            }
        )

        # predict child — the compare page searches subcalls for one whose
        # artifactName contains "predict".  Using an op URI with "predict" in
        # the name satisfies that check without using an object ref as op_name.
        batch.append(
            {
                "project_id": project_id,
                "id": predict_id,
                "trace_id": trace_id,
                "parent_id": pas_id,
                "op_name": f"weave:///{entity}/{project}/op/predict:imperative",
                "started_at": now,
                "ended_at": now,
                "attributes": {},
                "inputs": example,
                "output": outputs,
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
