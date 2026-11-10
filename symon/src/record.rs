//! Builds the record one client receives from a [`Sample`].
//!
//! A sample covers every device and every process. A client sees only the
//! GPUs it asked for, and the GPUs its process uses have the PROCESS binding.

use std::collections::HashSet;

use crate::metrics::{self, Field, Readings, Sample};
use crate::wandb_internal::{AcceleratorType, Binding, SystemMetricsRecord};

/// The typed record for a client monitoring the processes in `pids`.
///
/// `scoped` holds the readings specific to this client and `values` its
/// averages and its counters since their baselines. An empty
/// `gpu_device_ids` selects every GPU.
pub fn typed_record(
    sample: &Sample,
    scoped: Option<&Readings>,
    values: &[(Field, f64)],
    pids: &[u32],
    gpu_device_ids: &[i32],
) -> SystemMetricsRecord {
    let gpus_in_use = gpus_in_use(sample, pids);
    let mut record = sample.record.clone();
    for (field, value) in values {
        field.set(&mut record, *value);
    }
    record.accelerators.retain(|device| {
        let gpu = matches!(
            device.r#type(),
            AcceleratorType::NvidiaGpu | AcceleratorType::AmdGpu | AcceleratorType::AppleGpu
        );
        !gpu || gpu_device_ids.is_empty() || gpu_device_ids.contains(&(device.index as i32))
    });
    // Only NVML lists the processes on a device.
    for device in &mut record.accelerators {
        if device.source == "nvml" && sample.gpu_pids.contains_key(&device.index) {
            device.set_binding(if gpus_in_use.contains(&device.index) {
                Binding::Process
            } else {
                Binding::Visible
            });
        }
    }
    // After the device filter, which does not apply to scoped readings.
    if let Some(readings) = scoped {
        metrics::merge(&mut record, &readings.record);
    }
    record
}

/// The GPUs any of the processes in `pids` use, by device index.
fn gpus_in_use(sample: &Sample, pids: &[u32]) -> HashSet<u32> {
    sample
        .gpu_pids
        .iter()
        .filter(|(_, users)| users.iter().any(|pid| pids.contains(pid)))
        .map(|(device, _)| *device)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::NvidiaRate;
    use crate::wandb_internal::AcceleratorMetrics;

    #[test]
    fn typed_record_sets_averages_filters_gpus_and_binds_them() {
        let gpu = |index| AcceleratorMetrics {
            r#type: AcceleratorType::NvidiaGpu as i32,
            index,
            source: "nvml".to_string(),
            ..Default::default()
        };
        let sample = Sample {
            record: SystemMetricsRecord {
                accelerators: vec![gpu(0), gpu(1)],
                ..Default::default()
            },
            gpu_pids: [(0, vec![42]), (1, vec![7])].into(),
            ..Default::default()
        };
        let values = [
            (Field::Nvidia("nvml", 0, NvidiaRate::SmActive), 0.5),
            (Field::Nvidia("nvml", 1, NvidiaRate::SmActive), 0.51),
        ];

        let record = typed_record(&sample, None, &values, &[42], &[0]);

        let [device] = record.accelerators.as_slice() else {
            panic!("expected one GPU: {:?}", record.accelerators);
        };
        assert_eq!(device.index, 0);
        assert_eq!(device.binding(), Binding::Process);
        let Some(crate::wandb_internal::accelerator_metrics::Vendor::Nvidia(nvidia)) =
            &device.vendor
        else {
            panic!("no NVIDIA fields");
        };
        assert_eq!(nvidia.sm_active_ratio, Some(0.5));
    }
}
