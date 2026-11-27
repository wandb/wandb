//! Run metadata: config, summary, environment, and identity.

use serde_json::{Map, Value};

use crate::msg::RunMsg;
use crate::pagedlist::KeyValuePair;
use crate::store::proto::{ConfigRecord, EnvironmentRecord, SummaryRecord};

/// The current state of the run.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RunState {
    #[default]
    Unknown,
    Running,
    Finished,
    Failed,
    Crashed,
}

impl RunState {
    pub fn as_str(&self) -> &'static str {
        match self {
            RunState::Running => "Running",
            RunState::Finished => "Finished",
            RunState::Failed => "Failed",
            RunState::Crashed => "Error",
            RunState::Unknown => "Unknown",
        }
    }
}

/// Processes and stores run metadata.
#[derive(Default)]
pub struct RunOverview {
    run_id: String,
    display_name: String,
    project: String,
    notes: String,
    tags: Vec<String>,
    config: Map<String, Value>,
    summary: Map<String, Value>,
    environment: Option<EnvironmentRecord>,
    run_state: RunState,
}

impl RunOverview {
    pub fn new() -> Self {
        Self::default()
    }

    /// A string representation of the run state.
    pub fn state_string(&self) -> &'static str {
        self.run_state.as_str()
    }

    /// Processes a run message and updates internal state.
    pub fn process_run_msg(&mut self, msg: &RunMsg) {
        self.run_id = msg.id.clone();
        self.display_name = msg.display_name.clone();
        self.project = msg.project.clone();
        self.notes = msg.notes.clone();
        self.tags = dedup_strings(&msg.tags);
        self.run_state = RunState::Running;

        if let Some(config) = &msg.config {
            self.apply_config_record(config);
        }
    }

    fn apply_config_record(&mut self, record: &ConfigRecord) {
        for item in &record.update {
            let Some(value) = parse_json_ext(&item.value_json) else {
                continue;
            };
            let path = key_path(&item.key, &item.nested_key);
            match value {
                Value::Object(map) => set_subtree(&mut self.config, &path, map),
                other => set_path(&mut self.config, &path, other),
            }
        }
        for item in &record.remove {
            remove_path(&mut self.config, &key_path(&item.key, &item.nested_key));
        }
    }

    /// Processes system/environment information (merged across records).
    pub fn process_system_info(&mut self, record: &EnvironmentRecord) {
        match &mut self.environment {
            Some(env) => merge_environment(env, record),
            None => self.environment = Some(record.clone()),
        }
    }

    /// Processes summary data.
    pub fn process_summary(&mut self, records: &[SummaryRecord]) {
        for record in records {
            for item in &record.update {
                let Some(value) = parse_json_ext(&item.value_json) else {
                    continue;
                };
                let path = key_path(&item.key, &item.nested_key);
                set_path(&mut self.summary, &path, value);
            }
            for item in &record.remove {
                remove_path(&mut self.summary, &key_path(&item.key, &item.nested_key));
            }
        }
    }

    pub fn set_run_state(&mut self, state: RunState) {
        self.run_state = state;
    }

    // ---- Data accessors ----

    pub fn id(&self) -> &str {
        &self.run_id
    }

    pub fn display_name(&self) -> &str {
        &self.display_name
    }

    pub fn project(&self) -> &str {
        &self.project
    }

    pub fn notes(&self) -> &str {
        &self.notes
    }

    pub fn tags(&self) -> &[String] {
        &self.tags
    }

    pub fn state(&self) -> RunState {
        self.run_state
    }

    /// Environment data as key-value pairs.
    pub fn environment_items(&self) -> Vec<KeyValuePair> {
        let Some(env) = &self.environment else {
            return Vec::new();
        };
        let map = environment_to_json(env);
        let mut items = Vec::new();
        flatten_map(&map, "", &mut items, &[]);
        items
    }

    /// Config data as key-value pairs.
    pub fn config_items(&self) -> Vec<KeyValuePair> {
        let mut items = Vec::new();
        flatten_map(&self.config, "", &mut items, &[]);
        items
    }

    /// Summary data as key-value pairs.
    pub fn summary_items(&self) -> Vec<KeyValuePair> {
        let mut items = Vec::new();
        flatten_map(&self.summary, "", &mut items, &[]);
        items
    }
}

fn key_path(key: &str, nested_key: &[String]) -> Vec<String> {
    if !nested_key.is_empty() {
        nested_key.to_vec()
    } else {
        vec![key.to_string()]
    }
}

/// Parses JSON with support for the bare NaN/Infinity tokens produced by
/// W&B's extended JSON encoder.
pub fn parse_json_ext(s: &str) -> Option<Value> {
    match s.trim() {
        "NaN" => Some(Value::from(f64::NAN)),
        "Infinity" => Some(Value::from(f64::INFINITY)),
        "-Infinity" => Some(Value::from(f64::NEG_INFINITY)),
        trimmed => serde_json::from_str(trimmed).ok(),
    }
}

// ---- Path tree operations over serde_json maps ----

fn set_path(tree: &mut Map<String, Value>, path: &[String], value: Value) {
    let Some((last, prefix)) = path.split_last() else {
        return;
    };
    let mut node = tree;
    for key in prefix {
        let entry = node
            .entry(key.clone())
            .or_insert_with(|| Value::Object(Map::new()));
        if !entry.is_object() {
            *entry = Value::Object(Map::new());
        }
        node = entry.as_object_mut().expect("just ensured object");
    }
    node.insert(last.clone(), value);
}

/// Deep-merges `subtree` at `path`, setting leaves individually.
fn set_subtree(tree: &mut Map<String, Value>, path: &[String], subtree: Map<String, Value>) {
    for (key, value) in subtree {
        let mut child_path = path.to_vec();
        child_path.push(key);
        match value {
            Value::Object(map) => set_subtree(tree, &child_path, map),
            other => set_path(tree, &child_path, other),
        }
    }
}

fn remove_path(tree: &mut Map<String, Value>, path: &[String]) {
    fn inner(node: &mut Map<String, Value>, path: &[String]) -> bool {
        match path {
            [] => false,
            [last] => {
                node.remove(last);
                true
            }
            [head, rest @ ..] => {
                let Some(Value::Object(child)) = node.get_mut(head) else {
                    return false;
                };
                let removed = inner(child, rest);
                // Remove empty parents to avoid keeping around empty maps.
                if removed && child.is_empty() {
                    node.remove(head);
                }
                removed
            }
        }
    }
    inner(tree, path);
}

// ---- Flattening for display ----

/// Formats a leaf value the way Go's `fmt.Sprint` renders parsed JSON.
pub fn format_leaf(value: &Value) -> String {
    match value {
        Value::Null => "<nil>".to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => format_float_go(n.as_f64().unwrap_or(0.0)),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// Formats a float like Go's `fmt.Sprint(float64)`: shortest representation,
/// switching to scientific notation when the exponent is < -4 or >= 6.
pub fn format_float_go(v: f64) -> String {
    if v.is_nan() {
        return "NaN".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 { "+Inf" } else { "-Inf" }.to_string();
    }
    if v == 0.0 {
        return if v.is_sign_negative() { "-0" } else { "0" }.to_string();
    }

    let exp = v.abs().log10().floor() as i32;
    if !(-4..6).contains(&exp) {
        // Rust `{:e}` gives shortest mantissa like "1.6e7"; convert to Go's
        // "1.6e+07" style.
        let s = format!("{v:e}");
        if let Some(pos) = s.find('e') {
            let (mantissa, exp_str) = s.split_at(pos);
            let exp_num: i32 = exp_str[1..].parse().unwrap_or(0);
            return format!(
                "{mantissa}e{}{:02}",
                if exp_num < 0 { '-' } else { '+' },
                exp_num.abs()
            );
        }
        s
    } else {
        format!("{v}")
    }
}

/// Converts nested maps to flat key-value pairs.
///
/// Map keys are sorted (serde_json map iteration is insertion-ordered, so we
/// sort explicitly); slices are flattened using bracketed indices (a[0].b).
pub fn flatten_map(
    data: &Map<String, Value>,
    prefix: &str,
    result: &mut Vec<KeyValuePair>,
    path: &[String],
) {
    let mut keys: Vec<&String> = data.keys().collect();
    keys.sort();

    for k in keys {
        let v = &data[k.as_str()];
        let full_key = if prefix.is_empty() {
            k.to_string()
        } else {
            format!("{prefix}.{k}")
        };
        let mut current_path = path.to_vec();
        current_path.push(k.to_string());

        match v {
            Value::Object(map) => flatten_map(map, &full_key, result, &current_path),
            Value::Array(list) => flatten_slice(list, &full_key, result, &current_path),
            other => result.push(KeyValuePair {
                key: full_key,
                value: format_leaf(other),
                path: current_path,
            }),
        }
    }
}

/// Handles arrays by emitting `prefix[i]` and recursing as needed.
fn flatten_slice(list: &[Value], prefix: &str, result: &mut Vec<KeyValuePair>, path: &[String]) {
    for (i, elem) in list.iter().enumerate() {
        let idx_frag = format!("[{i}]");
        let full_key = format!("{prefix}{idx_frag}");
        let mut idx_path = path.to_vec();
        idx_path.push(idx_frag);

        match elem {
            Value::Object(map) => flatten_map(map, &full_key, result, &idx_path),
            Value::Array(inner) => flatten_slice(inner, &full_key, result, &idx_path),
            other => result.push(KeyValuePair {
                key: full_key,
                value: format_leaf(other),
                path: idx_path,
            }),
        }
    }
}

fn dedup_strings(ss: &[String]) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    ss.iter()
        .filter(|s| seen.insert(s.as_str()))
        .cloned()
        .collect()
}

// ---- Environment record JSON conversion ----

/// Merges `src` into `dst` following proto3 merge semantics: non-default
/// scalars overwrite, repeated fields append, map entries upsert, and
/// message fields merge recursively (replace for our simple cases).
fn merge_environment(dst: &mut EnvironmentRecord, src: &EnvironmentRecord) {
    fn ms(dst: &mut String, src: &str) {
        if !src.is_empty() {
            *dst = src.to_string();
        }
    }
    fn mu(dst: &mut u32, src: u32) {
        if src != 0 {
            *dst = src;
        }
    }

    ms(&mut dst.os, &src.os);
    ms(&mut dst.python, &src.python);
    if src.started_at.is_some() {
        dst.started_at = src.started_at;
    }
    ms(&mut dst.docker, &src.docker);
    dst.args.extend(src.args.iter().cloned());
    ms(&mut dst.program, &src.program);
    ms(&mut dst.code_path, &src.code_path);
    ms(&mut dst.code_path_local, &src.code_path_local);
    if src.git.is_some() {
        dst.git = src.git.clone();
    }
    ms(&mut dst.email, &src.email);
    ms(&mut dst.root, &src.root);
    ms(&mut dst.host, &src.host);
    ms(&mut dst.username, &src.username);
    ms(&mut dst.executable, &src.executable);
    ms(&mut dst.colab, &src.colab);
    mu(&mut dst.cpu_count, src.cpu_count);
    mu(&mut dst.cpu_count_logical, src.cpu_count_logical);
    ms(&mut dst.gpu_type, &src.gpu_type);
    mu(&mut dst.gpu_count, src.gpu_count);
    for (k, v) in &src.disk {
        match dst.disk.iter_mut().find(|(dk, _)| dk == k) {
            Some((_, dv)) => *dv = v.clone(),
            None => dst.disk.push((k.clone(), v.clone())),
        }
    }
    if src.memory_total.is_some() {
        dst.memory_total = src.memory_total;
    }
    if src.cpu.is_some() {
        dst.cpu = src.cpu;
    }
    if src.apple.is_some() {
        dst.apple = src.apple.clone();
    }
    dst.gpu_nvidia.extend(src.gpu_nvidia.iter().cloned());
    ms(&mut dst.cuda_version, &src.cuda_version);
    for (k, v) in &src.slurm {
        match dst.slurm.iter_mut().find(|(dk, _)| dk == k) {
            Some((_, dv)) => *dv = v.clone(),
            None => dst.slurm.push((k.clone(), v.clone())),
        }
    }
    if src.trainium.is_some() {
        dst.trainium = src.trainium.clone();
    }
    if src.tpu.is_some() {
        dst.tpu = src.tpu.clone();
    }
    ms(&mut dst.writer_id, &src.writer_id);
}

/// Converts the record to a JSON map using protojson conventions: field
/// names from the proto (`json_name` where declared, lowerCamelCase
/// otherwise), default values omitted, and 64-bit integers as strings.
pub fn environment_to_json(env: &EnvironmentRecord) -> Map<String, Value> {
    let mut m = Map::new();
    fn put_str(m: &mut Map<String, Value>, k: &str, v: &str) {
        if !v.is_empty() {
            m.insert(k.to_string(), Value::from(v));
        }
    }
    fn put_u32(m: &mut Map<String, Value>, k: &str, v: u32) {
        if v != 0 {
            m.insert(k.to_string(), Value::from(v));
        }
    }
    fn put_u64(m: &mut Map<String, Value>, k: &str, v: u64) {
        if v != 0 {
            m.insert(k.to_string(), Value::from(v.to_string()));
        }
    }

    put_str(&mut m, "os", &env.os);
    put_str(&mut m, "python", &env.python);
    if let Some(ts) = &env.started_at
        && (ts.seconds != 0 || ts.nanos != 0)
    {
        m.insert(
            "startedAt".to_string(),
            Value::from(format_rfc3339(ts.seconds, ts.nanos)),
        );
    }
    put_str(&mut m, "docker", &env.docker);
    if !env.args.is_empty() {
        m.insert(
            "args".to_string(),
            Value::Array(env.args.iter().map(|a| Value::from(a.as_str())).collect()),
        );
    }
    put_str(&mut m, "program", &env.program);
    put_str(&mut m, "codePath", &env.code_path);
    put_str(&mut m, "codePathLocal", &env.code_path_local);
    if let Some(git) = &env.git {
        let mut g = Map::new();
        put_str(&mut g, "remote", &git.remote_url);
        put_str(&mut g, "commit", &git.commit);
        m.insert("git".to_string(), Value::Object(g));
    }
    put_str(&mut m, "email", &env.email);
    put_str(&mut m, "root", &env.root);
    put_str(&mut m, "host", &env.host);
    put_str(&mut m, "username", &env.username);
    put_str(&mut m, "executable", &env.executable);
    put_str(&mut m, "colab", &env.colab);
    put_u32(&mut m, "cpu_count", env.cpu_count);
    put_u32(&mut m, "cpu_count_logical", env.cpu_count_logical);
    put_str(&mut m, "gpu", &env.gpu_type);
    put_u32(&mut m, "gpu_count", env.gpu_count);
    if !env.disk.is_empty() {
        let mut disk = Map::new();
        for (path, info) in &env.disk {
            let mut d = Map::new();
            put_u64(&mut d, "total", info.total);
            put_u64(&mut d, "used", info.used);
            disk.insert(path.clone(), Value::Object(d));
        }
        m.insert("disk".to_string(), Value::Object(disk));
    }
    if let Some(total) = env.memory_total {
        let mut mem = Map::new();
        put_u64(&mut mem, "total", total);
        m.insert("memory".to_string(), Value::Object(mem));
    }
    if let Some((count, count_logical)) = env.cpu {
        let mut c = Map::new();
        put_u32(&mut c, "count", count);
        put_u32(&mut c, "countLogical", count_logical);
        m.insert("cpu".to_string(), Value::Object(c));
    }
    if let Some(apple) = &env.apple {
        let mut a = Map::new();
        put_str(&mut a, "name", &apple.name);
        put_u32(&mut a, "ecpuCores", apple.ecpu_cores);
        put_u32(&mut a, "pcpuCores", apple.pcpu_cores);
        put_u32(&mut a, "gpuCores", apple.gpu_cores);
        put_u32(&mut a, "memoryGb", apple.memory_gb);
        put_u64(&mut a, "swapTotalBytes", apple.swap_total_bytes);
        put_u64(&mut a, "ramTotalBytes", apple.ram_total_bytes);
        put_str(&mut a, "macModel", &apple.mac_model);
        m.insert("apple".to_string(), Value::Object(a));
    }
    if !env.gpu_nvidia.is_empty() {
        let gpus: Vec<Value> = env
            .gpu_nvidia
            .iter()
            .map(|g| {
                let mut gm = Map::new();
                put_str(&mut gm, "name", &g.name);
                put_u64(&mut gm, "memoryTotal", g.memory_total);
                put_u32(&mut gm, "cudaCores", g.cuda_cores);
                put_str(&mut gm, "architecture", &g.architecture);
                put_str(&mut gm, "uuid", &g.uuid);
                Value::Object(gm)
            })
            .collect();
        m.insert("gpu_nvidia".to_string(), Value::Array(gpus));
    }
    put_str(&mut m, "cudaVersion", &env.cuda_version);
    if !env.slurm.is_empty() {
        let mut slurm = Map::new();
        for (k, v) in &env.slurm {
            slurm.insert(k.clone(), Value::from(v.as_str()));
        }
        m.insert("slurm".to_string(), Value::Object(slurm));
    }
    if let Some(t) = &env.trainium {
        let mut tm = Map::new();
        put_str(&mut tm, "name", &t.name);
        put_str(&mut tm, "vendor", &t.vendor);
        put_u32(&mut tm, "neuronDeviceCount", t.neuron_device_count);
        put_u32(
            &mut tm,
            "neuroncorePerDeviceCount",
            t.neuroncore_per_device_count,
        );
        m.insert("trainium".to_string(), Value::Object(tm));
    }
    if let Some(t) = &env.tpu {
        let mut tm = Map::new();
        put_str(&mut tm, "name", &t.name);
        put_u32(&mut tm, "hbmGib", t.hbm_gib);
        put_u32(&mut tm, "devicesPerChip", t.devices_per_chip);
        put_u32(&mut tm, "count", t.count);
        m.insert("tpu".to_string(), Value::Object(tm));
    }
    put_str(&mut m, "writerId", &env.writer_id);

    m
}

/// Formats a Unix timestamp as an RFC 3339 UTC string the way protojson
/// renders `google.protobuf.Timestamp`.
fn format_rfc3339(seconds: i64, nanos: i32) -> String {
    use chrono::TimeZone;
    let Some(dt) = chrono::Utc
        .timestamp_opt(seconds, nanos.max(0) as u32)
        .single()
    else {
        return String::new();
    };
    if nanos == 0 {
        dt.format("%Y-%m-%dT%H:%M:%SZ").to_string()
    } else {
        // protojson trims trailing zeros to 3/6/9 digits.
        let frac = format!("{:09}", nanos);
        let frac = if frac.ends_with("000000") {
            &frac[..3]
        } else if frac.ends_with("000") {
            &frac[..6]
        } else {
            &frac[..]
        };
        format!("{}.{}Z", dt.format("%Y-%m-%dT%H:%M:%S"), frac)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::proto::KeyedJsonItem;

    fn item(key: &str, value_json: &str) -> KeyedJsonItem {
        KeyedJsonItem {
            key: key.to_string(),
            nested_key: Vec::new(),
            value_json: value_json.to_string(),
        }
    }

    #[test]
    fn config_flattening() {
        let mut ro = RunOverview::new();
        let msg = RunMsg {
            id: "r1".into(),
            config: Some(ConfigRecord {
                update: vec![
                    item("lr", "0.001"),
                    item("opt", r#"{"name": "adam", "betas": [0.9, 0.999]}"#),
                ],
                remove: vec![],
            }),
            ..Default::default()
        };
        ro.process_run_msg(&msg);

        let items = ro.config_items();
        let keys: Vec<&str> = items.iter().map(|i| i.key.as_str()).collect();
        assert_eq!(keys, vec!["lr", "opt.betas[0]", "opt.betas[1]", "opt.name"]);
        assert_eq!(items[0].value, "0.001");
        assert_eq!(items[3].value, "adam");
    }

    #[test]
    fn summary_set_and_remove() {
        let mut ro = RunOverview::new();
        ro.process_summary(&[SummaryRecord {
            update: vec![item("loss", "0.5"), item("acc", "0.9")],
            remove: vec![],
        }]);
        ro.process_summary(&[SummaryRecord {
            update: vec![],
            remove: vec![item("acc", "")],
        }]);
        let items = ro.summary_items();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].key, "loss");
    }

    #[test]
    fn go_float_formatting() {
        assert_eq!(format_float_go(0.001), "0.001");
        assert_eq!(format_float_go(16000000.0), "1.6e+07");
        assert_eq!(format_float_go(100.0), "100");
        assert_eq!(format_float_go(123456.0), "123456");
        assert_eq!(format_float_go(1234567.0), "1.234567e+06");
        assert_eq!(format_float_go(0.00001), "1e-05");
        assert_eq!(format_float_go(-2.5), "-2.5");
    }

    #[test]
    fn environment_flattening() {
        let mut ro = RunOverview::new();
        let env = EnvironmentRecord {
            os: "macOS".to_string(),
            cpu_count: 8,
            writer_id: "w1".to_string(),
            ..Default::default()
        };
        ro.process_system_info(&env);
        let items = ro.environment_items();
        let keys: Vec<&str> = items.iter().map(|i| i.key.as_str()).collect();
        assert_eq!(keys, vec!["cpu_count", "os", "writerId"]);
        assert_eq!(items[0].value, "8");
    }
}
