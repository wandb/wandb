from .daimyo import Daimyo


class SweepDaimyo(Daimyo):
    pass


def _detect_convert_legacy_sweep_runspec(
    self, launch_spec: Dict[str, Any]
) -> None:
    # breakpoint()
    if launch_spec.get("uri") is not None:
        # Not a legacy sweep RunSpec
        return
    _logger.info('Legacy Sweep runSpec detected. Converting to Launch RunSpec format')
    launch_spec["uri"] = os.getcwd() # TODO: This seems hacky...
    launch_spec["entity"] = self._entity
    launch_spec["project"] = self._project
    # For now sweep runs use local process backend
    launch_spec["resource"] = "local-process"
    sweep_id = self._queues[0]
    launch_spec["overrides"] = {
        "args": ['--count', '1'],
        "entry_point": f"wandb agent {self._entity}/{self._project}/{sweep_id}",
        # "resource_args" : {}
    }
    # legacy_args = LegacySweepAgent._create_command_args(launch_spec)['args']
    # if legacy_args:
    #     launch_spec["overrides"]["args"].extend(legacy_args)
    # Remove old legacy RunSpec fields
    del launch_spec["args"]
    del launch_spec["logs"]