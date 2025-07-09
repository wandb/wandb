from __future__ import annotations

import json


class Run:
    _attrs: dict
    _state: str
    _project_internal_id: int | None

    def __init__(self, entity, project, run_id):
        self.entity = entity
        self.project = project
        self.run_id = run_id

    def _from_api_run_response(self, response_json: str) -> None:
        response = json.loads(response_json)

        if (
            response is None
            or response.get("project") is None
            or response["project"].get("run") is None
        ):
            raise ValueError(
                f"Could not find run {self.entity}/{self.project}/{self.run_id}"
            )

        self._attrs = response["project"]["run"]
        self._state = response["project"]["run"]["state"]

        if "projectId" in self._attrs:
            self._project_internal_id = int(self._attrs["projectId"])
        else:
            self._project_internal_id = None

        try:
            self._attrs["summaryMetrics"] = (
                json.loads(self._attrs["summaryMetrics"])
                if self._attrs.get("summaryMetrics")
                else {}
            )
        except json.decoder.JSONDecodeError:
            # ignore invalid utf-8 or control characters
            self._attrs["summaryMetrics"] = json.loads(
                self._attrs["summaryMetrics"],
                strict=False,
            )
        self._attrs["systemMetrics"] = (
            json.loads(self._attrs["systemMetrics"])
            if self._attrs.get("systemMetrics")
            else {}
        )
        if self._attrs.get("user"):
            self.user = self._attrs["user"]
        config_user, config_raw = {}, {}
        for key, value in json.loads(self._attrs.get("config") or "{}").items():
            config = config_raw if key in {"_wandb", "wandb_version"} else config_user
            if isinstance(value, dict) and "value" in value:
                config[key] = value["value"]
            else:
                config[key] = value
        config_raw.update(config_user)
        self._attrs["config"] = config_user
        self._attrs["rawconfig"] = config_raw
