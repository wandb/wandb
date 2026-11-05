//! AWS Trainium metrics via neuron-monitor.
//!
//! `neuron-monitor -c <config>` prints one JSON report per period on its
//! stdout. The latest report is kept, and each subscriber gets the
//! `neuron_runtime_data` entry of its process as typed NeuronCores and host
//! memory.

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use log::debug;
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

use crate::metrics::{MetricValue, Readings, Sample, Scope};
use crate::monitors::Collector;
use crate::wandb_internal::{
    AcceleratorMetrics, AcceleratorType, EnvironmentRecord, SystemMetricsRecord,
    TrainiumHostMetrics, TrainiumInfo, TrainiumMetrics, accelerator_metrics::Vendor,
};

const DEFAULT_BINARY: &str = "/opt/aws/neuron/bin/neuron-monitor";

/// The neuron-monitor configuration used when the subscriber gives none.
const DEFAULT_CONFIG: &str = r#"{
  "period": "1s",
  "neuron_runtimes": [
    {
      "tag_filter": ".*",
      "metrics": [
        {"type": "neuroncore_counters"},
        {"type": "memory_used"},
        {"type": "neuron_runtime_vcpu_usage"}
      ]
    }
  ],
  "system_metrics": [
    {"type": "vcpu_usage"},
    {"type": "memory_info"},
    {"type": "neuron_hw_counters"}
  ]
}"#;

pub struct Trainium {
    binary: PathBuf,
    /// The neuron-monitor process, started on the first sweep with a subscriber.
    child: Mutex<Option<Child>>,
    /// The latest report neuron-monitor printed.
    latest: Arc<Mutex<Option<Value>>>,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

impl Trainium {
    /// Returns None unless neuron-monitor is installed.
    pub fn new() -> Option<Self> {
        let on_path = std::env::var_os("PATH").map(|path| {
            std::env::split_paths(&path)
                .map(|dir| dir.join("neuron-monitor"))
                .collect::<Vec<_>>()
        });
        let binary = on_path
            .unwrap_or_default()
            .into_iter()
            .chain(std::iter::once(PathBuf::from(DEFAULT_BINARY)))
            .find(|path| path.is_file())?;
        debug!("Trainium: using {}", binary.display());
        Some(Self {
            binary,
            child: Mutex::new(None),
            latest: Arc::default(),
        })
    }

    /// Starts neuron-monitor unless it is running.
    fn start(&self, scopes: &[Scope]) -> std::io::Result<()> {
        let mut child = lock(&self.child);
        if child.is_some() {
            return Ok(());
        }
        let config = match scopes
            .iter()
            .find(|scope| !scope.neuron_monitor_config_path.is_empty())
        {
            Some(scope) => PathBuf::from(&scope.neuron_monitor_config_path),
            None => {
                // neuron-monitor averages over its period, so use the
                // sampling interval like wandb-core did.
                let period = scopes
                    .iter()
                    .map(|scope| scope.interval.as_secs())
                    .min()
                    .unwrap_or(1)
                    .max(1);
                let path = std::env::temp_dir().join("neuron_monitor_config.json");
                std::fs::write(&path, DEFAULT_CONFIG.replace("1s", &format!("{period}s")))?;
                path
            }
        };
        let mut process = Command::new(&self.binary)
            .arg("-c")
            .arg(config)
            .stdout(Stdio::piped())
            .kill_on_drop(true)
            .spawn()?;
        let stdout = process.stdout.take().expect("stdout is piped");
        let latest = self.latest.clone();
        tokio::spawn(async move {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                match serde_json::from_str(&line) {
                    Ok(report) => *lock(&latest) = Some(report),
                    Err(e) => debug!("Trainium: unparseable neuron-monitor output: {e}"),
                }
            }
        });
        *child = Some(process);
        Ok(())
    }
}

#[async_trait::async_trait]
impl Collector for Trainium {
    async fn collect_metrics(
        &self,
        scopes: &[Scope],
    ) -> Result<Sample, Box<dyn std::error::Error>> {
        let mut sample = Sample::default();
        if scopes.is_empty() {
            return Ok(sample);
        }
        self.start(scopes)?;
        let latest = lock(&self.latest);
        let Some(report) = latest.as_ref() else {
            return Ok(sample);
        };
        // Under torchrun, each process reports the NeuronCore of its rank.
        let local_rank = std::env::var("LOCAL_RANK")
            .ok()
            .filter(|rank| !rank.is_empty());
        let entries = report["neuron_runtime_data"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default();
        for scope in scopes {
            let entry = entries.iter().find(|entry| {
                entry["pid"]
                    .as_f64()
                    .is_some_and(|pid| pid == scope.pid as f64 || local_rank.is_some())
            });
            let Some(entry) = entry else {
                continue;
            };
            let record = record(&entry["report"], local_rank.as_deref());
            if record != SystemMetricsRecord::default() {
                sample.scoped.insert(
                    scope.clone(),
                    Readings {
                        record,
                        ..Default::default()
                    },
                );
            }
        }
        Ok(sample)
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &MetricValue>,
    ) -> EnvironmentRecord {
        let mut metadata = EnvironmentRecord::default();
        // neuron-monitor may take a few seconds to print its first report.
        for _ in 0..50 {
            if let Some(info) = lock(&self.latest)
                .as_ref()
                .map(|report| &report["neuron_hardware_info"])
                .filter(|info| info.is_object())
            {
                metadata.trainium = Some(TrainiumInfo {
                    name: "Trainium".to_string(),
                    vendor: "AWS".to_string(),
                    neuron_device_count: info["neuron_device_count"].as_u64().unwrap_or(0) as u32,
                    neuroncore_per_device_count: info["neuroncore_per_device_count"]
                        .as_u64()
                        .unwrap_or(0) as u32,
                });
                return metadata;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        metadata
    }

    fn shutdown(&self) {
        if let Some(mut child) = lock(&self.child).take() {
            let _ = child.start_kill();
        }
    }
}

/// The typed record of a `neuron_runtime_data` report: an accelerator per
/// NeuronCore and the host memory. With `local_rank` set, only that
/// NeuronCore is reported.
fn record(report: &Value, local_rank: Option<&str>) -> SystemMetricsRecord {
    let keep = |core: &str| local_rank.is_none_or(|rank| rank == core);
    let bytes = |value: &Value| value.as_f64().map(|value| value as u64);
    let mut cores: BTreeMap<u32, AcceleratorMetrics> = BTreeMap::new();

    for (name, counters) in fields(&report["neuroncore_counters"]["neuroncores_in_use"]) {
        if keep(name)
            && let Some(device) = neuroncore(&mut cores, name)
        {
            device.utilization_ratio = counters["neuroncore_utilization"]
                .as_f64()
                .map(|percent| percent / 100.0);
        }
    }
    let used = &report["memory_used"]["neuron_runtime_used_bytes"];
    for (name, usage) in fields(&used["usage_breakdown"]["neuroncore_memory_usage"]) {
        if keep(name)
            && let Some(device) = neuroncore(&mut cores, name)
            && let Some(Vendor::Trainium(trainium)) = &mut device.vendor
        {
            trainium.memory_constants_bytes = bytes(&usage["constants"]);
            trainium.memory_model_code_bytes = bytes(&usage["model_code"]);
            trainium.memory_model_shared_scratchpad_bytes =
                bytes(&usage["model_shared_scratchpad"]);
            trainium.memory_runtime_bytes = bytes(&usage["runtime_memory"]);
            trainium.memory_tensors_bytes = bytes(&usage["tensors"]);
        }
    }

    let host = &used["usage_breakdown"]["host"];
    let trainium_host = TrainiumHostMetrics {
        host_memory_bytes: bytes(&used["host"]),
        device_memory_bytes: bytes(&used["neuron_device"]),
        host_memory_application_bytes: bytes(&host["application_memory"]),
        host_memory_constants_bytes: bytes(&host["constants"]),
        host_memory_dma_buffers_bytes: bytes(&host["dma_buffers"]),
        host_memory_tensors_bytes: bytes(&host["tensors"]),
    };
    SystemMetricsRecord {
        accelerators: cores.into_values().collect(),
        trainium_host: (trainium_host != TrainiumHostMetrics::default()).then_some(trainium_host),
        ..Default::default()
    }
}

/// The accelerator of the NeuronCore named `name`, added if missing.
fn neuroncore<'a>(
    cores: &'a mut BTreeMap<u32, AcceleratorMetrics>,
    name: &str,
) -> Option<&'a mut AcceleratorMetrics> {
    let index = name.parse().ok()?;
    Some(cores.entry(index).or_insert_with(|| AcceleratorMetrics {
        r#type: AcceleratorType::AwsTrainium as i32,
        index,
        source: "neuron-monitor".to_string(),
        vendor: Some(Vendor::Trainium(TrainiumMetrics::default())),
        ..Default::default()
    }))
}

/// The fields of a JSON object; none for any other value.
fn fields(value: &Value) -> impl Iterator<Item = (&str, &Value)> {
    value
        .as_object()
        .into_iter()
        .flatten()
        .map(|(key, value)| (key.as_str(), value))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_a_report_into_neuroncores_and_host_memory() {
        let report = serde_json::json!({
            "neuroncore_counters": {
                "neuroncores_in_use": {"0": {"neuroncore_utilization": 1.3631567613356375}}
            },
            "memory_used": {
                "neuron_runtime_used_bytes": {
                    "host": 610705408,
                    "neuron_device": 102298328,
                    "usage_breakdown": {
                        "host": {
                            "application_memory": 609656832,
                            "constants": 0,
                            "dma_buffers": 1048576,
                            "tensors": 0
                        },
                        "neuroncore_memory_usage": {
                            "0": {
                                "constants": 196608,
                                "model_code": 101125344,
                                "model_shared_scratchpad": 0,
                                "runtime_memory": 0,
                                "tensors": 943608
                            }
                        }
                    }
                }
            }
        });

        let record = record(&report, Some("0"));

        let host = record.trainium_host.unwrap();
        assert_eq!(host.host_memory_bytes, Some(610705408));
        assert_eq!(host.device_memory_bytes, Some(102298328));
        assert_eq!(host.host_memory_application_bytes, Some(609656832));
        let [core] = record.accelerators.as_slice() else {
            panic!("expected one NeuronCore");
        };
        assert_eq!(core.utilization_ratio, Some(1.3631567613356375 / 100.0));
        let Some(Vendor::Trainium(memory)) = &core.vendor else {
            panic!("no Trainium fields");
        };
        assert_eq!(memory.memory_model_code_bytes, Some(101125344));
    }
}
