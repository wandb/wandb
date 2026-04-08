use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(untagged)] // This makes the enum serialize to just the inner value without the variant name
pub enum MetricValue {
    Int(i64),
    Float(f64),
    String(String),
}
