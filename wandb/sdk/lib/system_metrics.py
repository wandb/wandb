from __future__ import annotations

from enum import Flag, auto

from pydantic import BaseModel


class MetricGroup(Flag):
    CPU = auto()
    DISK = auto()
    MEMORY = auto()
    NETWORK = auto()
    TPU = auto()
    APPLE_SILICON = auto()
    NVIDIA_GPU = auto()
    AMD_GPU = auto()
    AWS_TRAINIUM = auto()

    ALL = (
        CPU
        | DISK
        | MEMORY
        | NETWORK
        | TPU
        | APPLE_SILICON
        | NVIDIA_GPU
        | AMD_GPU
        | AWS_TRAINIUM
    )


class MetricsFlags(BaseModel):
    # Generic CPU metrics
    cpu_utilization_process: bool = True
    cpu_utilization_per_core: bool = True
    cpu_threads_process: bool = True

    # Disk metrics
    disk_usage_percent_per_path: bool = True
    disk_usage_gb_per_path: bool = True
    disk_bytes_read: bool = True
    disk_bytes_written: bool = True

    # Memory metrics
    memory_system_percent: bool = True
    memory_system_available_mb: bool = True
    memory_process_rss_mb: bool = True
    memory_process_percent: bool = True

    # Network metrics
    network_bytes_sent: bool = False
    network_bytes_received: bool = False

    # TPU metrics (renamed: removed _per_device)
    tpu_memory_usage_percent: bool = True
    tpu_memory_bytes: bool = True
    tpu_duty_cycle_percent: bool = True

    # Apple Silicon metrics
    apple_cpu_efficiency_frequency: bool = True
    apple_cpu_efficiency_utilization_percent: bool = True
    apple_cpu_performance_frequency: bool = True
    apple_cpu_performance_utilization_percent: bool = True
    apple_cpu_temperature_avg: bool = True
    apple_cpu_power_watts: bool = True
    apple_gpu_frequency: bool = True
    apple_gpu_utilization_percent: bool = True
    apple_gpu_temperature: bool = True
    apple_gpu_power_watts: bool = True
    apple_memory_used_bytes: bool = True
    apple_memory_used_percent: bool = True
    apple_swap_used_bytes: bool = True
    apple_swap_used_percent: bool = True
    apple_ane_power_watts: bool = True
    apple_system_power_watts: bool = True

    # Nvidia GPU metrics
    nvidia_gpu_utilization: bool = True
    nvidia_gpu_memory_utilization_percent: bool = True
    nvidia_gpu_memory_total_bytes: bool = True
    nvidia_gpu_memory_used_bytes: bool = True
    nvidia_gpu_temperature: bool = True
    nvidia_gpu_power_watts: bool = True
    nvidia_gpu_power_limit_watts: bool = True
    nvidia_gpu_power_percent: bool = True
    nvidia_gpu_fan_speed_percent: bool = True
    nvidia_gpu_encoder_utilization: bool = True
    nvidia_gpu_sm_clock: bool = True
    nvidia_gpu_memory_clock: bool = True
    nvidia_gpu_graphics_clock: bool = True
    nvidia_gpu_memory_errors_corrected: bool = True
    nvidia_gpu_memory_errors_uncorrected: bool = True
    nvidia_gpu_pcie_link_gen: bool = True
    nvidia_gpu_pcie_link_width: bool = True
    nvidia_gpu_pcie_link_speed: bool = True

    # AMD GPU metrics
    amd_gpu_utilization: bool = True
    amd_gpu_memory_allocated: bool = True
    amd_gpu_memory_activity: bool = True
    amd_gpu_memory_overdrive: bool = True
    amd_gpu_temperature: bool = True
    amd_gpu_power_watts: bool = True
    amd_gpu_power_percent: bool = True

    # AWS Trainium metrics
    trn_neuroncore_utilization_per_core: bool = True
    trn_host_memory_total: bool = True
    trn_device_memory_total: bool = True
    trn_host_memory_application: bool = True
    trn_host_memory_constants: bool = True
    trn_host_memory_dma_buffers: bool = True
    trn_host_memory_tensors: bool = True
    trn_neuroncore_memory_constants_per_core: bool = True
    trn_neuroncore_memory_model_code_per_core: bool = True
    trn_neuroncore_memory_scratchpad_per_core: bool = True
    trn_neuroncore_memory_runtime_per_core: bool = True
    trn_neuroncore_memory_tensors_per_core: bool = True

    def _apply_groups(self, groups: MetricGroup, enabled: bool) -> None:
        metric_names = list(self.model_dump().keys())

        for group in MetricGroup:
            if group not in groups:
                continue
            matching_fields: list[str] = [
                m for m in metric_names if m.startswith(group.name.lower())
            ]
            for field in matching_fields:
                setattr(self, field, enabled)

    # Public API methods for group-based toggling
    def enable(self, groups: MetricGroup) -> None:
        """Enable all metrics for the specified asset groups."""
        self._apply_groups(groups, True)

    def disable(self, groups: MetricGroup) -> None:
        """Disable all metrics for the specified asset groups."""
        self._apply_groups(groups, False)
