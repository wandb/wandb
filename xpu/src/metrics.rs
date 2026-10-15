use serde::Serialize;
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(untagged)] // This makes the enum serialize to just the inner value without the variant name
pub enum MetricValue {
    Int(i64),
    Float(f64),
    String(String),
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

    /// PIDs of the processes using each GPU, by device index.
    pub gpu_pids: HashMap<u32, Vec<u32>>,
}
