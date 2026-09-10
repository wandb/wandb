//! The workspace runs-sidebar filter language.
//!
//! Bare terms search the default text fields (run key, name, id, project,
//! notes, and tags). Whitespace and AND join clauses, OR or `|` starts a new
//! group, NOT negates the next clause, and field operators support pattern
//! matching (`:`), exact matching (`=`, `!=`), numeric comparisons, and
//! existence checks (`has:field`).

use std::collections::BTreeMap;

use serde_json::Value;

use crate::filter::{FilterMatchMode, Matcher, compile_text_matcher};
use crate::msg::RunMsg;
use crate::store::proto::ConfigRecord;

/// Precomputed searchable metadata for one run in the workspace runs sidebar.
#[derive(Debug, Clone, Default)]
pub struct WorkspaceRunFilterData {
    pub run_key: String,
    pub display_name: String,
    pub id: String,
    pub project: String,
    pub notes: String,
    pub tags: Vec<String>,

    /// Flattened config values keyed by canonicalized path.
    pub config_by_path: BTreeMap<String, String>,
}

impl WorkspaceRunFilterData {
    pub fn from_key(run_key: &str) -> Self {
        Self {
            run_key: run_key.to_string(),
            ..Default::default()
        }
    }

    /// Converts a RunMsg into the indexed metadata used by the runs filter.
    pub fn from_run_msg(run_key: &str, msg: &RunMsg) -> Self {
        Self {
            run_key: run_key.to_string(),
            display_name: msg.display_name.clone(),
            id: msg.id.clone(),
            project: msg.project.clone(),
            notes: msg.notes.trim().to_string(),
            tags: normalize_tags(&msg.tags),
            config_by_path: flatten_config(msg.config.as_ref()),
        }
    }

    /// Merges newly indexed data over `existing`, keeping previously indexed
    /// values for fields the new record leaves empty. Run preload and
    /// streaming can deliver partial records.
    pub fn merge_over(mut self, existing: &WorkspaceRunFilterData) -> Self {
        if self.display_name.is_empty() {
            self.display_name = existing.display_name.clone();
        }
        if self.id.is_empty() {
            self.id = existing.id.clone();
        }
        if self.project.is_empty() {
            self.project = existing.project.clone();
        }
        if self.notes.is_empty() {
            self.notes = existing.notes.clone();
        }
        if self.tags.is_empty() && !existing.tags.is_empty() {
            self.tags = existing.tags.clone();
        }
        if self.config_by_path.is_empty() && !existing.config_by_path.is_empty() {
            self.config_by_path = existing.config_by_path.clone();
        }
        self
    }
}

fn normalize_tags(tags: &[String]) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    tags.iter()
        .map(|t| t.trim())
        .filter(|t| !t.is_empty() && seen.insert(t.to_string()))
        .map(str::to_string)
        .collect()
}

/// Flattens a ConfigRecord into canonicalized path/value pairs.
fn flatten_config(cfg: Option<&ConfigRecord>) -> BTreeMap<String, String> {
    let mut flat = BTreeMap::new();
    let Some(cfg) = cfg else { return flat };

    for item in &cfg.update {
        let path = if item.nested_key.is_empty() {
            item.key.clone()
        } else {
            item.nested_key.join(".")
        };
        let path = path.trim().to_string();
        if path.is_empty() {
            continue;
        }

        let raw = item.value_json.trim();
        if raw.is_empty() {
            flat.insert(canonical_path(&path), String::new());
            continue;
        }

        match serde_json::from_str::<Value>(raw) {
            Ok(value) => flatten_value(&path, &value, &mut flat),
            Err(_) => {
                flat.insert(canonical_path(&path), trim_raw_json(raw).to_string());
            }
        }
    }
    flat
}

fn flatten_value(prefix: &str, value: &Value, out: &mut BTreeMap<String, String>) {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            for key in keys {
                flatten_value(&format!("{prefix}.{key}"), &map[key], out);
            }
        }
        Value::Array(items) => {
            for (i, elem) in items.iter().enumerate() {
                flatten_value(&format!("{prefix}[{i}]"), elem, out);
            }
        }
        Value::Null => {
            out.insert(canonical_path(prefix), "null".to_string());
        }
        Value::String(s) => {
            out.insert(canonical_path(prefix), s.clone());
        }
        Value::Bool(b) => {
            out.insert(canonical_path(prefix), b.to_string());
        }
        Value::Number(n) => {
            let v = n.as_f64().unwrap_or(0.0);
            out.insert(
                canonical_path(prefix),
                crate::runoverview::format_float_go(v),
            );
        }
    }
}

fn trim_raw_json(raw: &str) -> &str {
    let raw = raw.trim();
    if raw.len() >= 2 && raw.starts_with('"') && raw.ends_with('"') {
        &raw[1..raw.len() - 1]
    } else {
        raw
    }
}

/// Normalizes config paths for case-insensitive lookup.
fn canonical_path(path: &str) -> String {
    path.trim().to_lowercase()
}

// ---- Query compilation ----

/// A disjunction of AND-connected clause groups. A query matches when any
/// group matches all of its clauses.
#[derive(Default)]
pub struct RunFilterQuery {
    groups: Vec<Vec<Clause>>,
}

struct Clause {
    negated: bool,
    pred: Predicate,
}

enum Predicate {
    Bare(Matcher),
    Pattern(Field, Matcher),
    Exact(Field, String),
    NotEqual(Field, String),
    Numeric(Field, NumericOp, f64),
    /// A numeric comparison with an unparsable RHS never matches.
    Never,
    Exists(Field),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum NumericOp {
    Gt,
    Ge,
    Lt,
    Le,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Field {
    DisplayName,
    Key,
    Id,
    Project,
    Notes,
    Tags,
    ConfigAny,
    ConfigPath(String),
}

impl RunFilterQuery {
    /// Parses the runs filter language into an executable query.
    pub fn compile(raw: &str, mode: FilterMatchMode) -> Self {
        let tokens = split_terms(raw);
        if tokens.is_empty() {
            return Self::default();
        }

        let mut groups: Vec<Vec<Clause>> = Vec::new();
        let mut current: Vec<Clause> = Vec::new();
        let mut pending_negation = false;

        for mut token in tokens {
            if token == "|" || token.eq_ignore_ascii_case("or") {
                pending_negation = false;
                if !current.is_empty() {
                    groups.push(std::mem::take(&mut current));
                }
                continue;
            }
            if token.eq_ignore_ascii_case("and") {
                continue;
            }
            if token.eq_ignore_ascii_case("not") {
                pending_negation = !pending_negation;
                continue;
            }

            if pending_negation {
                token.insert(0, '!');
                pending_negation = false;
            }

            if let Some(clause) = parse_clause(&token, mode) {
                current.push(clause);
            }
        }
        if !current.is_empty() {
            groups.push(current);
        }

        Self { groups }
    }

    /// Reports whether the query matches the indexed metadata for a run.
    pub fn matches(&self, data: &WorkspaceRunFilterData) -> bool {
        if self.groups.is_empty() {
            return true;
        }
        self.groups
            .iter()
            .any(|group| group.iter().all(|clause| clause.matches(data)))
    }
}

impl Clause {
    fn matches(&self, data: &WorkspaceRunFilterData) -> bool {
        let matched = self.pred.matches(data);
        if self.negated { !matched } else { matched }
    }
}

impl Predicate {
    fn matches(&self, data: &WorkspaceRunFilterData) -> bool {
        match self {
            Predicate::Bare(matcher) => {
                let base = [
                    &data.run_key,
                    &data.display_name,
                    &data.id,
                    &data.project,
                    &data.notes,
                ];
                base.iter().any(|v| !v.is_empty() && matcher.matches(v))
                    || data
                        .tags
                        .iter()
                        .any(|v| !v.is_empty() && matcher.matches(v))
            }
            Predicate::Pattern(field, matcher) => pattern_match(data, field, matcher),
            Predicate::Exact(field, rhs) => exact_candidates(data, field)
                .iter()
                .any(|c| eq_fold(c, rhs)),
            Predicate::NotEqual(field, rhs) => {
                let candidates = exact_candidates(data, field);
                !candidates.is_empty() && !candidates.iter().any(|c| eq_fold(c, rhs))
            }
            Predicate::Numeric(field, op, want) => {
                let Some(value) = single_value(data, field) else {
                    return false;
                };
                let Ok(got) = value.trim().parse::<f64>() else {
                    return false;
                };
                match op {
                    NumericOp::Gt => got > *want,
                    NumericOp::Ge => got >= *want,
                    NumericOp::Lt => got < *want,
                    NumericOp::Le => got <= *want,
                }
            }
            Predicate::Never => false,
            Predicate::Exists(field) => field_exists(data, field),
        }
    }
}

fn eq_fold(got: &str, want: &str) -> bool {
    got.trim().eq_ignore_ascii_case(want.trim())
}

fn pattern_match(data: &WorkspaceRunFilterData, field: &Field, matcher: &Matcher) -> bool {
    let match_any = |values: &[&str]| values.iter().any(|v| !v.is_empty() && matcher.matches(v));
    match field {
        Field::DisplayName => match_any(&[&data.display_name]),
        Field::Key => match_any(&[&data.run_key]),
        Field::Id => match_any(&[&data.id]),
        Field::Project => match_any(&[&data.project]),
        Field::Notes => match_any(&[&data.notes]),
        Field::Tags => data
            .tags
            .iter()
            .any(|t| !t.is_empty() && matcher.matches(t)),
        Field::ConfigAny => data.config_by_path.iter().any(|(path, value)| {
            matcher.matches(path)
                || matcher.matches(value)
                || matcher.matches(&format!("{path}={value}"))
        }),
        Field::ConfigPath(path) => data
            .config_by_path
            .get(path)
            .is_some_and(|v| matcher.matches(v)),
    }
}

fn exact_candidates(data: &WorkspaceRunFilterData, field: &Field) -> Vec<String> {
    let non_empty = |values: &[&str]| -> Vec<String> {
        values
            .iter()
            .filter(|v| !v.is_empty())
            .map(|v| v.to_string())
            .collect()
    };
    match field {
        Field::DisplayName => non_empty(&[&data.display_name]),
        Field::Key => non_empty(&[&data.run_key]),
        Field::Id => non_empty(&[&data.id]),
        Field::Project => non_empty(&[&data.project]),
        Field::Notes => non_empty(&[&data.notes]),
        Field::Tags => data
            .tags
            .iter()
            .filter(|t| !t.is_empty())
            .cloned()
            .collect(),
        Field::ConfigAny => {
            let mut out = Vec::with_capacity(data.config_by_path.len() * 3);
            for (path, value) in &data.config_by_path {
                out.push(path.clone());
                out.push(value.clone());
                out.push(format!("{path}={value}"));
            }
            out
        }
        Field::ConfigPath(path) => data
            .config_by_path
            .get(path)
            .map(|v| vec![v.clone()])
            .unwrap_or_default(),
    }
}

fn single_value(data: &WorkspaceRunFilterData, field: &Field) -> Option<String> {
    let non_empty = |v: &str| {
        if v.is_empty() {
            None
        } else {
            Some(v.to_string())
        }
    };
    match field {
        Field::DisplayName => non_empty(&data.display_name),
        Field::Key => non_empty(&data.run_key),
        Field::Id => non_empty(&data.id),
        Field::Project => non_empty(&data.project),
        Field::Notes => non_empty(&data.notes),
        Field::ConfigPath(path) => data.config_by_path.get(path).cloned(),
        _ => None,
    }
}

fn field_exists(data: &WorkspaceRunFilterData, field: &Field) -> bool {
    match field {
        Field::DisplayName => !data.display_name.is_empty(),
        Field::Key => !data.run_key.is_empty(),
        Field::Id => !data.id.is_empty(),
        Field::Project => !data.project.is_empty(),
        Field::Notes => !data.notes.is_empty(),
        Field::Tags => !data.tags.is_empty(),
        Field::ConfigAny => !data.config_by_path.is_empty(),
        Field::ConfigPath(path) => data.config_by_path.contains_key(path),
    }
}

// ---- Tokenizer & clause parser ----

/// Tokenizes a raw query while preserving quoted phrases and backslash
/// escapes inside quotes.
fn split_terms(raw: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let mut buf = String::new();
    let mut quote: Option<char> = None;
    let mut escaped = false;

    let flush = |buf: &mut String, tokens: &mut Vec<String>| {
        let term = buf.trim().to_string();
        buf.clear();
        if !term.is_empty() {
            tokens.push(term);
        }
    };

    for r in raw.chars() {
        if escaped {
            buf.push(r);
            escaped = false;
        } else if let Some(q) = quote {
            match r {
                '\\' => escaped = true,
                _ if r == q => quote = None,
                _ => buf.push(r),
            }
        } else if r == '"' || r == '\'' {
            quote = Some(r);
        } else if r.is_whitespace() {
            flush(&mut buf, &mut tokens);
        } else {
            buf.push(r);
        }
    }
    flush(&mut buf, &mut tokens);
    tokens
}

fn parse_clause(token: &str, mode: FilterMatchMode) -> Option<Clause> {
    let mut token = token.trim();
    if token.is_empty() {
        return None;
    }

    let mut negated = false;
    while let Some(rest) = token.strip_prefix(['-', '!']) {
        negated = !negated;
        token = rest;
    }
    if token.is_empty() {
        return None;
    }

    let bare = |negated| Clause {
        negated,
        pred: Predicate::Bare(compile_text_matcher(token, mode)),
    };

    let Some((lhs, rhs, op)) = split_operation(token) else {
        return Some(bare(negated));
    };

    if op == ":" && matches!(lhs.to_lowercase().as_str(), "has" | "exists") {
        let Some(field) = parse_field(rhs) else {
            return Some(bare(negated));
        };
        return Some(Clause {
            negated,
            pred: Predicate::Exists(field),
        });
    }

    let Some(field) = parse_field(lhs) else {
        return Some(bare(negated));
    };

    let pred = match op {
        ":" => Predicate::Pattern(field, compile_text_matcher(rhs, mode)),
        "=" => Predicate::Exact(field, rhs.to_string()),
        "!=" => Predicate::NotEqual(field, rhs.to_string()),
        ">" | ">=" | "<" | "<=" => match rhs.trim().parse::<f64>() {
            Ok(want) => {
                let num_op = match op {
                    ">" => NumericOp::Gt,
                    ">=" => NumericOp::Ge,
                    "<" => NumericOp::Lt,
                    _ => NumericOp::Le,
                };
                Predicate::Numeric(field, num_op, want)
            }
            Err(_) => Predicate::Never,
        },
        _ => return Some(bare(negated)),
    };

    Some(Clause { negated, pred })
}

/// Splits a token at its leftmost supported operator.
///
/// Preferring the earliest operator keeps queries like `name:^(foo=bar)$`
/// working, because the field separator is chosen before operator-like
/// characters that appear later in the pattern.
fn split_operation(token: &str) -> Option<(&str, &str, &str)> {
    const OPERATORS: [&str; 7] = [">=", "<=", "!=", "=", ">", "<", ":"];

    let mut best: Option<(usize, &str)> = None;
    for candidate in OPERATORS {
        let Some(idx) = token.find(candidate) else {
            continue;
        };
        if idx == 0 {
            continue;
        }
        match best {
            None => best = Some((idx, candidate)),
            Some((best_idx, best_op)) => {
                if idx < best_idx || (idx == best_idx && candidate.len() > best_op.len()) {
                    best = Some((idx, candidate));
                }
            }
        }
    }

    let (idx, op) = best?;
    let lhs = token[..idx].trim();
    let rhs = token[idx + op.len()..].trim();
    if lhs.is_empty() {
        return None;
    }
    Some((lhs, rhs, op))
}

/// Resolves field aliases and `cfg.`/`config.` path selectors.
fn parse_field(raw: &str) -> Option<Field> {
    let field = raw.trim().to_lowercase();
    if field.is_empty() {
        return None;
    }

    match field.as_str() {
        "name" | "run_name" | "display" | "display_name" => return Some(Field::DisplayName),
        "key" | "run_key" | "path" => return Some(Field::Key),
        "id" | "run_id" => return Some(Field::Id),
        "project" => return Some(Field::Project),
        "note" | "notes" => return Some(Field::Notes),
        "tag" | "tags" => return Some(Field::Tags),
        "config" | "cfg" => return Some(Field::ConfigAny),
        _ => {}
    }

    for prefix in ["config.", "cfg."] {
        if let Some(path) = field.strip_prefix(prefix)
            && !path.is_empty()
        {
            return Some(Field::ConfigPath(canonical_path(path)));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn data() -> WorkspaceRunFilterData {
        WorkspaceRunFilterData {
            run_key: "run-20260701_120000-abc123".into(),
            display_name: "sunny-dawn-42".into(),
            id: "abc123".into(),
            project: "llm-pretraining".into(),
            notes: "high lr experiment".into(),
            tags: vec!["debug".into(), "high-lr".into()],
            config_by_path: BTreeMap::from([
                ("lr".to_string(), "0.002".to_string()),
                ("model.layers".to_string(), "32".to_string()),
                ("optimizer".to_string(), "sgd".to_string()),
            ]),
        }
    }

    fn matches(q: &str) -> bool {
        RunFilterQuery::compile(q, FilterMatchMode::Regex).matches(&data())
    }

    #[test]
    fn bare_terms() {
        assert!(matches("sunny"));
        assert!(matches("abc123"));
        assert!(matches("high-lr"));
        assert!(!matches("nonexistent"));
    }

    #[test]
    fn and_or_not() {
        assert!(matches("sunny debug"));
        assert!(!matches("sunny nonexistent"));
        assert!(matches("nonexistent or sunny"));
        assert!(matches("nonexistent | sunny"));
        assert!(matches("not nonexistent"));
        assert!(!matches("not sunny"));
        assert!(matches("!nonexistent"));
    }

    #[test]
    fn field_operators() {
        assert!(matches("project:llm"));
        assert!(matches("project=llm-pretraining"));
        assert!(!matches("project=llm"));
        assert!(matches("project!=other"));
        assert!(matches("tag:debug"));
        assert!(matches("has:notes"));
        assert!(matches("exists:cfg.lr"));
        assert!(!matches("has:cfg.nonexistent"));
    }

    #[test]
    fn numeric_comparisons() {
        assert!(matches("cfg.lr>0.001"));
        assert!(matches("cfg.lr<=0.002"));
        assert!(!matches("cfg.lr>0.01"));
        assert!(matches("cfg.model.layers>=32"));
        assert!(!matches("cfg.optimizer>1"));
    }

    #[test]
    fn config_any() {
        assert!(matches("config:sgd"));
        assert!(matches("cfg:model.layers"));
        assert!(matches("cfg:optimizer=sgd"));
    }

    #[test]
    fn quoted_phrases() {
        assert!(matches("notes:\"high lr\""));
        assert!(!matches("notes:\"low lr\""));
    }
}
