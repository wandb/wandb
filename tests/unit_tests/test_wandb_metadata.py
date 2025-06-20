import datetime

from wandb.sdk.wandb_metadata import Metadata


def test_to_proto_update_from_proto():
    time_stamp = datetime.datetime.now(datetime.timezone.utc)
    metadata = Metadata(
        os="macOS-14.1-arm64-arm-64bit",
        python="CPython 3.10.11",
        heartbeat_at=time_stamp,
        started_at=time_stamp,
        docker="my-docker",
        cuda="12.3",
        args=["--foo", "bar"],
        state="running",
        program="program.py",
        code_path="/my/code.py",
        git=dict(
            remote_url="https://github.com/wandb/wandb.git",
            commit="e5585476938326d14ee1c62c84334e69875ce527",
        ),
        email="ai@wandb.com",
        root="/my/root",
        host="my-host",
        username="my-username",
        executable="/envs/sdk/bin/python",
        code_path_local=None,
        colab="https://colab.research.google.com/drive/1a2b3c4d5e6f7g8h9i0j",
        cpu_count=10,
        cpu_count_logical=10,
        gpu_type="NVIDIA Tesla T4",
        gpu_count=2,
        disk={},
        memory=dict(total=68719476736),
        cpu=dict(count=10, count_logical=10),
        apple=dict(
            name="Apple M1 Max",
            ecpu_cores=2,
            pcpu_cores=8,
            gpu_cores=24,
            memory_gb=64,
            swap_total_bytes=3221225472,
            ram_total_bytes=68719476736,
        ),
        gpu_nvidia=[
            {
                "name": "Tesla T4",
                "memory_total": "16106127360",
                "cuda_cores": 2560,
                "architecture": "Turing",
            },
            {
                "name": "Tesla T4",
                "memory_total": "16106127360",
                "cuda_cores": 2560,
                "architecture": "Turing",
            },
        ],
        gpu_amd=[
            {
                "id": "0x740f",
                "unique_id": "0x43cc8cc8af246708",
                "vbios_version": "113-D67301-063",
                "performance_level": "auto",
                "gpu_overdrive": "0",
                "gpu_memory_overdrive": "0",
                "max_power": "300.0",
                "series": "GENERIC RM IMAGE",
                "model": "0x0c34",
                "vendor": "Advanced Micro Devices, Inc. [AMD/ATI]",
                "sku": "D67301",
                "sclk_range": "500Mhz - 1700Mhz",
                "mclk_range": "400Mhz - 1600Mhz",
            },
            {
                "id": "0x740f",
                "unique_id": "0x6d6faa0820f04eca",
                "vbios_version": "113-D67301-063",
                "performance_level": "auto",
                "gpu_overdrive": "0",
                "gpu_memory_overdrive": "0",
                "max_power": "300.0",
                "series": "GENERIC RM IMAGE",
                "model": "0x0c34",
                "vendor": "Advanced Micro Devices, Inc. [AMD/ATI]",
                "sku": "D67301",
                "sclk_range": "500Mhz - 1700Mhz",
                "mclk_range": "400Mhz - 1600Mhz",
            },
        ],
        slurm={
            "SLURM_JOB_ID": "123456",
        },
        cuda_version="13.4",
        trainium={
            "name": "trainium",
            "vendor": "AWS",
            "neuron_device_count": 8,
            "neuroncore_per_device_count": 4,
        },
        tpu={"name": "v2", "hbm_gib": 8, "devices_per_chip": 2, "count": 1},
    )

    proto = metadata.to_proto()

    metadata_from_proto = Metadata()
    metadata_from_proto.update_from_proto(proto)

    # Check that the metadata is the same after converting to proto and back
    assert proto == metadata_from_proto.to_proto()
