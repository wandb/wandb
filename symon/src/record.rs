//! Builds the metrics one client receives from a [`Sample`].
//!
//! A sample covers every device and every process. A client sees only the
//! GPUs it asked for. In its typed record the GPUs its process uses have the
//! PROCESS binding; in its legacy items they get `gpu.process.<i>.*` copies.

use std::collections::HashSet;

use crate::metrics::{self, Field, Readings, Sample};
use crate::wandb_internal::{Binding, StatsItem, SystemMetricsRecord};

/// Metrics repeated under `gpu.process.<i>.` when the monitored process uses GPU `i`.
const PROCESS_METRICS: &[&str] = &[
    "gpu",
    "memory",
    "memoryAllocated",
    "memoryAllocatedBytes",
    "temp",
    "powerWatts",
    "enforcedPowerLimitWatts",
    "powerPercent",
];

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
    record.accelerators.retain(|device| {
        gpu_device_ids.is_empty() || gpu_device_ids.contains(&(device.index as i32))
    });
    for device in &mut record.accelerators {
        if sample.gpu_pids.contains_key(&device.index) {
            device.set_binding(if gpus_in_use.contains(&device.index) {
                Binding::Process
            } else {
                Binding::Visible
            });
        }
    }
    if let Some(readings) = scoped {
        metrics::merge(&mut record, &readings.record);
    }
    for (field, value) in values {
        field.set(&mut record, *value);
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

/// The stats items for a client monitoring the processes in `pids`.
///
/// `values` are the readings specific to this client: its averages, its
/// counters since their baselines and its scope's host metrics. An empty
/// `gpu_device_ids` selects every GPU.
pub fn stats_items(
    sample: &Sample,
    values: &[(String, f64)],
    pids: &[u32],
    gpu_device_ids: &[i32],
) -> Vec<StatsItem> {
    let gpus_in_use = gpus_in_use(sample, pids);

    let mut items = Vec::new();
    let mut push = |key: &str, value_json: String| {
        let gpu = gpu_key(key);
        if let Some((device, _)) = gpu
            && !gpu_device_ids.is_empty()
            && !gpu_device_ids.contains(&(device as i32))
        {
            return;
        }
        items.push(StatsItem {
            key: key.to_string(),
            value_json: value_json.clone(),
        });
        if let Some((device, name)) = gpu
            && gpus_in_use.contains(&device)
            && PROCESS_METRICS.contains(&name)
        {
            items.push(StatsItem {
                key: format!("gpu.process.{device}.{name}"),
                value_json,
            });
        }
    };

    for (key, value) in &sample.metrics {
        if key.starts_with('_') {
            continue;
        }
        if let Ok(value_json) = serde_json::to_string(value) {
            push(key, value_json);
        }
    }
    for (key, value) in values {
        if let Ok(value_json) = serde_json::to_string(value) {
            push(key, value_json);
        }
    }
    items
}

/// Splits `gpu.<index>.<name>` into its index and name.
fn gpu_key(key: &str) -> Option<(u32, &str)> {
    let (index, name) = key.strip_prefix("gpu.")?.split_once('.')?;
    Some((index.parse().ok()?, name))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::MetricValue;

    fn keys(items: &[StatsItem]) -> Vec<&str> {
        items.iter().map(|item| item.key.as_str()).collect()
    }

    #[test]
    fn filters_gpus_and_mirrors_process_metrics() {
        let sample = Sample {
            metrics: vec![
                (
                    "_gpu.0.name".to_string(),
                    MetricValue::String("H100".into()),
                ),
                ("gpu.0.temp".to_string(), MetricValue::Float(60.0)),
                ("gpu.0.smClock".to_string(), MetricValue::Int(1980)),
                ("gpu.1.temp".to_string(), MetricValue::Float(61.0)),
                ("tpu.0.dutyCycle".to_string(), MetricValue::Float(0.5)),
            ],
            gpu_pids: [(0, vec![42]), (1, vec![42])].into(),
            ..Default::default()
        };
        let averages = [
            ("gpu.0.smActive".to_string(), 50.0),
            ("gpu.1.smActive".to_string(), 51.0),
        ];

        let items = stats_items(&sample, &averages, &[7, 42], &[0]);
        assert_eq!(
            keys(&items),
            [
                "gpu.0.temp",
                "gpu.process.0.temp",
                "gpu.0.smClock",
                "tpu.0.dutyCycle",
                "gpu.0.smActive",
            ]
        );
        assert_eq!(items[1].value_json, "60.0");

        let items = stats_items(&sample, &averages, &[], &[]);
        assert_eq!(
            keys(&items),
            [
                "gpu.0.temp",
                "gpu.0.smClock",
                "gpu.1.temp",
                "tpu.0.dutyCycle",
                "gpu.0.smActive",
                "gpu.1.smActive",
            ]
        );
    }
}
