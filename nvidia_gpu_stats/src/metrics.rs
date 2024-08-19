use serde::Serialize;
use std::collections::BTreeMap;
use std::io;

/// System metrics storage.
///
/// Metrics are stored in a BTreeMap to ensure consistent ordering of keys
/// in the output JSON. The output map is flat to make it easier to parse
/// in downstream applications.
#[derive(Serialize)]
pub struct Metrics {
    #[serde(flatten)]
    metrics: BTreeMap<String, serde_json::Value>,
}

impl Metrics {
    pub fn new() -> Self {
        Metrics {
            metrics: BTreeMap::new(),
        }
    }

    pub fn add_metric<T: Into<serde_json::Value>>(&mut self, key: &str, value: T) {
        self.metrics.insert(key.to_string(), value.into());
    }

    pub fn add_timestamp(&mut self, timestamp: f64) {
        self.add_metric("_timestamp", timestamp);
    }

    /// Print the metrics as a JSON string to stdout.
    pub fn print_json(&self) -> io::Result<()> {
        let json_output = serde_json::to_string(&self.metrics)?;
        println!("{}", json_output);
        Ok(())
    }
}
