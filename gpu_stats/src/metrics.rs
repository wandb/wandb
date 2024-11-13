pub enum MetricValue {
    Int(i64),
    Float(f64),
    String(String),
}

impl ToString for MetricValue {
    fn to_string(&self) -> String {
        match self {
            MetricValue::Int(i) => i.to_string(),
            MetricValue::Float(f) => f.to_string(),
            MetricValue::String(s) => s.to_string(),
        }
    }
}
