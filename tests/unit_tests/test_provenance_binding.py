from types import SimpleNamespace


def test_binding_never_uses_unproven_host_ordinal():
    from wandb.sdk.provenance.binding import binding_evidence

    cuda = SimpleNamespace(
        is_initialized=lambda: True,
        current_device=lambda: 0,
        get_device_properties=lambda _: SimpleNamespace(),
    )
    assert binding_evidence(cuda, {"CUDA_VISIBLE_DEVICES": "3"})["status"] == "partial"


def test_binding_reports_process_visible_uuid():
    from wandb.sdk.provenance.binding import binding_evidence

    cuda = SimpleNamespace(
        is_initialized=lambda: True,
        current_device=lambda: 0,
        get_device_properties=lambda _: SimpleNamespace(uuid="GPU-1234"),
    )
    evidence = binding_evidence(cuda, {"CUDA_VISIBLE_DEVICES": "3"})
    assert evidence["gpu_uuid"] == "GPU-1234"
    assert evidence["cuda_index"] == 0
