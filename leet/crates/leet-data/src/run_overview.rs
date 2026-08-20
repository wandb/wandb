//! Port of `core/internal/leet/runoverview.go` (run metadata data-model).
//!
//! Support packages (used subsets) live in [`crate::run_config`],
//! [`crate::run_summary`] and [`crate::run_environment`].

use std::collections::HashSet;

use leet_proto::wandb_internal::{ConfigRecord, EnvironmentRecord, SummaryRecord};
use serde_json::{Map, Value};

use crate::run_config::RunConfig;
use crate::run_environment::RunEnvironment;
use crate::run_summary::{self, RunSummary};

pub const RUN_OVERVIEW_HEADER: &str = "Run Overview";

/// RunState indicates the current state of the run.
// PARITY: Go declares `type RunState int32` with iota values 0..4.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum RunState {
    #[default]
    Unknown,
    Running,
    Finished,
    Failed,
    Crashed,
}

/// RunMsg contains data from the wandb run record.
// PARITY: declared in messages.go in Go (a tea.Msg); it lives here because
// `RunOverview::process_run_msg` consumes it and `leet-tui` depends on
// `leet-data`, not vice versa. The Event enum re-exports it.
#[derive(Debug, Clone, Default)]
pub struct RunMsg {
    pub run_path: String,
    pub id: String,
    pub project: String,
    pub display_name: String,
    pub notes: String,
    pub tags: Vec<String>,
    pub config: Option<ConfigRecord>,
}

/// KeyValuePair represents a single key-value item to display.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct KeyValuePair {
    pub key: String,
    pub value: String,

    /// The full path for nested items.
    pub path: Vec<String>,
}

/// RunOverview processes and stores run metadata.
#[derive(Debug)]
pub struct RunOverview {
    run_id: String,
    display_name: String,
    project: String,
    notes: String,
    tags: Vec<String>,
    run_config: RunConfig,
    run_environment: Option<RunEnvironment>,
    run_summary: RunSummary,
    run_state: RunState,
}

impl Default for RunOverview {
    fn default() -> Self {
        Self::new()
    }
}

impl RunOverview {
    pub fn new() -> Self {
        RunOverview {
            run_id: String::new(),
            display_name: String::new(),
            project: String::new(),
            notes: String::new(),
            tags: Vec::new(),
            run_config: RunConfig::new(),
            run_environment: None,
            run_summary: RunSummary::new(),
            run_state: RunState::Unknown,
        }
    }

    /// StateString returns a string representation from the data model.
    pub fn state_string(&self) -> &'static str {
        match self.state() {
            RunState::Running => "Running",
            RunState::Finished => "Finished",
            RunState::Failed => "Failed",
            RunState::Crashed => "Error",
            RunState::Unknown => "Unknown",
        }
    }

    /// ProcessRunMsg processes a run message and updates internal state.
    pub fn process_run_msg(&mut self, msg: RunMsg) {
        self.run_id = msg.id;
        self.display_name = msg.display_name;
        self.project = msg.project;
        self.notes = msg.notes;
        self.tags = dedup_strings(msg.tags);
        self.run_state = RunState::Running;

        if let Some(config) = &msg.config {
            self.run_config.apply_change_record(config, |_err| {});
        }
    }

    /// ProcessSystemInfoMsg processes system/environment information.
    pub fn process_system_info_msg(&mut self, record: Option<&EnvironmentRecord>) {
        if self.run_environment.is_none()
            && let Some(record) = record
        {
            self.run_environment = Some(RunEnvironment::new(record.writer_id.clone()));
        }
        if let Some(run_environment) = &mut self.run_environment {
            // PARITY: Go passes a possibly-nil record to ProcessRecord,
            // where proto.Merge with a nil source is a no-op.
            if let Some(record) = record {
                run_environment.process_record(record);
            }
        }
    }

    /// ProcessSummaryMsg processes summary data.
    pub fn process_summary_msg(&mut self, summary: &[SummaryRecord]) {
        for s in summary {
            let _ = run_summary::from_proto(s).apply(&mut self.run_summary);
        }
    }

    /// SetRunState sets the run state.
    pub fn set_run_state(&mut self, state: RunState) {
        self.run_state = state;
    }

    // Data accessors

    /// ID returns the run ID.
    pub fn id(&self) -> &str {
        &self.run_id
    }

    /// DisplayName returns the run display name.
    pub fn display_name(&self) -> &str {
        &self.display_name
    }

    /// Project returns the project name.
    pub fn project(&self) -> &str {
        &self.project
    }

    /// Notes returns the run notes.
    pub fn notes(&self) -> &str {
        &self.notes
    }

    /// Tags returns a defensive copy of the run tags.
    pub fn tags(&self) -> Vec<String> {
        self.tags.clone()
    }

    /// State returns the run state.
    pub fn state(&self) -> RunState {
        self.run_state
    }

    /// EnvironmentItems returns environment data as key-value pairs.
    pub fn environment_items(&self) -> Vec<KeyValuePair> {
        let Some(run_environment) = &self.run_environment else {
            return Vec::new();
        };

        let env_data = run_environment.to_run_config_data();
        process_environment_data(env_data.as_ref())
    }

    /// ConfigItems returns config data as key-value pairs.
    // PARITY: Go checks `runConfig == nil`; it is always initialized by
    // NewRunOverview, and here it is not optional.
    pub fn config_items(&self) -> Vec<KeyValuePair> {
        let mut items = Vec::new();
        flatten_map(&self.run_config.clone_tree(), "", &mut items, &[]);
        items
    }

    /// SummaryItems returns summary data as key-value pairs.
    // PARITY: Go checks `runSummary == nil`; same as config_items above.
    pub fn summary_items(&self) -> Vec<KeyValuePair> {
        let mut items = Vec::new();
        flatten_map(&self.run_summary.to_nested_maps(), "", &mut items, &[]);
        items
    }
}

/// flattenMap converts nested maps to flat key-value pairs.
///
/// - Map keys are sorted (deterministic).
/// - Slices are flattened using bracketed indices (e.g., a\[0\].b).
fn flatten_map(
    data: &Map<String, Value>,
    prefix: &str,
    result: &mut Vec<KeyValuePair>,
    path: &[String],
) {
    // PARITY: Go's `data == nil` guard has no Rust equivalent (the nil case
    // is an Option at the only call site that can produce one).
    // PARITY: serde_json's Map is BTreeMap-backed (already sorted); the
    // explicit collect-and-sort is kept from Go and guards against the
    // preserve_order feature being enabled by another dependency.
    let mut keys: Vec<&String> = data.keys().collect();
    keys.sort();

    for k in keys {
        let v = &data[k.as_str()];

        let full_key = if prefix.is_empty() {
            k.clone()
        } else {
            format!("{prefix}.{k}")
        };
        let mut current_path = path.to_vec();
        current_path.push(k.clone());

        match v {
            Value::Object(val) => flatten_map(val, &full_key, result, &current_path),
            Value::Array(val) => flatten_slice(val, &full_key, result, &current_path),
            _ => result.push(KeyValuePair {
                key: full_key,
                value: go_sprint(v),
                path: current_path,
            }),
        }
    }
}

/// flattenSlice handles arrays by emitting `prefix[i]` and recursing as
/// needed.
fn flatten_slice(list: &[Value], prefix: &str, result: &mut Vec<KeyValuePair>, path: &[String]) {
    for (i, elem) in list.iter().enumerate() {
        let idx_frag = format!("[{i}]");
        let full_key = format!("{prefix}{idx_frag}");
        let mut idx_path = path.to_vec();
        idx_path.push(idx_frag);

        match elem {
            Value::Object(e) => flatten_map(e, &full_key, result, &idx_path),
            Value::Array(e) => flatten_slice(e, &full_key, result, &idx_path),
            _ => result.push(KeyValuePair {
                key: full_key,
                value: go_sprint(elem),
                path: idx_path,
            }),
        }
    }
}

/// processEnvironmentData handles special processing for environment data.
///
/// The run's transaction log should only contain info about a single writer.
fn process_environment_data(data: Option<&Map<String, Value>>) -> Vec<KeyValuePair> {
    let Some(data) = data else {
        return Vec::new();
    };

    let mut keys: Vec<&String> = data.keys().collect();

    if keys.is_empty() {
        return Vec::new();
    }

    keys.sort();
    let first_key = keys[0];

    let Some(first_value) = data.get(first_key.as_str()) else {
        // PARITY: unreachable double-check kept from Go.
        return Vec::new();
    };

    if let Value::Object(value_map) = first_value {
        let mut result = Vec::new();
        flatten_map(value_map, "", &mut result, &[]);
        return result;
    }

    vec![KeyValuePair {
        key: first_key.clone(),
        value: go_sprint(first_value),
        path: vec![first_key.clone()],
    }]
}

fn dedup_strings(ss: Vec<String>) -> Vec<String> {
    let mut seen: HashSet<&String> = HashSet::with_capacity(ss.len());
    let mut out: Vec<String> = Vec::with_capacity(ss.len());
    for s in &ss {
        if seen.insert(s) {
            out.push(s.clone());
        }
    }
    out
}

/// Go's `fmt.Sprint` for the `any` values simplejsonext and encoding/json
/// produce (int64, float64, string, bool, nil, []any, map[string]any).
///
/// The container arms are unreachable from `flatten_map`/`flatten_slice`
/// (which recurse instead) but are kept total for
/// `process_environment_data`'s non-map branch.
fn go_sprint(v: &Value) -> String {
    match v {
        // PARITY: fmt.Sprint of a nil interface value.
        Value::Null => "<nil>".to_string(),
        Value::Bool(b) => b.to_string(),
        Value::String(s) => s.clone(),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                // PARITY: unreachable via the simplejsonext port (integers
                // beyond i64 are promoted to floats) but Value can hold it.
                u.to_string()
            } else {
                go_sprint_float(n.as_f64().unwrap_or(f64::NAN))
            }
        }
        // PARITY: fmt prints slices as "[a b c]" and maps as
        // "map[k1:v1 k2:v2]" with sorted keys.
        Value::Array(l) => {
            let parts: Vec<String> = l.iter().map(go_sprint).collect();
            format!("[{}]", parts.join(" "))
        }
        Value::Object(m) => {
            let parts: Vec<String> = m
                .iter()
                .map(|(k, v)| format!("{k}:{}", go_sprint(v)))
                .collect();
            format!("map[{}]", parts.join(" "))
        }
    }
}

/// `strconv.FormatFloat(v, 'g', -1, 64)` — the shortest round-trip decimal
/// in Go's %v float form.
///
/// Not in `go_fmt` because that module's 'g' takes an explicit precision
/// (>= 1); the shortest form has its own exponent threshold.
fn go_sprint_float(v: f64) -> String {
    if v.is_nan() {
        return "NaN".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 {
            "+Inf".to_string()
        } else {
            "-Inf".to_string()
        };
    }

    // PARITY: Go's shortest-digit selection (strconv/ftoaryu.go) rounds
    // exact round-trip ties half-to-even, while Rust's `{:e}` rounds them
    // away from zero — e.g. f64::from_bits(0x4315CC95660CC0ED) is
    // "1.5339791363072592e+15" in Go but "1.5339791363072593e15" via
    // `{:e}`. The digits therefore come from serde_json's float writer,
    // which matches Go's selection (differentially verified against a
    // 756k-value Go fmt.Sprint corpus, zero mismatches); only Go's 'g'
    // shortest layout is applied below.
    let ser = serde_json::to_string(&v).expect("finite f64 serializes");
    let (neg, s) = match ser.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, ser.as_str()),
    };
    // Normalize "ddd.ddd" / "d[.ddd]e±dd" into significant digits plus the
    // decimal exponent of the leading digit.
    let (mantissa, exp10) = match s.split_once(['e', 'E']) {
        Some((m, e)) => (m, e.parse::<i32>().expect("valid exponent")),
        None => (s, 0),
    };
    let (int_part, frac_part) = match mantissa.split_once('.') {
        Some((i, f)) => (i, f),
        None => (mantissa, ""),
    };
    let all = format!("{int_part}{frac_part}");
    let no_lead = all.trim_start_matches('0');
    let exp = exp10 + int_part.len() as i32 - 1 - (all.len() - no_lead.len()) as i32;
    let digits = no_lead.trim_end_matches('0');

    if digits.is_empty() {
        // PARITY: strconv renders ±0 as "0"/"-0" (never in exponent form).
        return if neg {
            "-0".to_string()
        } else {
            "0".to_string()
        };
    }

    let mut out = String::new();
    if neg {
        out.push('-');
    }

    // PARITY: for the shortest precision, Go switches to scientific
    // notation when the decimal exponent is < -4 or >= 6
    // (strconv/ftoa.go formatDigits, shortest => eprec = 6).
    if !(-4..6).contains(&exp) {
        // Scientific: d[.ddd]e±dd (exponent sign always, min two digits).
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        if exp < 0 {
            out.push('-');
        } else {
            out.push('+');
        }
        let e = exp.unsigned_abs();
        if e < 10 {
            out.push('0');
        }
        out.push_str(&e.to_string());
    } else if exp >= 0 {
        // Fixed with the decimal point inside/after the digit string.
        let int_len = (exp + 1) as usize;
        if digits.len() <= int_len {
            out.push_str(digits);
            for _ in digits.len()..int_len {
                out.push('0');
            }
        } else {
            out.push_str(&digits[..int_len]);
            out.push('.');
            out.push_str(&digits[int_len..]);
        }
    } else {
        // 0.0…digits
        out.push_str("0.");
        for _ in 0..(-exp - 1) {
            out.push('0');
        }
        out.push_str(digits);
    }
    out
}

#[cfg(test)]
mod tests {
    use leet_proto::wandb_internal::ConfigItem;
    use pretty_assertions::assert_eq;

    use super::*;

    // Transliterated from core/internal/leet/runoverview_test.go.

    #[test]
    fn process_run_msg_stores_metadata_and_flattens_config_sorted() {
        let mut ro = RunOverview::new();

        // Intentionally provide keys out of order to verify flattening +
        // stable sort.
        ro.process_run_msg(RunMsg {
            id: "run-42".to_string(),
            display_name: "cool-run".to_string(),
            project: "proj".to_string(),
            notes: "Primary baseline".to_string(),
            tags: vec!["vision".to_string(), "baseline".to_string()],
            config: Some(ConfigRecord {
                update: vec![
                    ConfigItem {
                        nested_key: vec!["trainer".to_string(), "lr".to_string()],
                        value_json: "0.01".to_string(),
                        ..Default::default()
                    },
                    ConfigItem {
                        nested_key: vec!["alpha".to_string(), "a".to_string()],
                        value_json: "1".to_string(),
                        ..Default::default()
                    },
                    ConfigItem {
                        nested_key: vec!["trainer".to_string(), "epochs".to_string()],
                        value_json: "10".to_string(),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            }),
            ..Default::default()
        });

        assert_eq!(ro.id(), "run-42");
        assert_eq!(ro.display_name(), "cool-run");
        assert_eq!(ro.project(), "proj");
        assert_eq!(ro.notes(), "Primary baseline");
        assert_eq!(
            ro.tags(),
            vec!["vision".to_string(), "baseline".to_string()]
        );

        let items = ro.config_items();
        assert_eq!(items.len(), 3);

        assert_eq!(items[0].key, "alpha.a");
        assert_eq!(items[1].key, "trainer.epochs");
        assert_eq!(items[2].key, "trainer.lr");

        assert_eq!(items[0].path, vec!["alpha".to_string(), "a".to_string()]);
        assert_eq!(
            items[1].path,
            vec!["trainer".to_string(), "epochs".to_string()]
        );
        assert_eq!(items[2].path, vec!["trainer".to_string(), "lr".to_string()]);

        assert_eq!(items[0].value, "1");
        assert_eq!(items[1].value, "10");
        assert_eq!(items[2].value, "0.01");
    }

    #[test]
    fn process_system_info_msg_yields_environment_items() {
        let mut ro = RunOverview::new();
        // First message creates the environment model and processes data.
        ro.process_system_info_msg(Some(&EnvironmentRecord {
            writer_id: "writer-1".to_string(),
            os: "linux".to_string(),
            ..Default::default()
        }));

        let env = ro.environment_items();
        assert!(!env.is_empty(), "expected at least one environment item");

        let found = env
            .iter()
            .any(|kv| kv.value.to_lowercase().contains("linux"));
        assert!(found, "expected an environment item containing 'linux'");
    }

    #[test]
    fn environment_u32_fields_render_like_go_float64() {
        // PARITY: Go's ToRunConfigData re-parses protojson output with
        // encoding/json, so uint32 fields become float64 and fmt.Sprint
        // renders them with %g: cpu_count_logical=2000000 is "2e+06"
        // (expectation produced by Go's leet.RunOverview), not "2000000".
        let mut ro = RunOverview::new();
        ro.process_system_info_msg(Some(&EnvironmentRecord {
            writer_id: "w".to_string(),
            cpu_count: 8,
            cpu_count_logical: 2_000_000,
            ..Default::default()
        }));

        let env = ro.environment_items();
        let value_of = |key: &str| {
            env.iter()
                .find(|kv| kv.key == key)
                .map(|kv| kv.value.as_str())
        };
        assert_eq!(value_of("cpu_count"), Some("8"));
        assert_eq!(value_of("cpu_count_logical"), Some("2e+06"));
    }

    #[test]
    fn process_summary_msg_flattens_and_sorts() {
        let mut ro = RunOverview::new();

        let s = SummaryRecord {
            update: vec![
                leet_proto::wandb_internal::SummaryItem {
                    nested_key: vec!["val".to_string(), "acc".to_string()],
                    value_json: "0.88".to_string(),
                    ..Default::default()
                },
                leet_proto::wandb_internal::SummaryItem {
                    nested_key: vec!["acc".to_string()],
                    value_json: "0.9".to_string(),
                    ..Default::default()
                },
            ],
            ..Default::default()
        };
        ro.process_summary_msg(&[s]);

        let items = ro.summary_items();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].key, "acc"); // alphabetical before "val.acc"
        assert_eq!(items[1].key, "val.acc"); // flattened nested key
        assert_eq!(items[0].value, "0.9");
        assert_eq!(items[1].value, "0.88");
    }

    #[test]
    fn state_transitions() {
        let mut ro = RunOverview::new();
        assert_eq!(ro.state(), RunState::Unknown);
        ro.process_run_msg(RunMsg::default());
        assert_eq!(ro.state(), RunState::Running);

        ro.set_run_state(RunState::Finished);
        assert_eq!(ro.state(), RunState::Finished);
    }

    #[test]
    fn config_list_of_maps_flattens() {
        let mut ro = RunOverview::new();
        ro.process_run_msg(RunMsg {
            config: Some(ConfigRecord {
                update: vec![ConfigItem {
                    nested_key: vec!["a".to_string()],
                    value_json: r#"[{"b":1},{"c":2}]"#.to_string(),
                    ..Default::default()
                }],
                ..Default::default()
            }),
            ..Default::default()
        });

        let items = ro.config_items();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].key, "a[0].b");
        assert_eq!(items[0].value, "1");
        assert_eq!(
            items[0].path,
            vec!["a".to_string(), "[0]".to_string(), "b".to_string()]
        );

        assert_eq!(items[1].key, "a[1].c");
        assert_eq!(items[1].value, "2");
        assert_eq!(
            items[1].path,
            vec!["a".to_string(), "[1]".to_string(), "c".to_string()]
        );
    }

    // Anchors for the fmt.Sprint float port (Go: strconv 'g' with shortest
    // precision; expectations produced by Go's fmt).

    #[test]
    fn go_sprint_float_matches_go() {
        for (v, want) in [
            (0.0, "0"),
            (-0.0, "-0"),
            (10.0, "10"),
            (0.9, "0.9"),
            (0.01, "0.01"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1e-7, "1e-07"),
            (100000.0, "100000"),
            (999999.5, "999999.5"),
            (1e6, "1e+06"),
            (1234567.0, "1.234567e+06"),
            (123456789.0, "1.23456789e+08"),
            (1.5e300, "1.5e+300"),
            (0.1 + 0.2, "0.30000000000000004"),
            (-1234.5, "-1234.5"),
            // Exact round-trip ties: Go's shortest selection rounds the
            // last digit half-to-even; Rust `{:e}` would round away from
            // zero (…93 / …23 / …93).
            (f64::from_bits(0x4315CC95660CC0ED), "1.5339791363072592e+15"),
            (f64::from_bits(0x43129879088FF039), "1.3085487957268622e+15"),
            (
                f64::from_bits(0xC316FED6EBAF054D),
                "-1.6181621295516992e+15",
            ),
        ] {
            assert_eq!(go_sprint_float(v), want, "v={v}");
        }
        assert_eq!(go_sprint_float(f64::NAN), "NaN");
        assert_eq!(go_sprint_float(f64::INFINITY), "+Inf");
        assert_eq!(go_sprint_float(f64::NEG_INFINITY), "-Inf");
    }
}
