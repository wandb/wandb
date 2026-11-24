//! Builds the record one client receives from a [`Sample`].
//!
//! A sample covers every device and every process. A client sees only the
//! GPUs it asked for, each with its binding to the client's process: PROCESS
//! for the GPUs the process uses, and what its job says for the others.

use std::collections::{HashMap, HashSet};

use crate::job::Job;
use crate::metrics::{self, Field, Readings, Sample};
use crate::wandb_internal::{AcceleratorType, Binding, SystemMetricsRecord};

/// The typed record for a client monitoring the processes in `pids`, which
/// belong to `job`.
///
/// `scoped` holds the readings specific to this client and `values` its
/// averages and its counters since their baselines. An empty
/// `gpu_device_ids` selects every GPU.
pub fn typed_record(
    sample: &Sample,
    scoped: Option<&Readings>,
    values: &[(Field, f64)],
    pids: &[u32],
    job: &Job,
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
    // DCGM knows a GPU by its index. Its entry takes the identity NVML has
    // for that GPU, so a reader can tell that the two are one device.
    let identities: HashMap<u32, (String, String, String)> = record
        .accelerators
        .iter()
        .filter(|device| device.source == "nvml" && device.parent_uuid.is_empty())
        .map(|device| {
            let identity = (
                device.uuid.clone(),
                device.model.clone(),
                device.pci_bus_id.clone(),
            );
            (device.index, identity)
        })
        .collect();
    for device in &mut record.accelerators {
        if device.source == "dcgm" {
            if let Some((uuid, model, pci_bus_id)) = identities.get(&device.index) {
                device.uuid.clone_from(uuid);
                device.model.clone_from(model);
                device.pci_bus_id.clone_from(pci_bus_id);
            }
            continue;
        }
        // Only NVML lists the processes on a device.
        if device.source == "nvml"
            && let Some(users) = sample.gpu_pids.get(&device.uuid)
        {
            device.process_count = Some(users.len() as u32);
        }
        device.set_binding(if gpus_in_use.contains(device.uuid.as_str()) {
            Binding::Process
        } else {
            job.binding(device)
        });
    }
    // After the device filter, which does not apply to scoped readings.
    if let Some(readings) = scoped {
        metrics::merge(&mut record, &readings.record);
    }
    record
}

/// The uuids of the GPUs any of the processes in `pids` use.
fn gpus_in_use<'a>(sample: &'a Sample, pids: &[u32]) -> HashSet<&'a str> {
    sample
        .gpu_pids
        .iter()
        .filter(|(_, users)| users.iter().any(|pid| pids.contains(pid)))
        .map(|(uuid, _)| uuid.as_str())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::NvidiaRate;
    use crate::wandb_internal::AcceleratorMetrics;

    #[test]
    fn binds_gpus_to_the_process_then_the_job_and_counts_their_processes() {
        let gpu = |index, source: &str| AcceleratorMetrics {
            r#type: AcceleratorType::NvidiaGpu as i32,
            index,
            uuid: if source == "nvml" {
                format!("GPU-{index}")
            } else {
                String::new()
            },
            source: source.to_string(),
            ..Default::default()
        };
        let sample = Sample {
            record: SystemMetricsRecord {
                accelerators: vec![gpu(0, "nvml"), gpu(1, "nvml"), gpu(1, "dcgm")],
                ..Default::default()
            },
            gpu_pids: [
                ("GPU-0".to_string(), vec![42]),
                ("GPU-1".to_string(), vec![7, 8]),
            ]
            .into(),
            ..Default::default()
        };

        let record = typed_record(&sample, None, &[], &[42], &Job::default(), &[]);

        let bound: Vec<_> = record
            .accelerators
            .iter()
            .map(|device| (device.uuid.as_str(), device.binding(), device.process_count))
            .collect();
        assert_eq!(
            bound,
            [
                ("GPU-0", Binding::Process, Some(1)),
                ("GPU-1", Binding::Visible, Some(2)),
                ("GPU-1", Binding::Unspecified, None),
            ]
        );
    }

    #[test]
    fn typed_record_sets_averages_filters_gpus_and_binds_them() {
        let gpu = |index| AcceleratorMetrics {
            r#type: AcceleratorType::NvidiaGpu as i32,
            index,
            uuid: format!("GPU-{index}"),
            source: "nvml".to_string(),
            ..Default::default()
        };
        let sample = Sample {
            record: SystemMetricsRecord {
                accelerators: vec![gpu(0), gpu(1)],
                ..Default::default()
            },
            gpu_pids: [
                ("GPU-0".to_string(), vec![42]),
                ("GPU-1".to_string(), vec![7]),
            ]
            .into(),
            ..Default::default()
        };
        let values = [
            (Field::Nvidia("nvml", 0, NvidiaRate::SmActive), 0.5),
            (Field::Nvidia("nvml", 1, NvidiaRate::SmActive), 0.51),
        ];

        let record = typed_record(&sample, None, &values, &[42], &Job::default(), &[0]);

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
