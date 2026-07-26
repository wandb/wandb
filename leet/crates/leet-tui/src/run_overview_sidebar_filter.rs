//! Port of `core/internal/leet/runoverviewsidebarfilter.go` — filter key
//! handling and per-section match bookkeeping for
//! [`RunOverviewSidebar`](crate::run_overview_sidebar::RunOverviewSidebar).
//!
//! The [`crate::filter::Filter`] widget owns the draft/applied state
//! machine; text matching goes through
//! `leet_data::run_filter_query::compile_text_matcher` (see the DIVERGENCE
//! note in `crate::filter`).

use leet_data::run_overview::KeyValuePair;

use crate::filter::FilterMatchMode;
use crate::key::KeyEvent;
use crate::run_overview_sidebar::RunOverviewSidebar;

impl RunOverviewSidebar {
    /// HandleFilterKey processes a key event while the overview filter is
    /// active.
    // PHASE-5: called from the run/workspace key handlers
    // (runhandlers.go:292, workspacehandlers.go:69).
    #[allow(dead_code)]
    pub fn handle_filter_key(&mut self, msg: &KeyEvent) {
        if self.filter.handle_key(msg) {
            self.apply_filter();
            self.update_section_heights();
        }
    }

    /// EnterFilterMode activates filter mode (draft initialized from
    /// applied).
    pub fn enter_filter_mode(&mut self) {
        self.filter.activate();
    }

    /// UpdateFilterDraft updates the in‑progress filter text (for live
    /// preview).
    pub fn update_filter_draft(&mut self, msg: &KeyEvent) {
        self.filter.update_draft(msg);
    }

    /// ExitFilterMode exits filter input mode and optionally applies the
    /// filter.
    pub fn exit_filter_mode(&mut self, apply: bool) {
        if apply {
            self.filter.commit();
        } else {
            self.filter.cancel();
        }
        self.apply_filter();
        self.update_section_heights();
    }

    /// ClearFilter removes any applied/draft filter and restores all items.
    pub fn clear_filter(&mut self) {
        self.filter.clear();
        self.apply_filter();
        self.update_section_heights();
    }

    /// ToggleFilterMatchMode flips regex <-> glob and reapplies the live
    /// preview.
    pub fn toggle_filter_match_mode(&mut self) {
        self.filter.toggle_mode();
        self.apply_filter();
        self.update_section_heights();
    }

    /// IsFilterMode reports whether we are currently typing a filter.
    pub fn is_filter_mode(&self) -> bool {
        self.filter.is_active()
    }

    /// FilterMode exposes the current filter match mode.
    // PHASE-5: read by the status bars (workspace.go:1185, run view).
    #[allow(dead_code)]
    pub fn filter_mode(&self) -> FilterMatchMode {
        self.filter.mode()
    }

    /// FilterQuery returns the currently effective query (applied if set,
    /// else draft).
    pub fn filter_query(&self) -> &str {
        self.filter.query()
    }

    /// IsFiltering returns true if an applied (non‑empty) filter exists.
    pub fn is_filtering(&self) -> bool {
        !self.filter.is_active() && !self.filter.query().is_empty()
    }

    /// ApplyFilter recomputes FilteredItems for each section based on the
    /// current matcher.
    /// Also auto‑focuses the section with most matches while the query is
    /// non‑empty.
    pub fn apply_filter(&mut self) {
        let matcher = self.filter.matcher();

        for i in 0..self.sections.len() {
            // fresh slice so there's no aliasing with Items
            let mut filtered: Vec<KeyValuePair> = Vec::with_capacity(self.sections[i].items.len());
            for it in &self.sections[i].items {
                // Match on either key or value.
                if matcher(&it.key) || matcher(&it.value) {
                    filtered.push(it.clone());
                }
            }
            self.sections[i].filtered_items = filtered;
            self.sections[i].home();
        }

        // While query is non‑empty (draft or applied), drive focus to the
        // best section.
        if !self.filter.query().is_empty() {
            self.focus_best_match_section();
        }
    }

    /// focusBestMatchSection focuses the section that has the most filter
    /// matches. Ties are resolved by keeping the current active section.
    /// No-ops if no section has matches.
    fn focus_best_match_section(&mut self) {
        let mut best = self.active_section;
        let mut maximum = 0;

        for (i, section) in self.sections.iter().enumerate() {
            let m = section.filtered_items.len();
            if m > maximum {
                maximum = m;
                best = i as isize;
            }
        }

        if maximum == 0 || best == self.active_section {
            return;
        }
        self.set_active_section(best); // centralizes deactivation + cursor/page reset
    }

    /// FilterInfo returns a compact, human‑readable per‑section match
    /// summary for the status bar.
    pub fn filter_info(&self) -> String {
        // Only show during input or with an active filter.
        if !self.is_filter_mode() && self.filter_query().is_empty() {
            return String::new();
        }

        let mut parts: Vec<String> = Vec::new();
        for sec in &self.sections {
            let filter_matches = sec.filtered_items.len();
            if filter_matches == 0 {
                continue;
            }

            let mut title = sec.title.as_str();
            if title == "Environment" {
                title = "Env";
            }
            parts.push(format!("{title}: {filter_matches}"));
        }
        if parts.is_empty() {
            return "no matches".to_string();
        }
        parts.join(", ")
    }
}
