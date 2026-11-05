use serde::Serialize;
use std::collections::{BTreeMap, HashMap};
use std::time::Duration;

use prost::Message;

use crate::wandb_internal::{
    DiskIoMetrics, HostMetrics, NetworkMetrics, ProcessMetrics, ProcessStats, SdkMetrics,
    SubscribeRequest, SystemMetricsRecord,
};

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(untagged)] // This makes the enum serialize to just the inner value without the variant name
pub enum MetricValue {
    Int(i64),
    Float(f64),
    String(String),
}

/// One of the filters selecting the OpenMetrics samples a subscriber
/// receives.
#[derive(Debug, Default, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Filter {
    /// Matched against `<endpoint name>.<metric name>`.
    pub metric_regex: String,
    /// Label name to the regex its value must match. All must match.
    pub label_regexes: BTreeMap<String, String>,
}

/// The parts of a subscription that select what the host and scraping
/// collectors read for it. Subscribers with equal scopes share one set of
/// readings.
#[derive(Debug, Default, Clone, PartialEq, Eq, Hash)]
pub struct Scope {
    /// The subscriber's sampling interval.
    pub interval: Duration,
    pub pid: u32,
    pub track_process_tree: bool,
    pub disable_cgroup: bool,
    pub wandb_pids: Vec<u32>,
    pub disk_paths: Vec<String>,
    /// OpenMetrics endpoint URLs by name.
    pub open_metrics_endpoints: BTreeMap<String, String>,
    pub open_metrics_filters: Vec<Filter>,
    pub open_metrics_http_headers: BTreeMap<String, String>,
    /// Prometheus instant-query URL of a DCGM exporter, or empty.
    pub dcgm_exporter: String,
    pub neuron_monitor_config_path: String,
    /// Whether the subscriber gets the host details wandb leet symon shows.
    pub host_details: bool,
}

impl From<&SubscribeRequest> for Scope {
    fn from(request: &SubscribeRequest) -> Self {
        let mut wandb_pids: Vec<u32> = request
            .wandb_pids
            .iter()
            .filter(|pid| **pid > 0)
            .map(|pid| *pid as u32)
            .collect();
        wandb_pids.sort_unstable();
        wandb_pids.dedup();
        let mut open_metrics_filters: Vec<Filter> = request
            .open_metrics_filters
            .iter()
            .map(|filter| Filter {
                metric_regex: filter.metric_regex.clone(),
                label_regexes: filter.label_regexes.clone().into_iter().collect(),
            })
            .collect();
        open_metrics_filters.sort();
        open_metrics_filters.dedup();
        Self {
            interval: Duration::from_millis((request.interval_seconds.max(0.0) * 1000.0) as u64),
            pid: request.pid.max(0) as u32,
            track_process_tree: request.track_process_tree,
            disable_cgroup: request.disable_cgroup,
            wandb_pids,
            disk_paths: request.disk_paths.clone(),
            open_metrics_endpoints: request.open_metrics_endpoints.clone().into_iter().collect(),
            open_metrics_filters,
            open_metrics_http_headers: request
                .open_metrics_http_headers
                .clone()
                .into_iter()
                .collect(),
            dcgm_exporter: request.dcgm_exporter.clone(),
            neuron_monitor_config_path: request.neuron_monitor_config_path.clone(),
            host_details: request.host_details,
        }
    }
}

/// A reading that a subscriber averages over its interval or counts from its
/// first sample: a typed record field, or a legacy metric name for the
/// collectors that do not fill the typed record yet.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Key {
    Legacy(String),
    Field(Field),
}

impl From<&str> for Key {
    fn from(key: &str) -> Self {
        Key::Legacy(key.to_string())
    }
}

impl From<String> for Key {
    fn from(key: String) -> Self {
        Key::Legacy(key)
    }
}

impl From<Field> for Key {
    fn from(field: Field) -> Self {
        Key::Field(field)
    }
}

/// The typed record fields that are averaged or counted.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Field {
    ProcessCpu,
    ProcessCpuUser,
    ProcessCpuSystem,
    ProcessCgroupCpuThrottled,
    ProcessCgroupOomKills,
    SdkCpu,
    SdkCpuUser,
    SdkCpuSystem,
    DiskRead(String),
    DiskWrite(String),
    NetworkSent,
    NetworkRecv,
    NetworkTcpRetransmits,
}

impl Field {
    /// Sets this field of `record` to `value`.
    pub fn set(&self, record: &mut SystemMetricsRecord, value: f64) {
        let count = value.max(0.0) as u64;
        match self {
            Field::ProcessCpu => process(record).cpu_ratio = Some(value),
            Field::ProcessCpuUser => process(record).cpu_user_ratio = Some(value),
            Field::ProcessCpuSystem => process(record).cpu_system_ratio = Some(value),
            Field::ProcessCgroupCpuThrottled => {
                process(record).cgroup_cpu_throttled_ratio = Some(value)
            }
            Field::ProcessCgroupOomKills => process(record).cgroup_oom_kills = Some(count),
            Field::SdkCpu => sdk(record).cpu_ratio = Some(value),
            Field::SdkCpuUser => sdk(record).cpu_user_ratio = Some(value),
            Field::SdkCpuSystem => sdk(record).cpu_system_ratio = Some(value),
            Field::DiskRead(device) | Field::DiskWrite(device) => {
                let disk_io = &mut record.host.get_or_insert_with(HostMetrics::default).disk_io;
                let index = match disk_io.iter().position(|io| io.device == *device) {
                    Some(index) => index,
                    None => {
                        disk_io.push(DiskIoMetrics {
                            device: device.clone(),
                            ..Default::default()
                        });
                        disk_io.len() - 1
                    }
                };
                if matches!(self, Field::DiskRead(_)) {
                    disk_io[index].read_bytes = Some(count);
                } else {
                    disk_io[index].write_bytes = Some(count);
                }
            }
            Field::NetworkSent => network(record).sent_bytes = Some(count),
            Field::NetworkRecv => network(record).recv_bytes = Some(count),
            Field::NetworkTcpRetransmits => network(record).tcp_retransmits = Some(count),
        }
    }
}

fn process(record: &mut SystemMetricsRecord) -> &mut ProcessMetrics {
    record.process.get_or_insert_with(ProcessMetrics::default)
}

fn sdk(record: &mut SystemMetricsRecord) -> &mut SdkMetrics {
    record.sdk.get_or_insert_with(SdkMetrics::default)
}

fn network(record: &mut SystemMetricsRecord) -> &mut NetworkMetrics {
    record
        .host
        .get_or_insert_with(HostMetrics::default)
        .network
        .get_or_insert_with(NetworkMetrics::default)
}

/// Merges `other` into `record` with protobuf merge semantics: set fields
/// replace, repeated fields append and messages merge.
pub fn merge(record: &mut SystemMetricsRecord, other: &SystemMetricsRecord) {
    if *other != SystemMetricsRecord::default() {
        // Decoding what prost just encoded cannot fail.
        let _ = record.merge(other.encode_to_vec().as_slice());
    }
}

/// The host readings for one scope, in their reported units.
#[derive(Debug, Default)]
pub struct Readings {
    /// Point-in-time readings in the typed record.
    pub record: SystemMetricsRecord,
    /// Point-in-time readings keyed by metric name.
    pub metrics: Vec<(String, f64)>,
    /// Readings that describe the time since the previous sample.
    pub averages: Vec<(Key, f64)>,
    /// Counters that only grow. A subscriber receives their increase since
    /// its first sample.
    pub counters: Vec<(Key, f64)>,
    /// The monitored process and its descendants, whose use of a GPU is
    /// reported under `gpu.process.<i>.*`.
    pub pids: Vec<u32>,
}

impl Readings {
    pub fn average(&mut self, key: impl Into<Key>, value: f64) {
        self.averages.push((key.into(), value));
    }

    pub fn counter(&mut self, key: impl Into<Key>, value: f64) {
        self.counters.push((key.into(), value));
    }
}

/// One pass over every collector.
#[derive(Debug, Default)]
pub struct Sample {
    /// Point-in-time readings in the typed record.
    pub record: SystemMetricsRecord,

    /// Point-in-time readings keyed by metric name. Keys starting with `_`
    /// are static facts used for metadata and are not reported as metrics.
    pub metrics: Vec<(String, MetricValue)>,

    /// Readings that describe the time since the previous sample, such as
    /// GPM utilization. A subscriber receives their mean over its interval.
    pub averages: Vec<(Key, f64)>,

    /// Host-wide counters that only grow, such as bytes sent over the
    /// network. A subscriber receives their increase since its first sample.
    pub counters: Vec<(Key, f64)>,

    /// The host readings that depend on the subscriber, by scope.
    pub scoped: HashMap<Scope, Readings>,

    /// PIDs of the processes using each GPU, by device index.
    pub gpu_pids: HashMap<u32, Vec<u32>>,

    /// Every process on the host, read when a scope asks for host details.
    pub processes: Vec<ProcessStats>,
}

impl Sample {
    /// Adds another collector's readings to this sample.
    pub fn merge(&mut self, other: Sample) {
        merge(&mut self.record, &other.record);
        self.metrics.extend(other.metrics);
        self.averages.extend(other.averages);
        self.counters.extend(other.counters);
        self.gpu_pids.extend(other.gpu_pids);
        self.processes.extend(other.processes);
        for (scope, readings) in other.scoped {
            let mine = self.scoped.entry(scope).or_default();
            merge(&mut mine.record, &readings.record);
            mine.metrics.extend(readings.metrics);
            mine.averages.extend(readings.averages);
            mine.counters.extend(readings.counters);
            mine.pids.extend(readings.pids);
        }
    }
}
