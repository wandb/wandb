use serde::Serialize;
use std::collections::HashMap;

use crate::wandb_internal::SubscribeRequest;

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(untagged)] // This makes the enum serialize to just the inner value without the variant name
pub enum MetricValue {
    Int(i64),
    Float(f64),
    String(String),
}

/// The parts of a subscription that select what the host collector reads
/// for it. Subscribers with equal scopes share one set of readings.
#[derive(Debug, Default, Clone, PartialEq, Eq, Hash)]
pub struct Scope {
    pub pid: u32,
    pub track_process_tree: bool,
    pub disable_cgroup: bool,
    pub wandb_pids: Vec<u32>,
    pub disk_paths: Vec<String>,
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
        Self {
            pid: request.pid.max(0) as u32,
            track_process_tree: request.track_process_tree,
            disable_cgroup: request.disable_cgroup,
            wandb_pids,
            disk_paths: request.disk_paths.clone(),
        }
    }
}

/// The host readings for one scope, in their reported units.
#[derive(Debug, Default)]
pub struct Readings {
    /// Point-in-time readings keyed by metric name.
    pub metrics: Vec<(String, f64)>,
    /// Readings that describe the time since the previous sample.
    pub averages: Vec<(String, f64)>,
    /// Counters that only grow. A subscriber receives their increase since
    /// its first sample.
    pub counters: Vec<(String, f64)>,
}

impl Readings {
    pub fn metric(&mut self, key: impl Into<String>, value: f64) {
        self.metrics.push((key.into(), value));
    }

    pub fn average(&mut self, key: impl Into<String>, value: f64) {
        self.averages.push((key.into(), value));
    }

    pub fn counter(&mut self, key: impl Into<String>, value: f64) {
        self.counters.push((key.into(), value));
    }
}

/// One pass over every collector.
#[derive(Debug, Default)]
pub struct Sample {
    /// Point-in-time readings keyed by metric name. Keys starting with `_`
    /// are static facts used for metadata and are not reported as metrics.
    pub metrics: Vec<(String, MetricValue)>,

    /// Readings that describe the time since the previous sample, such as
    /// GPM utilization. A subscriber receives their mean over its interval.
    pub averages: Vec<(String, f64)>,

    /// Host-wide counters that only grow, such as bytes sent over the
    /// network. A subscriber receives their increase since its first sample.
    pub counters: Vec<(String, f64)>,

    /// The host readings that depend on the subscriber, by scope.
    pub scoped: HashMap<Scope, Readings>,

    /// PIDs of the processes using each GPU, by device index.
    pub gpu_pids: HashMap<u32, Vec<u32>>,
}
