//! Port of `core/internal/leet/filter.go` — the shared filter widget state
//! machine (draft/applied pattern, input mode, regex/glob toggle).
//!
//! DIVERGENCE (PORTING.md module mapping, PARITY.md §2.8): the pure
//! text-matching subset of filter.go — `FilterMatchMode`, `compileTextMatcher`,
//! `globMatchUnanchoredCaseInsensitive`, `wildcardMatch`, `hasRegexMeta`
//! (filter.go:11-29, 168-267) — is hosted in `leet_data::run_filter_query`
//! (its `runfilterquery.go` port calls `compileTextMatcher`, and `leet-tui`
//! depends on `leet-data`, not vice versa). It is re-exported here and MUST
//! NOT be re-ported. This module carries only the `Filter` widget and its key
//! handling.

use crate::key::{KeyCode, KeyEvent};

// Re-export the matcher subset so leet-tui call sites keep filter.go's
// single-file surface (`filter::FilterMatchMode`, `filter::compile_text_matcher`).
pub use leet_data::run_filter_query::{FilterMatchMode, TextMatcher, compile_text_matcher};

/// Filter tracks the filter state.
///
/// Used for filtering run overview items and metric charts.
#[derive(Debug, Clone)]
pub struct Filter {
    input_active: bool,    // filter input mode
    draft: String,         // what the user is typing (preview)
    applied: String,       // committed pattern
    mode: FilterMatchMode, // current match mode
}

impl Filter {
    /// Port of `NewFilter`.
    pub fn new() -> Filter {
        Filter {
            input_active: false,
            draft: String::new(),
            applied: String::new(),
            mode: FilterMatchMode::Regex,
        }
    }

    /// Activate enters input mode, initializing the draft with the current
    /// applied pattern.
    pub fn activate(&mut self) {
        self.input_active = true;
        self.draft = self.applied.clone();
    }

    /// Commit applies the current draft and exits input mode.
    pub fn commit(&mut self) {
        self.applied = std::mem::take(&mut self.draft);
        self.input_active = false;
    }

    /// Cancel discards the draft and exits input mode without changing the
    /// applied pattern.
    pub fn cancel(&mut self) {
        self.draft.clear();
        self.input_active = false;
    }

    /// Clear removes any applied filter and exits input mode.
    pub fn clear(&mut self) {
        self.applied.clear();
        self.draft.clear();
        self.input_active = false;
    }

    pub fn toggle_mode(&mut self) {
        if self.mode == FilterMatchMode::Regex {
            self.mode = FilterMatchMode::Glob;
        } else {
            self.mode = FilterMatchMode::Regex;
        }
    }

    /// UpdateDraft updates the in-progress filter text based on provided input.
    pub fn update_draft(&mut self, msg: &KeyEvent) {
        match msg.code {
            KeyCode::Backspace => self.draft = trim_last_rune(&self.draft).to_owned(),
            KeyCode::Space => self.draft.push(' '),
            _ => {
                // PARITY: Go checks `msg.Text != ""`; `None` ⇔ Go `""`
                // (key.rs field contract).
                if let Some(text) = &msg.text
                    && !text.is_empty()
                {
                    self.draft.push_str(text);
                }
            }
        }
    }

    /// HandleKey processes a filter-mode key event, mutating filter state
    /// accordingly.
    ///
    /// Returns true if the filter state changed (i.e. the caller should
    /// reapply).
    pub fn handle_key(&mut self, msg: &KeyEvent) -> bool {
        match msg.code {
            KeyCode::Esc => {
                if !self.input_active {
                    return false;
                }
                self.cancel();
                true
            }
            KeyCode::Enter => {
                if !self.input_active {
                    return false;
                }
                self.commit();
                true
            }
            KeyCode::Tab => {
                self.toggle_mode();
                true
            }
            KeyCode::Backspace | KeyCode::Space => {
                if msg.code == KeyCode::Backspace && self.draft.is_empty() {
                    return false;
                }
                self.update_draft(msg);
                true
            }
            _ => {
                if msg.text.as_deref().unwrap_or("").is_empty() {
                    return false;
                }
                self.update_draft(msg);
                true
            }
        }
    }

    /// Query returns the current filter pattern (draft if active, applied
    /// otherwise).
    pub fn query(&self) -> &str {
        if self.input_active {
            &self.draft
        } else {
            &self.applied
        }
    }

    /// Mode returns the current matching mode.
    pub fn mode(&self) -> FilterMatchMode {
        self.mode
    }

    /// IsActive reports whether the filter is in input mode.
    pub fn is_active(&self) -> bool {
        self.input_active
    }

    /// Matcher returns a case-insensitive, unanchored matcher according to
    /// mode.
    ///
    /// In regex mode falls back to substring if there are no regex metachars
    /// or if compile fails.
    pub fn matcher(&self) -> TextMatcher {
        compile_text_matcher(self.query(), self.mode)
    }
}

impl Default for Filter {
    /// PARITY: Go constructs `Filter` only via `NewFilter` (filter.go:39-41,
    /// mode = FilterModeRegex); the zero-value struct (mode Undefined) is
    /// never used, so `Default` mirrors the constructor.
    fn default() -> Filter {
        Filter::new()
    }
}

/// Port of `trimLastRune`.
fn trim_last_rune(s: &str) -> &str {
    match s.char_indices().next_back() {
        // PARITY: Go's `size <= 0` fallback (utf8.DecodeLastRuneInString on
        // invalid UTF-8 → strip one byte) is unreachable here: a Rust `str`
        // is always valid UTF-8, so the last char's byte offset always exists.
        Some((idx, _)) => &s[..idx],
        None => s, // s == ""
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::key::KeyMods;

    /// Go `tea.KeyPressMsg{Text: "é"}`-style text key: code is the printable
    /// char, text carries what filter input appends.
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

    // Go: TestFilter_HandleKey_BackspaceIsRuneSafe
    #[test]
    fn filter_handle_key_backspace_is_rune_safe() {
        let mut f = Filter::new();
        f.activate();

        assert!(f.handle_key(&text_key("é")));
        assert_eq!(f.query(), "é");

        assert!(f.handle_key(&code_key(KeyCode::Backspace)));
        assert_eq!(f.query(), "");
    }

    // Go: TestFilter_HandleKey_NavigationKeyIsNoOp
    #[test]
    fn filter_handle_key_navigation_key_is_no_op() {
        let mut f = Filter::new();
        f.activate();

        assert!(!f.handle_key(&code_key(KeyCode::Up)));
        assert!(f.query().is_empty());
    }
}
