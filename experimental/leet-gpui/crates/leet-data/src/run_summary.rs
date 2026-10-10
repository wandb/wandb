//! Port of `core/internal/runsummary` — the subset used by
//! `core/internal/leet/runoverview.go` (`New`, `Set`, `Remove`, `FromProto`,
//! `Updates.Apply`, `ToNestedMaps`).
//!
//! `UpdateSummaries` / `ConfigureMetric` / `ToRecords` / `Serialize` /
//! `Updates.Merge` / `Updates.IsEmpty` are not reachable from runoverview.go
//! and are not ported. Because `ConfigureMetric` is out, `track` stays
//! `UNSET` and `no_summary` stays false; the fields and the full
//! `to_marshallable_value` are ported anyway so the shapes stay 1:1 with Go.
//!
//! Shares the pathtree and simplejsonext used-subset ports hosted in
//! [`crate::run_config`].

use leet_proto::wandb_internal::{SummaryItem, SummaryRecord};
use serde_json::{Map, Value};

use crate::run_config::{PathTree, TreePath, json_float, unmarshal_string};

/// SummaryTypeFlags selects which summary values to emit for a metric.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SummaryTypeFlags(pub u64);

pub const UNSET: SummaryTypeFlags = SummaryTypeFlags(0);
pub const LATEST: SummaryTypeFlags = SummaryTypeFlags(1);
pub const MIN: SummaryTypeFlags = SummaryTypeFlags(1 << 1);
pub const MAX: SummaryTypeFlags = SummaryTypeFlags(1 << 2);
pub const MEAN: SummaryTypeFlags = SummaryTypeFlags(1 << 3);
pub const FIRST: SummaryTypeFlags = SummaryTypeFlags(1 << 4);

impl SummaryTypeFlags {
    pub fn is_empty(self) -> bool {
        self.0 == 0
    }

    pub fn has_any(self, flag: SummaryTypeFlags) -> bool {
        (self.0 & flag.0) > 0
    }
}

/// metricSummary is the summary value of a single metric.
///
/// The zero value is an empty summary.
// PARITY: Go `any` leaves are `serde_json::Value` here; a Go nil interface
// and a JSON null are both `Value::Null` (simplejsonext decodes JSON null to
// nil, so Go cannot distinguish them either).
#[derive(Debug, Clone, Default, PartialEq)]
struct MetricSummary {
    latest: Value,
    first: Value,
    min: f64,
    max: f64,
    total: f64,
    count: i64,

    /// The list of summary values to emit.
    ///
    /// If empty, the latest value is used. Otherwise, the metric's summary
    /// is a dictionary containing the requested values.
    track: SummaryTypeFlags,

    /// Disables any summary output for the metric at all.
    no_summary: bool,

    /// Whether any summary data has been accumulated.
    has_data: bool,
}

impl MetricSummary {
    fn clear(&mut self) {
        self.latest = Value::Null;
        self.has_data = false;
    }

    /// SetExplicit sets an explicit summary value for the metric.
    ///
    /// This resets any configured summary types.
    fn set_explicit(&mut self, value: Value) {
        self.latest = value;
        self.track = UNSET;
        self.has_data = true;
    }

    /// ToMarshallableValue returns the metric's summary as
    /// a JSON-marshallable type.
    ///
    /// Returns `None` if there is no summary.
    fn to_marshallable_value(&self) -> Option<Value> {
        if self.no_summary || !self.has_data {
            return None;
        }

        if self.track.is_empty() {
            // PARITY: Go returns ms.latest as `any`; when that is nil the
            // callers treat it as "no summary", so a JSON null maps to None.
            return match &self.latest {
                Value::Null => None,
                v => Some(v.clone()),
            };
        }

        let mut summary = Map::new();
        if self.track.has_any(LATEST) {
            summary.insert("last".to_string(), self.latest.clone());
        }
        if self.track.has_any(FIRST) {
            summary.insert("first".to_string(), self.first.clone());
        }
        if self.track.has_any(MAX) {
            summary.insert("max".to_string(), json_float(self.max));
        }
        if self.track.has_any(MIN) {
            summary.insert("min".to_string(), json_float(self.min));
        }
        if self.track.has_any(MEAN) {
            summary.insert(
                "mean".to_string(),
                json_float(self.total / self.count as f64),
            );
        }

        Some(Value::Object(summary))
    }
}

/// RunSummary tracks summary statistics for all metrics in a run.
#[derive(Debug, Default)]
pub struct RunSummary {
    /// Maps metrics to MetricSummary objects.
    summaries: PathTree<MetricSummary>,
}

impl RunSummary {
    pub fn new() -> Self {
        RunSummary {
            summaries: PathTree::new(),
        }
    }

    /// Set sets the explicit summary value for a metric.
    pub fn set(&mut self, path: &TreePath, value: Value) {
        self.get_or_make_summary(path).set_explicit(value);
    }

    /// Remove deletes the summary for a metric.
    // PARITY: Go clears the summary through the *metricSummary pointer but
    // leaves the tree node in place.
    pub fn remove(&mut self, path: &TreePath) {
        let Some(summary) = self.summaries.get_leaf_mut(path) else {
            return;
        };
        summary.clear();
    }

    fn to_summary_tree(&self) -> PathTree<Value> {
        let mut json_tree = PathTree::new();

        self.summaries.for_each_leaf(|path, summary| {
            if let Some(json_summary) = summary.to_marshallable_value() {
                json_tree.set(path.clone(), json_summary);
            }
            true
        });

        json_tree
    }

    /// ToNestedMaps returns a nested-map representation of the summary.
    ///
    /// All values are JSON-marshallable types.
    pub fn to_nested_maps(&self) -> Map<String, Value> {
        self.to_summary_tree().clone_tree()
    }

    fn get_or_make_summary(&mut self, path: &TreePath) -> &mut MetricSummary {
        self.summaries
            .get_or_make_leaf(path, MetricSummary::default)
    }
}

/// Error from [`Updates::apply`].
// PARITY: Go wraps errors.Join(errs...), whose message is the individual
// messages joined by newlines.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("runsummary: failed to update some keys: {0}")]
pub struct ApplyError(String);

/// Updates is a collection of updates to a run's summary.
// PARITY: Go documents "A nil value acts like no updates"; a nil *Updates
// receiver is unrepresentable in Rust — callers always hold a value
// (runoverview.go only ever calls FromProto(...).Apply(...)).
#[derive(Debug, Default)]
pub struct Updates {
    /// Values to add to or change in the summary.
    ///
    /// Leaves in the tree are JSON-encoded values (supporting +-Infinity
    /// and NaN).
    update: PathTree<String>,

    /// Paths to remove from the summary.
    ///
    /// None of the paths appear in `update`.
    remove: PathTree<()>,
}

/// NoUpdates returns a mutable Updates instance that makes no changes.
pub fn no_updates() -> Updates {
    Updates {
        update: PathTree::new(),
        remove: PathTree::new(),
    }
}

/// FromProto makes Updates from a SummaryRecord.
pub fn from_proto(record: &SummaryRecord) -> Updates {
    let mut u = no_updates();

    // Perf: single-label paths (the overwhelmingly common case) land at the
    // tree root; pre-size it to avoid incremental rehashing.
    u.update.reserve_root(record.update.len());
    for item in &record.update {
        let path = key_path(item);
        u.update.set(path, item.value_json.clone());
    }

    for item in &record.remove {
        let path = key_path(item);
        // PARITY: Go sets into `remove` and then removes from `update`; the
        // two trees are independent, so the swapped order is equivalent and
        // lets `path` move into the final set.
        u.update.remove(&path);
        u.remove.set(path, ());
    }

    u
}

impl Updates {
    /// Apply modifies the summary with these updates.
    ///
    /// A partial success is possible if some values' JSON strings cannot be
    /// unmarshaled.
    pub fn apply(&self, rs: &mut RunSummary) -> Result<(), ApplyError> {
        let mut errs: Vec<String> = Vec::new();

        // PARITY: Go iterates leaves in nondeterministic order; leaf paths
        // are disjoint so the result is identical (here: sorted order).
        self.update.for_each_leaf(|path, value_json| {
            match unmarshal_string(value_json) {
                Ok(value) => rs.set(path, value),
                Err(err) => {
                    errs.push(format!("error in path {}: {}", to_dotted_path(path), err));
                }
            }
            true
        });

        self.remove.for_each_leaf(|path, _| {
            rs.remove(path);
            true
        });

        if !errs.is_empty() {
            return Err(ApplyError(errs.join("\n")));
        }

        Ok(())
    }
}

/// toDottedPath escapes dots in the path components and concatenates them
/// using dots.
fn to_dotted_path(path: &TreePath) -> String {
    let escaped_labels: Vec<String> = path
        .labels()
        .iter()
        .map(|label| label.replace('.', "\\."))
        .collect();

    escaped_labels.join(".")
}

/// keyPath returns the key on the summary item as a path.
fn key_path(item: &SummaryItem) -> TreePath {
    if !item.nested_key.is_empty() {
        return TreePath::from_labels(item.nested_key.clone());
    }
    TreePath::from_labels(vec![item.key.clone()])
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;
    use serde_json::json;

    use super::*;

    fn json_map(v: Value) -> Map<String, Value> {
        match v {
            Value::Object(m) => m,
            _ => panic!("expected a JSON object"),
        }
    }

    fn path_of(first: &str, rest: &[&str]) -> TreePath {
        TreePath::path_of(first, rest)
    }

    // Transliterated from core/internal/runsummary/updates_test.go.
    // TestUpdates_Apply_NilMakesNoChanges exercises Go's nil *Updates
    // receiver (unrepresentable here); TestUpdates_Merge,
    // TestUpdates_Merge_NilMakesNoChanges and TestUpdates_IsEmpty cover
    // Merge/IsEmpty, which are outside the ported subset.

    #[test]
    fn updates_apply_inserts_removes_and_collects_errors() {
        let mut rs = RunSummary::new();
        rs.set(&path_of("x", &[]), json!(1));
        rs.set(&path_of("y", &[]), json!(2));

        let err = from_proto(&SummaryRecord {
            update: vec![
                SummaryItem {
                    key: "x".to_string(),
                    value_json: "3.5".to_string(),
                    ..Default::default()
                },
                SummaryItem {
                    key: "z".to_string(),
                    value_json: r#""this is z""#.to_string(),
                    ..Default::default()
                },
                SummaryItem {
                    key: "oops".to_string(),
                    value_json: "<not valid JSON>".to_string(),
                    ..Default::default()
                },
            ],
            remove: vec![SummaryItem {
                key: "y".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        })
        .apply(&mut rs);

        assert_eq!(
            rs.to_nested_maps(),
            json_map(json!({
                "x": 3.5,
                "z": "this is z",
            })),
        );
        let err = err.expect_err("expected an apply error").to_string();
        assert!(err.contains("failed to update some keys"), "err: {err}");
        assert!(err.contains("oops"), "err: {err}");
    }

    #[test]
    fn updates_from_proto() {
        let mut rs = RunSummary::new();

        let result = from_proto(&SummaryRecord {
            update: vec![
                SummaryItem {
                    key: "invalid-but-removed".to_string(),
                    value_json: "<not valid JSON>".to_string(),
                    ..Default::default()
                },
                SummaryItem {
                    nested_key: vec!["good".to_string(), "key".to_string()],
                    value_json: "123".to_string(),
                    ..Default::default()
                },
            ],
            remove: vec![SummaryItem {
                key: "invalid-but-removed".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        })
        .apply(&mut rs);

        assert!(result.is_ok());
        assert_eq!(
            rs.to_nested_maps(),
            json_map(json!({
                "good": {
                    "key": 123,
                },
            })),
        );
    }

    // Transliterated from core/internal/runsummary/runsummary_test.go for
    // the ported subset (Set/Remove/ToNestedMaps). The Go tests assert via
    // Serialize (not ported); the equivalent nested-map form is asserted
    // instead. TestSummaryTypes, TestNoSummary, TestToRecords and
    // TestSerialize need ConfigureMetric/UpdateSummaries/ToRecords/Serialize
    // and are not ported.

    #[test]
    fn explicit_summary() {
        let mut rs = RunSummary::new();

        rs.set(&path_of("x", &[]), json!(123));
        rs.set(&path_of("y", &[]), json!(10.5));
        rs.set(&path_of("z", &[]), json!("abc"));

        assert_eq!(
            rs.to_nested_maps(),
            json_map(json!({
                "x": 123,
                "y": 10.5,
                "z": "abc",
            })),
        );
    }

    #[test]
    fn nested_key() {
        // PARITY: the Go test's UpdateSummaries half is outside the ported
        // subset; the explicit-Set half is kept.
        let mut rs = RunSummary::new();

        rs.set(&path_of("a", &["b", "c"]), json!({"value": 1}));

        assert_eq!(
            rs.to_nested_maps(),
            json_map(json!({
                "a": {"b": {"c": {"value": 1}}},
            })),
        );
    }

    #[test]
    fn remove() {
        let mut rs = RunSummary::new();

        rs.set(&path_of("x", &["y"]), json!(1));
        rs.set(&path_of("z", &["w"]), json!(2));
        rs.remove(&path_of("x", &["y"]));

        assert_eq!(rs.to_nested_maps(), json_map(json!({"z": {"w": 2}})));
    }
}
