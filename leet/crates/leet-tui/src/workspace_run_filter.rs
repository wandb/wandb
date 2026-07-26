//! Port of `core/internal/leet/workspacerunfilter.go` — runs-sidebar filter
//! key handling and live preview.
//!
//! In Go every function here is a `*Workspace` method. The `Workspace` model
//! (workspace.go) is not ported yet, so the file's Workspace surface is a
//! seam trait: [`WorkspaceRunFilterHost`] requires accessors for the fields
//! this file touches (workspace.go:37-64) plus the `Workspace` methods
//! defined in other files, and hosts the 1:1 port of this file's methods as
//! provided methods. Phase 5's `Workspace` implements the required items and
//! inherits the ports unchanged.

use std::borrow::Cow;
use std::collections::{HashMap, HashSet};

use leet_charts::styles::MEDIUM_SHADE_BLOCK;
use leet_data::run_filter_query::{
    RunFilterConfigEntry, WorkspaceRunFilterData, compile_run_filter_query,
};
use leet_proto::wandb_internal::ConfigRecord;

use crate::animation::AnimatedValue;
use crate::event::RunMsg;
use crate::filter::Filter;
use crate::key::KeyEvent;
use crate::paged_list::PagedList;

/// The `*Workspace` receiver surface used by workspacerunfilter.go.
///
/// Required items are the seam; provided methods are the mechanical port.
pub trait WorkspaceRunFilterHost {
    /// Go `tea.Cmd` returned by workspace key handlers.
    // PHASE-5: becomes the app-shell `Command` type (CONCURRENCY.md §2.7)
    // once model.rs lands.
    type Cmd;

    // --- Workspace fields (workspace.go:37-64) ---

    /// Go `w.filter` — drives the runs sidebar search box (workspace.go:61).
    fn filter(&self) -> &Filter;
    fn filter_mut(&mut self) -> &mut Filter;

    /// Go `w.runs` — the run selector (workspace.go:40).
    fn runs(&self) -> &PagedList;
    fn runs_mut(&mut self) -> &mut PagedList;

    /// Go `w.runsAnimState` (workspace.go:37).
    fn runs_anim_state(&self) -> &AnimatedValue;

    /// Go `w.runsFilterIndex` — caches searchable per-run metadata (name,
    /// project, config) for the runs sidebar so metadata filtering stays fast
    /// during live preview (workspace.go:62-64).
    fn runs_filter_index(&self) -> &HashMap<String, WorkspaceRunFilterData>;
    fn runs_filter_index_mut(&mut self) -> &mut HashMap<String, WorkspaceRunFilterData>;

    // --- Workspace methods defined outside this file ---

    /// Go `w.handleToggleRunsSidebar(msg)`.
    // PHASE-5: `Workspace::handle_toggle_runs_sidebar`
    // (workspacehandlers.go:344) — not ported yet.
    fn handle_toggle_runs_sidebar(&mut self, msg: &KeyEvent) -> Option<Self::Cmd>;

    /// Go `w.consoleLogsPane.SetActive(active)`.
    // PHASE-5: forwards to `ConsoleLogsPane::set_active`
    // (consolelogspane.go:115) — the pane is not ported yet
    // (console_logs_pane.rs).
    fn set_console_logs_pane_active(&mut self, active: bool);

    /// Go `w.runOverviewSidebar.deactivateAllSections()`.
    // PHASE-5: forwards to `RunOverviewSidebar::deactivate_all_sections`
    // (runoverviewsidebarnav.go:340) — the sidebar is not ported yet
    // (run_overview_sidebar_nav.rs).
    fn deactivate_all_run_overview_sections(&mut self);

    /// Go `w.restoreRunCursor(runKey)`.
    // PHASE-5: `Workspace::restore_run_cursor` (workspacedirwatcher.go:389)
    // — not ported yet.
    fn restore_run_cursor(&mut self, run_key: &str);

    /// Go `w.syncRunsPage()`.
    // PHASE-5: `Workspace::sync_runs_page` (workspace.go:1315). Go returns
    // `(startIdx, endIdx int)`, discarded at this file's only call site
    // (workspacerunfilter.go:86), so the seam returns nothing.
    fn sync_runs_page(&mut self);

    // --- workspacerunfilter.go methods (the port) ---

    /// handleRunFilterKey updates the runs filter draft and reapplies it for
    /// live preview while the editor is active.
    fn handle_run_filter_key(&mut self, msg: &KeyEvent) {
        if self.filter_mut().handle_key(msg) {
            self.apply_run_filter();
        }
    }

    /// handleEnterRunsFilter focuses the runs sidebar and enters runs filter
    /// input mode. If the sidebar is currently collapsed, it is expanded
    /// first.
    fn handle_enter_runs_filter(&mut self, msg: &KeyEvent) -> Option<Self::Cmd> {
        let mut cmd = None;
        if !self.runs_anim_state().is_expanded() && !self.runs_anim_state().is_animating() {
            cmd = self.handle_toggle_runs_sidebar(msg);
        }

        self.runs_mut().active = true;
        self.set_console_logs_pane_active(false);
        self.deactivate_all_run_overview_sections();
        self.filter_mut().activate();
        self.apply_run_filter();

        cmd
    }

    /// handleClearRunsFilter clears the applied runs filter and exits filter
    /// mode.
    fn handle_clear_runs_filter(&mut self, _msg: &KeyEvent) -> Option<Self::Cmd> {
        if self.filter().query().is_empty() && !self.filter().is_active() {
            return None;
        }
        self.filter_mut().clear();
        self.apply_run_filter();
        None
    }

    /// buildRunsFilterStatus returns the status bar prompt for the runs
    /// filter.
    fn build_runs_filter_status(&self) -> String {
        format!(
            "Runs filter ({}): {}{} [{}/{}] (Enter to apply • Tab to toggle mode)",
            self.filter().mode(),
            self.filter().query(),
            MEDIUM_SHADE_BLOCK,
            self.runs().filtered_items.len(),
            self.runs().items.len(),
        )
    }

    /// applyRunFilter reevaluates the runs sidebar against the current filter
    /// query. It preserves the cursor when the previously focused run remains
    /// visible.
    fn apply_run_filter(&mut self) {
        let mut prev_cursor_key = String::new();
        if let Some(cur) = self.runs().current_item() {
            prev_cursor_key = cur.key.clone();
        }

        let query = self.filter().query().to_owned();
        if query.is_empty() {
            // PARITY: Go aliases the Items slice (`FilteredItems = Items`);
            // cloned at the boundary (PORTING.md append-aliasing rule) —
            // both slices are only ever reassigned wholesale, never mutated
            // in place, so aliasing is unobservable.
            let items = self.runs().items.clone();
            self.runs_mut().filtered_items = items;
        } else {
            let compiled = compile_run_filter_query(&query, self.filter().mode());
            let mut filtered = Vec::with_capacity(self.runs().items.len());
            for item in &self.runs().items {
                if compiled.matches(&self.run_filter_data(&item.key)) {
                    filtered.push(item.clone());
                }
            }
            self.runs_mut().filtered_items = filtered;
        }

        if !prev_cursor_key.is_empty() {
            self.restore_run_cursor(&prev_cursor_key);
        }
        self.sync_runs_page();
    }

    /// runFilterData returns indexed filter metadata for runKey.
    ///
    /// If the run has not been preloaded yet, it falls back to the run key so
    /// name-based filtering still works before richer metadata arrives.
    // PARITY: Go returns a shallow struct copy — the map/slice headers are
    // shared with the index entry, O(1) per run. A naive `.clone()` here would
    // deep-copy every flattened config entry per run per live-preview
    // keystroke, so indexed entries are borrowed (`Cow::Borrowed`) and only
    // the un-indexed fallback is constructed.
    fn run_filter_data(&self, run_key: &str) -> Cow<'_, WorkspaceRunFilterData> {
        if let Some(data) = self.runs_filter_index().get(run_key) {
            return Cow::Borrowed(data);
        }
        Cow::Owned(WorkspaceRunFilterData {
            run_key: run_key.to_owned(),
            ..WorkspaceRunFilterData::default()
        })
    }

    /// indexRunFilterData caches searchable metadata derived from a RunMsg.
    ///
    /// Run preload and streaming can deliver partial records, so missing
    /// fields keep the previously indexed value instead of clobbering it.
    fn index_run_filter_data(&mut self, run_key: &str, msg: &RunMsg) {
        let mut data = build_workspace_run_filter_data(run_key, msg);
        if let Some(existing) = self.runs_filter_index().get(run_key) {
            if data.display_name.is_empty() {
                data.display_name = existing.display_name.clone();
            }
            if data.id.is_empty() {
                data.id = existing.id.clone();
            }
            if data.project.is_empty() {
                data.project = existing.project.clone();
            }
            if data.notes.is_empty() {
                data.notes = existing.notes.clone();
            }
            if data.tags.is_empty() && !existing.tags.is_empty() {
                data.tags = existing.tags.clone();
            }
            if data.config_entries.is_empty() && !existing.config_entries.is_empty() {
                data.config_by_path = existing.config_by_path.clone();
                data.config_entries = existing.config_entries.clone();
            }
        }
        self.runs_filter_index_mut()
            .insert(run_key.to_owned(), data);
    }
}

/// buildWorkspaceRunFilterData converts a RunMsg into the indexed metadata
/// used by the runs filter.
pub fn build_workspace_run_filter_data(run_key: &str, msg: &RunMsg) -> WorkspaceRunFilterData {
    let (config_by_path, config_entries) = flatten_run_filter_config(msg.config.as_deref());
    // PARITY: Go replaces a nil configByPath with a fresh empty map; the Rust
    // flatten already returns an empty (writable) map for the nil record.
    WorkspaceRunFilterData {
        run_key: run_key.to_owned(),
        display_name: msg.display_name.clone(),
        id: msg.id.clone(),
        project: msg.project.clone(),
        notes: msg.notes.trim().to_owned(),
        tags: normalize_run_filter_tags(&msg.tags),
        config_by_path,
        config_entries,
    }
}

fn normalize_run_filter_tags(tags: &[String]) -> Vec<String> {
    if tags.is_empty() {
        // PARITY: Go returns nil; an empty Vec reads identically.
        return Vec::new();
    }

    let mut seen: HashSet<String> = HashSet::with_capacity(tags.len());
    let mut out: Vec<String> = Vec::with_capacity(tags.len());
    for tag in tags {
        let tag = tag.trim();
        if tag.is_empty() {
            continue;
        }
        if seen.insert(tag.to_owned()) {
            out.push(tag.to_owned());
        }
    }

    // PARITY: Go returns nil when everything was trimmed away; empty Vec.
    out
}

/// flattenRunFilterConfig flattens a ConfigRecord into canonicalized
/// path/value pairs plus a sorted entry list for broad config searches.
pub fn flatten_run_filter_config(
    cfg: Option<&ConfigRecord>,
) -> (HashMap<String, String>, Vec<RunFilterConfigEntry>) {
    // PARITY: Go returns (nil, nil); empty map/vec read identically.
    let Some(cfg) = cfg else {
        return (HashMap::new(), Vec::new());
    };

    let mut flat: HashMap<String, String> = HashMap::new();
    for item in &cfg.update {
        // PARITY: Go skips nil items; prost repeated message fields hold
        // values, never nil, so the check vanishes.

        let mut path = item.nested_key.join(".");
        if path.is_empty() {
            path = item.key.clone();
        }
        let path = path.trim();
        if path.is_empty() {
            continue;
        }

        let raw = item.value_json.trim();
        if raw.is_empty() {
            flat.insert(canonical_run_filter_path(path), String::new());
            continue;
        }

        // PARITY: Go json.Unmarshal decodes every JSON number to float64;
        // flatten_run_filter_value mirrors that by rendering serde numbers
        // through their f64 value.
        let value = match serde_json::from_str::<serde_json::Value>(raw) {
            Ok(value) => value,
            Err(_) => serde_json::Value::String(trim_run_filter_raw_json_value(raw).to_owned()),
        };
        flatten_run_filter_value(path, &value, &mut flat);
    }

    let mut keys: Vec<String> = Vec::with_capacity(flat.len());
    for path in flat.keys() {
        keys.push(path.clone());
    }
    keys.sort();

    let mut entries: Vec<RunFilterConfigEntry> = Vec::with_capacity(keys.len());
    for path in keys {
        let value = flat[&path].clone();
        entries.push(RunFilterConfigEntry { path, value });
    }

    (flat, entries)
}

/// flattenRunFilterValue recursively expands JSON-like config values into
/// canonical path/value pairs.
fn flatten_run_filter_value(
    prefix: &str,
    value: &serde_json::Value,
    out: &mut HashMap<String, String>,
) {
    match value {
        serde_json::Value::Object(v) => {
            // PARITY: Go sorts the map keys before recursing (map iteration
            // order is random); explicit sort keeps the same order regardless
            // of serde_json's map backend.
            let mut keys: Vec<&String> = v.keys().collect();
            keys.sort();
            for key in keys {
                flatten_run_filter_value(&format!("{prefix}.{key}"), &v[key.as_str()], out);
            }
        }
        serde_json::Value::Array(v) => {
            for (i, elem) in v.iter().enumerate() {
                flatten_run_filter_value(&format!("{prefix}[{i}]"), elem, out);
            }
        }
        serde_json::Value::Null => {
            out.insert(canonical_run_filter_path(prefix), "null".to_owned());
        }
        // Go `default:` → `fmt.Sprint(v)`. After json.Unmarshal the remaining
        // kinds are exactly bool, float64 and string.
        serde_json::Value::Bool(v) => {
            out.insert(canonical_run_filter_path(prefix), v.to_string());
        }
        serde_json::Value::Number(v) => {
            out.insert(
                canonical_run_filter_path(prefix),
                go_sprint_f64(v.as_f64().unwrap_or(f64::NAN)),
            );
        }
        serde_json::Value::String(v) => {
            out.insert(canonical_run_filter_path(prefix), v.clone());
        }
    }
}

/// trimRunFilterRawJSONValue removes surrounding JSON string quotes from a
/// raw config value when structured decoding is unavailable.
fn trim_run_filter_raw_json_value(raw: &str) -> &str {
    let raw = raw.trim();
    let bytes = raw.as_bytes();
    if bytes.len() >= 2 && bytes[0] == b'"' && bytes[bytes.len() - 1] == b'"' {
        // PARITY: Go slices bytes; both quote bytes are one-byte UTF-8
        // sequences, so the slice always lands on char boundaries.
        return &raw[1..raw.len() - 1];
    }
    raw
}

/// canonicalRunFilterPath normalizes config paths for case-insensitive
/// lookup.
// PARITY: duplicates the private `canonical_run_filter_path` in
// `leet_data::run_filter_query` (runfilterquery.go:587-590 lives in that
// module's Go source); it is not exported from leet-data, so the one-liner is
// repeated here with the same go_to_lower shim semantics (per-char
// `char::to_lowercase`, see the PARITY note on the shim). PHASE-5: consolidate
// by exporting the leet-data helper.
fn canonical_run_filter_path(path: &str) -> String {
    path.trim().chars().flat_map(char::to_lowercase).collect()
}

/// Go `fmt.Sprint(v)` for a float64, i.e.
/// `strconv.FormatFloat(v, 'g', -1, 64)`: shortest round-trip digits, %e form
/// when the decimal exponent is < -4 or >= 6 (internal/strconv/ftoa.go
/// `formatDigits`, shortest eprec = 6).
// PARITY: `leet_data::go_fmt::format_float_g` requires prec >= 1 and cannot
// express Go's shortest (-1) mode, so the shortest-'g' renderer lives here.
// The rendering shape mirrors format_float_g's fixed/scientific branches.
#[allow(clippy::manual_range_contains)] // keep Go's `exp < -4 || exp >= eprec` shape
fn go_sprint_f64(v: f64) -> String {
    if v.is_nan() {
        return "NaN".to_owned();
    }
    if v.is_infinite() {
        return if v > 0.0 { "+Inf" } else { "-Inf" }.to_owned();
    }
    if v == 0.0 {
        return if v.is_sign_negative() { "-0" } else { "0" }.to_owned();
    }

    let neg = v < 0.0;
    let abs = v.abs();

    // Rust `{:e}` with no precision prints the shortest round-trip mantissa —
    // the same (unique) digit string Go's shortest conversion produces.
    let sci = format!("{abs:e}"); // e.g. "1.23e3", "1e0", "1.5e-7"
    let (mantissa, exp) = sci
        .split_once('e')
        .expect("LowerExp always emits an exponent");
    let exp10: i32 = exp.parse().expect("LowerExp exponent is an integer");
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();

    let mut out = String::new();
    if neg {
        out.push('-');
    }

    if exp10 < -4 || exp10 >= 6 {
        // fmtE: d[.ddd]e±dd — sign always, at least two exponent digits.
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        if exp10 < 0 {
            out.push('-');
        } else {
            out.push('+');
        }
        let e = exp10.unsigned_abs();
        if e < 10 {
            out.push('0');
        }
        out.push_str(&e.to_string());
    } else if exp10 >= 0 {
        // Fixed with the decimal point inside/after the digit string.
        let int_len = (exp10 + 1) as usize;
        if digits.len() <= int_len {
            out.push_str(&digits);
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
        for _ in 0..(-exp10 - 1) {
            out.push('0');
        }
        out.push_str(&digits);
    }
    out
}

#[cfg(test)]
mod tests {
    use leet_data::run_overview::KeyValuePair;
    use leet_proto::wandb_internal::ConfigItem;
    use pretty_assertions::assert_eq;

    use crate::key::{KeyCode, KeyMods};

    use super::*;

    // Go has no workspacerunfilter_test.go; every test below is Rust-only
    // coverage pinning the port against Go behavior (fmt.Sprint outputs were
    // captured from a Go oracle run).

    fn text_key(text: &str) -> KeyEvent {
        KeyEvent {
            code: KeyCode::Char(text.chars().next().expect("non-empty text")),
            text: Some(text.to_string()),
            mods: KeyMods::NONE,
        }
    }

    fn code_key(code: KeyCode) -> KeyEvent {
        KeyEvent {
            code,
            text: None,
            mods: KeyMods::NONE,
        }
    }

    fn config_item(key: &str, nested: &[&str], value_json: &str) -> ConfigItem {
        ConfigItem {
            key: key.to_owned(),
            nested_key: nested.iter().map(|s| (*s).to_owned()).collect(),
            value_json: value_json.to_owned(),
        }
    }

    /// Minimal Workspace stand-in implementing the seam's required items.
    #[derive(Default)]
    struct MockWorkspace {
        filter: Filter,
        runs: PagedList,
        runs_anim_state: Option<AnimatedValue>,
        runs_filter_index: HashMap<String, WorkspaceRunFilterData>,

        toggle_calls: usize,
        console_logs_active: Option<bool>,
        deactivate_sections_calls: usize,
        restored_cursors: Vec<String>,
        sync_runs_page_calls: usize,
    }

    impl MockWorkspace {
        fn new(expanded: bool) -> Self {
            let mut w = MockWorkspace {
                runs_anim_state: Some(AnimatedValue::new(expanded, 30)),
                ..MockWorkspace::default()
            };
            w.runs.items = vec![
                KeyValuePair {
                    key: "run-alpha".to_owned(),
                    ..KeyValuePair::default()
                },
                KeyValuePair {
                    key: "run-beta".to_owned(),
                    ..KeyValuePair::default()
                },
                KeyValuePair {
                    key: "run-gamma".to_owned(),
                    ..KeyValuePair::default()
                },
            ];
            w.runs.filtered_items = w.runs.items.clone();
            w.runs.set_items_per_page(10);
            w
        }
    }

    impl WorkspaceRunFilterHost for MockWorkspace {
        type Cmd = &'static str;

        fn filter(&self) -> &Filter {
            &self.filter
        }
        fn filter_mut(&mut self) -> &mut Filter {
            &mut self.filter
        }
        fn runs(&self) -> &PagedList {
            &self.runs
        }
        fn runs_mut(&mut self) -> &mut PagedList {
            &mut self.runs
        }
        fn runs_anim_state(&self) -> &AnimatedValue {
            self.runs_anim_state.as_ref().expect("anim state set")
        }
        fn runs_filter_index(&self) -> &HashMap<String, WorkspaceRunFilterData> {
            &self.runs_filter_index
        }
        fn runs_filter_index_mut(&mut self) -> &mut HashMap<String, WorkspaceRunFilterData> {
            &mut self.runs_filter_index
        }

        fn handle_toggle_runs_sidebar(&mut self, _msg: &KeyEvent) -> Option<Self::Cmd> {
            self.toggle_calls += 1;
            Some("toggle-runs-sidebar")
        }
        fn set_console_logs_pane_active(&mut self, active: bool) {
            self.console_logs_active = Some(active);
        }
        fn deactivate_all_run_overview_sections(&mut self) {
            self.deactivate_sections_calls += 1;
        }
        fn restore_run_cursor(&mut self, run_key: &str) {
            self.restored_cursors.push(run_key.to_owned());
        }
        fn sync_runs_page(&mut self) {
            self.sync_runs_page_calls += 1;
        }
    }

    #[test]
    fn handle_run_filter_key_reapplies_on_change_and_ignores_nav_keys() {
        let mut w = MockWorkspace::new(true);
        w.filter.activate();

        w.handle_run_filter_key(&text_key("b"));
        assert_eq!(w.filter.query(), "b");
        assert_eq!(w.sync_runs_page_calls, 1);
        assert_eq!(
            w.runs
                .filtered_items
                .iter()
                .map(|i| i.key.as_str())
                .collect::<Vec<_>>(),
            vec!["run-beta"],
        );

        // A navigation key does not change filter state: no reapply.
        w.handle_run_filter_key(&code_key(KeyCode::Up));
        assert_eq!(w.sync_runs_page_calls, 1);
    }

    #[test]
    fn handle_enter_runs_filter_expands_collapsed_sidebar_first() {
        let mut w = MockWorkspace::new(false);

        let cmd = w.handle_enter_runs_filter(&code_key(KeyCode::Enter));
        assert_eq!(cmd, Some("toggle-runs-sidebar"));
        assert_eq!(w.toggle_calls, 1);
        assert!(w.runs.active);
        assert_eq!(w.console_logs_active, Some(false));
        assert_eq!(w.deactivate_sections_calls, 1);
        assert!(w.filter.is_active());
        assert_eq!(w.sync_runs_page_calls, 1);
    }

    #[test]
    fn handle_enter_runs_filter_skips_toggle_when_expanded() {
        let mut w = MockWorkspace::new(true);

        let cmd = w.handle_enter_runs_filter(&code_key(KeyCode::Enter));
        assert_eq!(cmd, None);
        assert_eq!(w.toggle_calls, 0);
        assert!(w.filter.is_active());
    }

    #[test]
    fn handle_clear_runs_filter_is_noop_when_empty_and_inactive() {
        let mut w = MockWorkspace::new(true);

        assert_eq!(w.handle_clear_runs_filter(&code_key(KeyCode::Esc)), None);
        assert_eq!(w.sync_runs_page_calls, 0);
    }

    #[test]
    fn handle_clear_runs_filter_clears_and_reapplies() {
        let mut w = MockWorkspace::new(true);
        w.filter.activate();
        w.filter.handle_key(&text_key("beta"));
        w.apply_run_filter();
        assert_eq!(w.runs.filtered_items.len(), 1);

        assert_eq!(w.handle_clear_runs_filter(&code_key(KeyCode::Esc)), None);
        assert!(!w.filter.is_active());
        assert_eq!(w.filter.query(), "");
        assert_eq!(w.runs.filtered_items.len(), 3);
    }

    #[test]
    fn build_runs_filter_status_formats_like_go() {
        let mut w = MockWorkspace::new(true);
        w.filter.activate();
        w.filter.handle_key(&text_key("beta"));
        w.apply_run_filter();

        assert_eq!(
            w.build_runs_filter_status(),
            "Runs filter (regex): beta\u{2592} [1/3] (Enter to apply \u{2022} Tab to toggle mode)",
        );
    }

    #[test]
    fn apply_run_filter_preserves_cursor_and_uses_index_metadata() {
        let mut w = MockWorkspace::new(true);
        // Cursor on "run-beta" (page 0, line 1).
        w.runs.set_page_and_line(0, 1);
        assert_eq!(
            w.runs.current_item().map(|i| i.key.clone()),
            Some("run-beta".to_owned())
        );

        // Index metadata so "run-alpha" matches by display name.
        w.index_run_filter_data(
            "run-alpha",
            &RunMsg {
                display_name: "sunny-morning-7".to_owned(),
                ..RunMsg::default()
            },
        );

        w.filter.activate();
        for ch in ["s", "u", "n", "n", "y"] {
            w.filter.handle_key(&text_key(ch));
        }
        w.apply_run_filter();

        assert_eq!(
            w.runs
                .filtered_items
                .iter()
                .map(|i| i.key.as_str())
                .collect::<Vec<_>>(),
            vec!["run-alpha"],
        );
        assert_eq!(w.restored_cursors, vec!["run-beta".to_owned()]);
        assert_eq!(w.sync_runs_page_calls, 1);
    }

    #[test]
    fn apply_run_filter_empty_query_shows_all_items() {
        let mut w = MockWorkspace::new(true);
        w.runs.filtered_items.clear();

        w.apply_run_filter();
        assert_eq!(w.runs.filtered_items.len(), 3);
        // Empty prev cursor (no navigable filtered items) → no restore.
        assert!(w.restored_cursors.is_empty());
        assert_eq!(w.sync_runs_page_calls, 1);
    }

    #[test]
    fn run_filter_data_falls_back_to_run_key() {
        let w = MockWorkspace::new(true);
        let data = w.run_filter_data("not-preloaded");
        assert!(
            matches!(data, Cow::Owned(_)),
            "un-indexed key must build the owned fallback",
        );
        assert_eq!(
            *data,
            WorkspaceRunFilterData {
                run_key: "not-preloaded".to_owned(),
                ..WorkspaceRunFilterData::default()
            },
        );
    }

    #[test]
    fn run_filter_data_borrows_indexed_entries() {
        let mut w = MockWorkspace::new(true);
        w.index_run_filter_data(
            "run-alpha",
            &RunMsg {
                display_name: "sunny-morning-7".to_owned(),
                ..RunMsg::default()
            },
        );

        // Indexed entries are returned by reference (Go's shallow struct
        // copy), never deep-cloned per lookup.
        let data = w.run_filter_data("run-alpha");
        assert!(matches!(data, Cow::Borrowed(_)));
        assert_eq!(data.display_name, "sunny-morning-7");
    }

    #[test]
    fn index_run_filter_data_keeps_existing_fields_on_partial_update() {
        let mut w = MockWorkspace::new(true);
        w.index_run_filter_data(
            "run-alpha",
            &RunMsg {
                display_name: "sunny-morning-7".to_owned(),
                id: "abc123".to_owned(),
                project: "proj".to_owned(),
                notes: "  first note  ".to_owned(),
                tags: vec!["a".to_owned(), "b".to_owned()],
                config: Some(Box::new(ConfigRecord {
                    update: vec![config_item("LR", &[], "0.1")],
                    ..ConfigRecord::default()
                })),
                ..RunMsg::default()
            },
        );

        // Partial record: only the display name is set; everything else must
        // survive from the previous index entry.
        w.index_run_filter_data(
            "run-alpha",
            &RunMsg {
                display_name: "renamed-run".to_owned(),
                ..RunMsg::default()
            },
        );

        let data = &w.runs_filter_index["run-alpha"];
        assert_eq!(data.display_name, "renamed-run");
        assert_eq!(data.id, "abc123");
        assert_eq!(data.project, "proj");
        assert_eq!(data.notes, "first note");
        assert_eq!(data.tags, vec!["a".to_owned(), "b".to_owned()]);
        assert_eq!(data.config_by_path["lr"], "0.1");
        assert_eq!(
            data.config_entries,
            vec![RunFilterConfigEntry {
                path: "lr".to_owned(),
                value: "0.1".to_owned(),
            }],
        );
    }

    #[test]
    fn build_workspace_run_filter_data_trims_notes_and_normalizes_tags() {
        let data = build_workspace_run_filter_data(
            "rk",
            &RunMsg {
                display_name: "name".to_owned(),
                notes: " \t hello \n".to_owned(),
                tags: vec![
                    "  a ".to_owned(),
                    "".to_owned(),
                    "b".to_owned(),
                    "a".to_owned(),
                    "   ".to_owned(),
                ],
                ..RunMsg::default()
            },
        );
        assert_eq!(data.run_key, "rk");
        assert_eq!(data.notes, "hello");
        assert_eq!(data.tags, vec!["a".to_owned(), "b".to_owned()]);
        // No config record → empty (Go: nil replaced with empty map).
        assert!(data.config_by_path.is_empty());
        assert!(data.config_entries.is_empty());
    }

    #[test]
    fn flatten_run_filter_config_flattens_and_sorts() {
        let cfg = ConfigRecord {
            update: vec![
                config_item("", &["Optimizer", "LR"], "0.001"),
                config_item("Model", &[], r#"{"Depth": 12, "Heads": [4, 8]}"#),
                config_item("note", &[], r#""hi there""#),
                config_item("flag", &[], "true"),
                config_item("none", &[], "null"),
                config_item("empty", &[], "   "),
                config_item("bad", &[], r#""a" "b""#),
                config_item("worse", &[], r#""unterminated"#),
                config_item("  ", &[], "1"), // blank path skipped
            ],
            ..ConfigRecord::default()
        };

        let (flat, entries) = flatten_run_filter_config(Some(&cfg));

        assert_eq!(flat["optimizer.lr"], "0.001");
        assert_eq!(flat["model.depth"], "12");
        assert_eq!(flat["model.heads[0]"], "4");
        assert_eq!(flat["model.heads[1]"], "8");
        assert_eq!(flat["note"], "hi there");
        assert_eq!(flat["flag"], "true");
        assert_eq!(flat["none"], "null");
        assert_eq!(flat["empty"], "");
        // Invalid JSON falls back to the quote-trimmed raw text (Go oracle:
        // `"a" "b"` → `a" "b`; `"unterminated` has no closing quote and is
        // kept verbatim).
        assert_eq!(flat["bad"], r#"a" "b"#);
        assert_eq!(flat["worse"], r#""unterminated"#);

        let paths: Vec<&str> = entries.iter().map(|e| e.path.as_str()).collect();
        assert_eq!(
            paths,
            vec![
                "bad",
                "empty",
                "flag",
                "model.depth",
                "model.heads[0]",
                "model.heads[1]",
                "none",
                "note",
                "optimizer.lr",
                "worse",
            ],
        );

        // Nil record → (nil, nil) in Go, empty here.
        let (flat, entries) = flatten_run_filter_config(None);
        assert!(flat.is_empty());
        assert!(entries.is_empty());
    }

    #[test]
    fn flatten_run_filter_value_sorts_object_keys() {
        let value: serde_json::Value =
            serde_json::from_str(r#"{"b": {"y": 1, "x": 2}, "a": 3}"#).expect("valid JSON");
        let mut out = HashMap::new();
        flatten_run_filter_value("Root", &value, &mut out);

        let mut keys: Vec<&String> = out.keys().collect();
        keys.sort();
        assert_eq!(keys, vec!["root.a", "root.b.x", "root.b.y"]);
        assert_eq!(out["root.a"], "3");
        assert_eq!(out["root.b.x"], "2");
        assert_eq!(out["root.b.y"], "1");
    }

    #[test]
    fn trim_run_filter_raw_json_value_strips_surrounding_quotes() {
        assert_eq!(trim_run_filter_raw_json_value(r#" "abc" "#), "abc");
        assert_eq!(trim_run_filter_raw_json_value(r#""""#), "");
        assert_eq!(trim_run_filter_raw_json_value(r#"""#), r#"""#);
        assert_eq!(trim_run_filter_raw_json_value("plain"), "plain");
    }

    // Expected strings captured from a Go oracle:
    // `fmt.Sprint(v)` after `json.Unmarshal` of the literal (go1.26).
    #[test]
    fn go_sprint_f64_matches_go_oracle() {
        let cases: &[(f64, &str)] = &[
            (3.0, "3"),
            (3.5, "3.5"),
            (0.1, "0.1"),
            (1e20, "1e+20"),
            (1e21, "1e+21"),
            (1e-4, "0.0001"),
            (1e-5, "1e-05"),
            (1.2345678901234568e20, "1.2345678901234568e+20"),
            (2.5e-10, "2.5e-10"),
            (1234567.25, "1.23456725e+06"),
            (1e100, "1e+100"),
            (-3.75, "-3.75"),
            (1e6, "1e+06"),
            (999999.5, "999999.5"),
            (950000.0, "950000"),
            (123456.75, "123456.75"),
            (100000.5, "100000.5"),
            (0.0, "0"),
            (-0.0, "-0"),
        ];
        for &(v, want) in cases {
            assert_eq!(go_sprint_f64(v), want, "value {v:?}");
        }
    }
}
