//! Port of `core/internal/leet/runfilterquery.go` — the workspace runs-sidebar
//! query language: tokenizer, parser, and evaluator.
//!
//! DIVERGENCE: also hosts the pure text-matching subset of
//! `core/internal/leet/filter.go` ([`FilterMatchMode`], [`compile_text_matcher`]
//! and the glob helpers). In Go those live in `filter.go`, which otherwise
//! ports to `leet-tui` (it handles `tea.KeyPressMsg`); the matcher is shared by
//! the generic `Filter` type and higher-level query parsers, so it lives here
//! in `leet-data` where both crates can reach it. Recorded in PORTING.md
//! (module mapping) and PARITY.md §2.8: `leet-tui`'s `filter` module must
//! reuse/re-export these, not re-port them.

use std::collections::HashMap;
use std::fmt;

use regex::Regex;

/// FilterMatchMode selects the string-matching engine for metric titles.
// PARITY: declared in filter.go in Go (FilterModeUndefined is the zero value).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum FilterMatchMode {
    #[default]
    Undefined,
    Regex,
    Glob,
}

impl fmt::Display for FilterMatchMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FilterMatchMode::Glob => write!(f, "glob"),
            _ => write!(f, "regex"),
        }
    }
}

/// A compiled case-insensitive text matcher (Go: `func(string) bool`).
pub type TextMatcher = Box<dyn Fn(&str) -> bool>;

/// One compiled run-filter predicate (Go: `func(WorkspaceRunFilterData) bool`).
type MatchFn = Box<dyn Fn(&WorkspaceRunFilterData) -> bool>;

/// WorkspaceRunFilterData is the precomputed searchable metadata for one run in
/// the workspace runs sidebar.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct WorkspaceRunFilterData {
    pub run_key: String,
    pub display_name: String,
    pub id: String,
    pub project: String,
    pub notes: String,
    pub tags: Vec<String>,

    /// ConfigByPath stores flattened config values keyed by canonicalized path.
    pub config_by_path: HashMap<String, String>,
    /// ConfigEntries preserves the flattened config for broader "config:<term>"
    /// searches that should match either a key or a value.
    pub config_entries: Vec<RunFilterConfigEntry>,
}

/// RunFilterConfigEntry stores one flattened config path/value pair.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct RunFilterConfigEntry {
    pub path: String,
    pub value: String,
}

/// RunFilterQuery is a disjunction of AND-connected clause groups.
///
/// A query matches when any group matches all of its clauses.
#[derive(Default)]
pub struct RunFilterQuery {
    groups: Vec<RunFilterGroup>,
}

/// RunFilterGroup is one AND-connected group inside a runs filter query.
#[derive(Default)]
struct RunFilterGroup {
    clauses: Vec<RunFilterClause>,
}

/// RunFilterClause is one atomic predicate with optional negation.
struct RunFilterClause {
    negated: bool,
    // Go: `match`; renamed because `match` is a Rust keyword.
    match_fn: Option<MatchFn>,
}

impl RunFilterClause {
    /// Match evaluates the clause against one run's indexed metadata.
    // Go: Match.
    fn matches(&self, data: &WorkspaceRunFilterData) -> bool {
        let Some(match_fn) = &self.match_fn else {
            return true;
        };
        let matched = match_fn(data);
        if self.negated {
            return !matched;
        }
        matched
    }
}

/// CompileRunFilterQuery parses the runs filter language into an executable
/// query.
///
/// Bare terms search the default text fields (run key, name, id, project,
/// notes, and tags). Whitespace and AND join clauses, OR or | starts a new
/// group, NOT negates the next clause, and field operators support pattern
/// matching (:), exact matching (=, !=), numeric comparisons, and existence
/// checks (has:field).
pub fn compile_run_filter_query(raw: &str, mode: FilterMatchMode) -> RunFilterQuery {
    let tokens = split_run_filter_terms(raw);
    if tokens.is_empty() {
        return RunFilterQuery::default();
    }

    let mut groups: Vec<RunFilterGroup> = Vec::with_capacity(1);
    let mut current = RunFilterGroup::default();
    let mut pending_negation = false;

    for mut token in tokens {
        if token == "|" || go_equal_fold(&token, "or") {
            pending_negation = false;
            if !current.clauses.is_empty() {
                groups.push(std::mem::take(&mut current));
            }
            continue;
        }
        if go_equal_fold(&token, "and") {
            continue;
        }
        if go_equal_fold(&token, "not") {
            pending_negation = !pending_negation;
            continue;
        }

        if pending_negation {
            token = format!("!{token}");
            pending_negation = false;
        }

        let Some(clause) = parse_run_filter_clause(&token, mode) else {
            continue;
        };
        current.clauses.push(clause);
    }

    if !current.clauses.is_empty() {
        groups.push(current);
    }

    RunFilterQuery { groups }
}

impl RunFilterQuery {
    /// Match reports whether the query matches the indexed metadata for a run.
    // Go: Match.
    pub fn matches(&self, data: &WorkspaceRunFilterData) -> bool {
        if self.groups.is_empty() {
            return true;
        }

        for group in &self.groups {
            let mut matched = true;
            for clause in &group.clauses {
                if !clause.matches(data) {
                    matched = false;
                    break;
                }
            }
            if matched {
                return true;
            }
        }

        false
    }
}

/// splitRunFilterTerms tokenizes a raw query while preserving quoted phrases and
/// backslash escapes inside quotes.
fn split_run_filter_terms(raw: &str) -> Vec<String> {
    let mut tokens: Vec<String> = Vec::new();
    let mut b = String::new();
    let mut quote = '\0';
    let mut escaped = false;

    fn flush(b: &mut String, tokens: &mut Vec<String>) {
        let term = b.trim().to_string();
        b.clear();
        if !term.is_empty() {
            tokens.push(term);
        }
    }

    for r in raw.chars() {
        if escaped {
            b.push(r);
            escaped = false;
        } else if quote != '\0' {
            match r {
                '\\' => escaped = true,
                _ if r == quote => quote = '\0',
                _ => b.push(r),
            }
        } else if r == '"' || r == '\'' {
            quote = r;
        } else if r.is_whitespace() {
            // PARITY: Go unicode.IsSpace and char::is_whitespace both follow
            // the Unicode White_Space property.
            flush(&mut b, &mut tokens);
        } else {
            b.push(r);
        }
    }

    flush(&mut b, &mut tokens);
    tokens
}

/// parseRunFilterClause parses one token into either a fielded predicate or a
/// bare-text clause.
fn parse_run_filter_clause(token: &str, mode: FilterMatchMode) -> Option<RunFilterClause> {
    let mut token = token.trim();
    if token.is_empty() {
        return None;
    }

    let mut negated = false;
    while !token.is_empty() && (token.as_bytes()[0] == b'-' || token.as_bytes()[0] == b'!') {
        negated = !negated;
        token = &token[1..];
    }

    if token.is_empty() {
        return None;
    }

    let Some((lhs, rhs, op)) = split_run_filter_operation(token) else {
        return Some(new_bare_run_filter_clause(token, mode, negated));
    };

    if is_run_filter_exists_operator(&lhs, op) {
        let Some(field) = parse_run_filter_field(&rhs) else {
            return Some(new_bare_run_filter_clause(token, mode, negated));
        };
        return Some(RunFilterClause {
            negated,
            match_fn: Some(Box::new(move |data| run_filter_field_exists(data, &field))),
        });
    }

    let Some(field) = parse_run_filter_field(&lhs) else {
        return Some(new_bare_run_filter_clause(token, mode, negated));
    };

    let Some(predicate) = build_run_filter_predicate(field, op, &rhs, mode) else {
        return Some(new_bare_run_filter_clause(token, mode, negated));
    };

    Some(RunFilterClause {
        negated,
        match_fn: Some(predicate),
    })
}

/// newBareRunFilterClause searches the default text fields without requiring an
/// explicit field qualifier.
fn new_bare_run_filter_clause(term: &str, mode: FilterMatchMode, negated: bool) -> RunFilterClause {
    let matcher = compile_text_matcher(term, mode);
    RunFilterClause {
        negated,
        match_fn: Some(Box::new(move |data| {
            let mut values: Vec<&str> = vec![
                &data.run_key,
                &data.display_name,
                &data.id,
                &data.project,
                &data.notes,
            ];
            values.extend(data.tags.iter().map(String::as_str));
            run_filter_match_any(&matcher, &values)
        })),
    }
}

/// splitRunFilterOperation splits a token at its leftmost supported operator.
///
/// Preferring the earliest operator keeps queries like name:^(foo=bar)$ working,
/// because the field separator is chosen before operator-like characters that
/// appear later in the pattern.
fn split_run_filter_operation(token: &str) -> Option<(String, String, &'static str)> {
    const OPERATORS: [&str; 7] = [">=", "<=", "!=", "=", ">", "<", ":"];
    let mut best_idx: Option<usize> = None;
    let mut best_op: &'static str = "";

    for candidate in OPERATORS {
        // Go: strings.Index returns -1 when absent; `idx <= 0` also skips a
        // match at position 0 (byte indices in both languages).
        let Some(idx) = token.find(candidate) else {
            continue;
        };
        if idx == 0 {
            continue;
        }
        let better = match best_idx {
            None => true,
            Some(best) => idx < best || (idx == best && candidate.len() > best_op.len()),
        };
        if better {
            best_idx = Some(idx);
            best_op = candidate;
        }
    }
    let best_idx = best_idx?;

    let lhs = token[..best_idx].trim();
    let rhs = token[best_idx + best_op.len()..].trim();
    if lhs.is_empty() {
        return None;
    }
    Some((lhs.to_string(), rhs.to_string(), best_op))
}

/// isRunFilterExistsOperator reports whether lhs:rhs is an existence query such
/// as has:project or exists:cfg.dataset.
fn is_run_filter_exists_operator(lhs: &str, op: &str) -> bool {
    if op != ":" {
        return false;
    }
    let lhs = go_to_lower(lhs.trim());
    lhs == "has" || lhs == "exists"
}

/// runFilterFieldKind identifies the searchable fields supported by the runs
/// filter language.
// PARITY: Go's runFilterFieldInvalid zero value is unrepresentable here;
// parse_run_filter_field returns None instead.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RunFilterFieldKind {
    DisplayName,
    Key,
    Id,
    Project,
    Notes,
    Tags,
    ConfigAny,
    ConfigPath,
}

/// runFilterField names a supported field or a specific flattened config path.
#[derive(Debug, Clone)]
struct RunFilterField {
    kind: RunFilterFieldKind,
    path: String,
}

impl RunFilterField {
    fn new(kind: RunFilterFieldKind) -> Self {
        RunFilterField {
            kind,
            path: String::new(),
        }
    }
}

/// parseRunFilterField resolves field aliases and cfg./config. path selectors.
fn parse_run_filter_field(raw: &str) -> Option<RunFilterField> {
    let field = go_to_lower(raw.trim());
    if field.is_empty() {
        return None;
    }

    match field.as_str() {
        "name" | "run_name" | "display" | "display_name" => {
            return Some(RunFilterField::new(RunFilterFieldKind::DisplayName));
        }
        "key" | "run_key" | "path" => {
            return Some(RunFilterField::new(RunFilterFieldKind::Key));
        }
        "id" | "run_id" => {
            return Some(RunFilterField::new(RunFilterFieldKind::Id));
        }
        "project" => {
            return Some(RunFilterField::new(RunFilterFieldKind::Project));
        }
        "note" | "notes" => {
            return Some(RunFilterField::new(RunFilterFieldKind::Notes));
        }
        "tag" | "tags" => {
            return Some(RunFilterField::new(RunFilterFieldKind::Tags));
        }
        "config" | "cfg" => {
            return Some(RunFilterField::new(RunFilterFieldKind::ConfigAny));
        }
        _ => {}
    }

    if let Some(path) = field.strip_prefix("config.")
        && !path.is_empty()
    {
        return Some(RunFilterField {
            kind: RunFilterFieldKind::ConfigPath,
            path: canonical_run_filter_path(path),
        });
    }
    if let Some(path) = field.strip_prefix("cfg.")
        && !path.is_empty()
    {
        return Some(RunFilterField {
            kind: RunFilterFieldKind::ConfigPath,
            path: canonical_run_filter_path(path),
        });
    }

    None
}

/// buildRunFilterPredicate builds a field-specific predicate for op and rhs.
fn build_run_filter_predicate(
    field: RunFilterField,
    op: &'static str,
    rhs: &str,
    mode: FilterMatchMode,
) -> Option<MatchFn> {
    match op {
        ":" => {
            let matcher = compile_text_matcher(rhs, mode);
            Some(Box::new(move |data| {
                run_filter_pattern_match(data, &field, &matcher)
            }))
        }
        "=" => {
            let rhs = rhs.to_string();
            Some(Box::new(move |data| {
                run_filter_exact_match(data, &field, &rhs)
            }))
        }
        "!=" => {
            let rhs = rhs.to_string();
            Some(Box::new(move |data| {
                run_filter_exact_mismatch(data, &field, &rhs)
            }))
        }
        ">" | ">=" | "<" | "<=" => {
            let Some(want) = parse_run_filter_number(rhs) else {
                return Some(Box::new(|_| false));
            };
            Some(Box::new(move |data| {
                run_filter_numeric_compare(data, &field, op, want)
            }))
        }
        _ => None,
    }
}

/// runFilterPatternMatch applies a mode-aware text matcher to the selected field.
fn run_filter_pattern_match(
    data: &WorkspaceRunFilterData,
    field: &RunFilterField,
    matcher: &TextMatcher,
) -> bool {
    match field.kind {
        RunFilterFieldKind::DisplayName => run_filter_match_any(matcher, &[&data.display_name]),
        RunFilterFieldKind::Key => run_filter_match_any(matcher, &[&data.run_key]),
        RunFilterFieldKind::Id => run_filter_match_any(matcher, &[&data.id]),
        RunFilterFieldKind::Project => run_filter_match_any(matcher, &[&data.project]),
        RunFilterFieldKind::Notes => run_filter_match_any(matcher, &[&data.notes]),
        RunFilterFieldKind::Tags => {
            let tags: Vec<&str> = data.tags.iter().map(String::as_str).collect();
            run_filter_match_any(matcher, &tags)
        }
        RunFilterFieldKind::ConfigAny => {
            for entry in &data.config_entries {
                if matcher(&entry.path)
                    || matcher(&entry.value)
                    || matcher(&format!("{}={}", entry.path, entry.value))
                {
                    return true;
                }
            }
            false
        }
        RunFilterFieldKind::ConfigPath => {
            let Some(value) = data.config_by_path.get(&field.path) else {
                return false;
            };
            matcher(value)
        }
    }
}

/// runFilterExactMatch reports whether any candidate value equals rhs.
fn run_filter_exact_match(
    data: &WorkspaceRunFilterData,
    field: &RunFilterField,
    rhs: &str,
) -> bool {
    let candidates = run_filter_exact_candidates(data, field);
    for candidate in &candidates {
        if run_filter_exact_value_equal(candidate, rhs) {
            return true;
        }
    }
    false
}

/// runFilterExactMismatch reports whether all candidate values differ from rhs.
fn run_filter_exact_mismatch(
    data: &WorkspaceRunFilterData,
    field: &RunFilterField,
    rhs: &str,
) -> bool {
    let candidates = run_filter_exact_candidates(data, field);
    if candidates.is_empty() {
        return false;
    }
    for candidate in &candidates {
        if run_filter_exact_value_equal(candidate, rhs) {
            return false;
        }
    }
    true
}

/// runFilterExactCandidates returns the values inspected by exact and inequality
/// operations for a field.
fn run_filter_exact_candidates(
    data: &WorkspaceRunFilterData,
    field: &RunFilterField,
) -> Vec<String> {
    match field.kind {
        RunFilterFieldKind::DisplayName => run_filter_non_empty_strings(&[&data.display_name]),
        RunFilterFieldKind::Key => run_filter_non_empty_strings(&[&data.run_key]),
        RunFilterFieldKind::Id => run_filter_non_empty_strings(&[&data.id]),
        RunFilterFieldKind::Project => run_filter_non_empty_strings(&[&data.project]),
        RunFilterFieldKind::Notes => run_filter_non_empty_strings(&[&data.notes]),
        RunFilterFieldKind::Tags => {
            let tags: Vec<&str> = data.tags.iter().map(String::as_str).collect();
            run_filter_non_empty_strings(&tags)
        }
        RunFilterFieldKind::ConfigAny => {
            let mut out = Vec::with_capacity(data.config_entries.len() * 3);
            for entry in &data.config_entries {
                out.push(entry.path.clone());
                out.push(entry.value.clone());
                out.push(format!("{}={}", entry.path, entry.value));
            }
            out
        }
        RunFilterFieldKind::ConfigPath => {
            if let Some(value) = data.config_by_path.get(&field.path) {
                return vec![value.clone()];
            }
            Vec::new()
        }
    }
}

/// runFilterExactValueEqual compares values case-insensitively after trimming
/// surrounding whitespace.
///
/// Exact operators are intentionally string-based. Numeric semantics belong to
/// >, >=, <, and <= so identifiers like "00123" do not accidentally match "123".
fn run_filter_exact_value_equal(got: &str, want: &str) -> bool {
    go_equal_fold(got.trim(), want.trim())
}

/// runFilterNumericCompare applies a numeric comparison to fields that resolve
/// to a single numeric value.
fn run_filter_numeric_compare(
    data: &WorkspaceRunFilterData,
    field: &RunFilterField,
    op: &str,
    want: f64,
) -> bool {
    let Some(value) = run_filter_single_value(data, field) else {
        return false;
    };
    let Some(got) = parse_run_filter_number(value) else {
        return false;
    };

    match op {
        ">" => got > want,
        ">=" => got >= want,
        "<" => got < want,
        "<=" => got <= want,
        _ => false,
    }
}

/// runFilterSingleValue returns the single value addressable by numeric
/// comparison operators.
fn run_filter_single_value<'a>(
    data: &'a WorkspaceRunFilterData,
    field: &RunFilterField,
) -> Option<&'a str> {
    match field.kind {
        RunFilterFieldKind::DisplayName => {
            (!data.display_name.is_empty()).then_some(data.display_name.as_str())
        }
        RunFilterFieldKind::Key => (!data.run_key.is_empty()).then_some(data.run_key.as_str()),
        RunFilterFieldKind::Id => (!data.id.is_empty()).then_some(data.id.as_str()),
        RunFilterFieldKind::Project => (!data.project.is_empty()).then_some(data.project.as_str()),
        RunFilterFieldKind::Notes => (!data.notes.is_empty()).then_some(data.notes.as_str()),
        RunFilterFieldKind::ConfigPath => data.config_by_path.get(&field.path).map(String::as_str),
        _ => None,
    }
}

/// runFilterFieldExists reports whether a field is present in indexed run
/// metadata.
fn run_filter_field_exists(data: &WorkspaceRunFilterData, field: &RunFilterField) -> bool {
    match field.kind {
        RunFilterFieldKind::DisplayName => !data.display_name.is_empty(),
        RunFilterFieldKind::Key => !data.run_key.is_empty(),
        RunFilterFieldKind::Id => !data.id.is_empty(),
        RunFilterFieldKind::Project => !data.project.is_empty(),
        RunFilterFieldKind::Notes => !data.notes.is_empty(),
        RunFilterFieldKind::Tags => !data.tags.is_empty(),
        RunFilterFieldKind::ConfigAny => !data.config_entries.is_empty(),
        RunFilterFieldKind::ConfigPath => data.config_by_path.contains_key(&field.path),
    }
}

fn run_filter_match_any(matcher: &TextMatcher, values: &[&str]) -> bool {
    for value in values {
        if !value.is_empty() && matcher(value) {
            return true;
        }
    }
    false
}

fn run_filter_non_empty_strings(values: &[&str]) -> Vec<String> {
    let mut out = Vec::with_capacity(values.len());
    for value in values {
        if value.is_empty() {
            continue;
        }
        out.push((*value).to_string());
    }
    out
}

/// canonicalRunFilterPath normalizes config paths for case-insensitive lookup.
fn canonical_run_filter_path(path: &str) -> String {
    go_to_lower(path.trim())
}

/// parseRunFilterNumber parses a numeric literal used by numeric comparison
/// operators.
fn parse_run_filter_number(raw: &str) -> Option<f64> {
    let trimmed = raw.trim();
    // PARITY: Go strconv.ParseFloat additionally accepts hex float literals
    // ("0x1p3") and digit-separating underscores ("1_000"); str::parse::<f64>
    // rejects both. Accepted divergence for these exotic literals.
    let value = trimmed.parse::<f64>().ok()?;
    // PARITY: Go strconv.ParseFloat returns ErrRange on overflow, so "1e999"
    // fails to parse there; str::parse saturates to ±inf instead. Reject
    // non-finite results unless the literal itself spelled an infinity (both
    // parsers accept "inf"/"infinity" with optional sign, case-insensitive).
    if value.is_infinite() && !is_infinity_literal(trimmed) {
        return None;
    }
    Some(value)
}

fn is_infinity_literal(s: &str) -> bool {
    let s = s.strip_prefix(['+', '-']).unwrap_or(s);
    s.eq_ignore_ascii_case("inf") || s.eq_ignore_ascii_case("infinity")
}

// --- Text matching (pure subset of core/internal/leet/filter.go) ---

/// compileTextMatcher returns a case-insensitive matcher according to mode.
///
/// It is shared by the generic `Filter` type and higher-level query parsers
/// (for example the workspace runs filter) so all text filtering in LEET uses
/// the same glob/regex semantics.
pub fn compile_text_matcher(query: &str, mode: FilterMatchMode) -> TextMatcher {
    if query.is_empty() {
        return Box::new(|_| true);
    }

    match mode {
        FilterMatchMode::Glob => {
            let query = query.to_string();
            Box::new(move |s| glob_match_unanchored_case_insensitive(&query, s))
        }
        FilterMatchMode::Regex => {
            if !has_regex_meta(query) {
                let lq = go_to_lower(query);
                return Box::new(move |s| go_to_lower(s).contains(&lq));
            }
            // Compile once; if it fails, fall back to substring.
            // PARITY: Go regexp is RE2; the regex crate is compatible for
            // leet's pattern subset, and both reach this fallback on error.
            match Regex::new(&format!("(?i){query}")) {
                Ok(re) => Box::new(move |s| re.is_match(s)),
                Err(_) => {
                    let lq = go_to_lower(query);
                    Box::new(move |s| go_to_lower(s).contains(&lq))
                }
            }
        }
        FilterMatchMode::Undefined => Box::new(|_| true),
    }
}

/// globMatchUnanchoredCaseInsensitive reports whether s matches pattern using
/// case-insensitive, unanchored glob semantics.
///
/// Supported meta: '*' (any sequence), '?' (any single char).
/// '/' is treated as a normal character (not a separator).
fn glob_match_unanchored_case_insensitive(pattern: &str, s: &str) -> bool {
    let mut p = go_to_lower(pattern);
    let t = go_to_lower(s);

    // Empty or single '*' matches everything.
    if p.is_empty() || p == "*" {
        return true;
    }

    // No wildcards -> substring match.
    if !p.contains(['*', '?']) {
        return t.contains(&p);
    }

    // Unanchored by default: allow leading/trailing text.
    if !p.starts_with('*') {
        p = format!("*{p}");
    }
    if !p.ends_with('*') {
        p.push('*');
    }

    wildcard_match(p.as_bytes(), t.as_bytes())
}

/// wildcardMatch is a classic '*'/'?' matcher with backtracking.
/// Assumes inputs are already lowercased.
// PARITY: Go indexes BYTES here, so '?' matches one byte (not one rune) —
// ported byte-for-byte.
fn wildcard_match(p: &[u8], t: &[u8]) -> bool {
    let mut pi = 0usize;
    let mut si = 0usize;
    let mut star: Option<usize> = None;
    let mut matched = 0usize;

    while si < t.len() {
        if pi < p.len() && (p[pi] == b'?' || p[pi] == t[si]) {
            pi += 1;
            si += 1;
        } else if pi < p.len() && p[pi] == b'*' {
            star = Some(pi);
            matched = si;
            pi += 1;
        } else if let Some(star_idx) = star {
            pi = star_idx + 1;
            matched += 1;
            si = matched;
        } else {
            return false;
        }
    }
    while pi < p.len() && p[pi] == b'*' {
        pi += 1;
    }
    pi == p.len()
}

/// hasRegexMeta reports whether s contains any Go regexp metacharacters.
fn has_regex_meta(s: &str) -> bool {
    s.chars().any(|r| {
        matches!(
            r,
            '.' | '^' | '$' | '*' | '+' | '?' | '(' | ')' | '[' | ']' | '{' | '}' | '|' | '\\'
        )
    })
}

// --- Go strings case-mapping shims ---

/// Go `strings.ToLower`.
// PARITY: Go applies unicode.ToLower per rune (simple mapping, no final-sigma
// context rule). char::to_lowercase is the closest match; it diverges only on
// the few full-mapping expansions (e.g. U+0130 'İ' -> "i\u{307}" here, 'i' in
// Go). str::to_lowercase is NOT used because its final-sigma handling would
// diverge on Greek text.
fn go_to_lower(s: &str) -> String {
    s.chars().flat_map(char::to_lowercase).collect()
}

/// Go `strings.EqualFold`.
// PARITY: approximates Go's Unicode simple case folding by comparing per-rune
// lowercasings; diverges only on multi-member fold orbits whose lowercase
// forms differ (e.g. 'σ'/'ς'). Exact for ASCII.
fn go_equal_fold(a: &str, b: &str) -> bool {
    go_to_lower(a) == go_to_lower(b)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_run_filter_data() -> WorkspaceRunFilterData {
        WorkspaceRunFilterData {
            run_key: "run-20260209_010101-abc123".to_string(),
            display_name: "resnet50-baseline".to_string(),
            id: "abc123".to_string(),
            project: "vision".to_string(),
            notes: "warm start from imagenet checkpoint".to_string(),
            tags: vec!["scheduled".to_string(), "release".to_string()],
            config_by_path: HashMap::from([
                ("lr".to_string(), "0.001".to_string()),
                ("optimizer".to_string(), "adamw".to_string()),
                ("model.layers".to_string(), "12".to_string()),
            ]),
            config_entries: vec![
                RunFilterConfigEntry {
                    path: "lr".to_string(),
                    value: "0.001".to_string(),
                },
                RunFilterConfigEntry {
                    path: "optimizer".to_string(),
                    value: "adamw".to_string(),
                },
                RunFilterConfigEntry {
                    path: "model.layers".to_string(),
                    value: "12".to_string(),
                },
            ],
        }
    }

    // Go: TestCompileRunFilterQuery_BareTermMatchesIdentityFields
    #[test]
    fn compile_run_filter_query_bare_term_matches_identity_fields() {
        let data = test_run_filter_data();

        assert!(compile_run_filter_query("vision", FilterMatchMode::Regex).matches(&data));
        assert!(compile_run_filter_query("resnet", FilterMatchMode::Regex).matches(&data));
        assert!(compile_run_filter_query("abc123", FilterMatchMode::Regex).matches(&data));
        assert!(compile_run_filter_query("checkpoint", FilterMatchMode::Regex).matches(&data));
        assert!(compile_run_filter_query("scheduled", FilterMatchMode::Regex).matches(&data));
        assert!(!compile_run_filter_query("nonexistent", FilterMatchMode::Regex).matches(&data));
    }

    // Go: TestCompileRunFilterQuery_ProjectAndConfigClauses
    #[test]
    fn compile_run_filter_query_project_and_config_clauses() {
        let data = test_run_filter_data();

        let query = compile_run_filter_query(
            "project:vision cfg.lr>=1e-3 cfg.optimizer=adamw cfg.model.layers=12",
            FilterMatchMode::Regex,
        );
        assert!(query.matches(&data));

        let query = compile_run_filter_query("project:vision cfg.lr>0.01", FilterMatchMode::Regex);
        assert!(!query.matches(&data));
    }

    // Go: TestCompileRunFilterQuery_GlobNegationAndOr
    #[test]
    fn compile_run_filter_query_glob_negation_and_or() {
        let mut data = test_run_filter_data();

        let query = compile_run_filter_query(
            "project:vis* -name:debug | project:nlp",
            FilterMatchMode::Glob,
        );
        assert!(query.matches(&data));

        data.display_name = "debug-run".to_string();
        assert!(
            !query.matches(&data),
            "negated name clause should exclude the vision run"
        );

        data.project = "nlp".to_string();
        assert!(
            query.matches(&data),
            "OR group should match the nlp project"
        );
    }

    // Go: TestCompileRunFilterQuery_HasAndConfigAnySearch
    #[test]
    fn compile_run_filter_query_has_and_config_any_search() {
        let data = test_run_filter_data();

        let query = compile_run_filter_query("has:cfg.lr config:adam", FilterMatchMode::Regex);
        assert!(query.matches(&data));

        let query = compile_run_filter_query("has:cfg.missing", FilterMatchMode::Regex);
        assert!(!query.matches(&data));
    }

    // Go: TestCompileRunFilterQuery_TextualBooleanAliases
    #[test]
    fn compile_run_filter_query_textual_boolean_aliases() {
        let mut data = test_run_filter_data();

        let query = compile_run_filter_query(
            "project:vision AND NOT name:debug OR project:nlp",
            FilterMatchMode::Regex,
        );
        assert!(query.matches(&data));

        data.display_name = "debug-run".to_string();
        assert!(
            !query.matches(&data),
            "NOT alias should negate the following clause"
        );
    }

    // Go: TestCompileRunFilterQuery_ExactMatchDoesNotCoerceNumericLookingIDs
    #[test]
    fn compile_run_filter_query_exact_match_does_not_coerce_numeric_looking_ids() {
        let mut data = test_run_filter_data();
        data.id = "00123".to_string();
        data.project = "010".to_string();

        assert!(compile_run_filter_query("id=00123", FilterMatchMode::Regex).matches(&data));
        assert!(!compile_run_filter_query("id=123", FilterMatchMode::Regex).matches(&data));

        assert!(compile_run_filter_query("project=010", FilterMatchMode::Regex).matches(&data));
        assert!(!compile_run_filter_query("project=10", FilterMatchMode::Regex).matches(&data));
    }

    // Go: TestCompileRunFilterQuery_QuotedTermsAndEscapes
    #[test]
    fn compile_run_filter_query_quoted_terms_and_escapes() {
        let mut data = test_run_filter_data();
        data.display_name = r#"exp "alpha" baseline"#.to_string();

        assert!(
            compile_run_filter_query(r#"name:"exp \"alpha\"""#, FilterMatchMode::Regex)
                .matches(&data)
        );
        assert!(
            !compile_run_filter_query(r#"name:"exp \"beta\"""#, FilterMatchMode::Regex)
                .matches(&data)
        );
    }

    // Go: TestCompileRunFilterQuery_DisplayAliasesAreConsistentAcrossOperators
    #[test]
    fn compile_run_filter_query_display_aliases_are_consistent_across_operators() {
        let data = WorkspaceRunFilterData {
            run_key: "run-20260209_010101-vision01".to_string(),
            display_name: "baseline".to_string(),
            ..Default::default()
        };

        for query in [
            "run_name:base",
            "name:base",
            "display:base",
            "display_name:base",
            //
            "run_name=baseline",
            "name=baseline",
            "display=baseline",
            "display_name=baseline",
            //
            "run_name!=other",
            "name!=other",
            "display!=other",
            "display_name!=other",
            //
            "has:run_name",
            "has:name",
            "has:display",
            "has:display_name",
        ] {
            assert!(
                compile_run_filter_query(query, FilterMatchMode::Regex).matches(&data),
                "query={query:?}"
            );
        }
    }

    // Go: TestCompileRunFilterQuery_TagAndNoteAliasesAreConsistentAcrossOperators
    #[test]
    fn compile_run_filter_query_tag_and_note_aliases_are_consistent_across_operators() {
        let data = test_run_filter_data();

        for query in [
            "tag:scheduled",
            "tags:scheduled",
            "tag=release",
            "tags=release",
            "tag!=canary",
            "tags!=canary",
            "has:tag",
            "has:tags",
            //
            "note:checkpoint",
            "notes:checkpoint",
            r#"note="warm start from imagenet checkpoint""#,
            r#"notes="warm start from imagenet checkpoint""#,
            "note!=debug",
            "notes!=debug",
            "has:note",
            "has:notes",
        ] {
            assert!(
                compile_run_filter_query(query, FilterMatchMode::Regex).matches(&data),
                "query={query:?}"
            );
        }

        assert!(!compile_run_filter_query("tag!=release", FilterMatchMode::Regex).matches(&data));
        assert!(!compile_run_filter_query("note:ablation", FilterMatchMode::Regex).matches(&data));
    }
}
