//! Text filtering with draft/applied states and regex/glob matching.

use regex::RegexBuilder;

/// String-matching engine for filter queries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FilterMatchMode {
    Regex,
    Glob,
}

impl std::fmt::Display for FilterMatchMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FilterMatchMode::Glob => write!(f, "glob"),
            FilterMatchMode::Regex => write!(f, "regex"),
        }
    }
}

/// Key events relevant to filter input.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FilterKey {
    // Variants are mapped from terminal keys by `FilterKey::from_event`.
    Esc,
    Enter,
    Tab,
    Backspace,
    Char(char),
}

impl FilterKey {
    /// Maps a terminal key event to a filter key, or None when the key is
    /// not filter input.
    pub fn from_event(key: &crossterm::event::KeyEvent) -> Option<Self> {
        use crossterm::event::{KeyCode, KeyModifiers};
        match key.code {
            KeyCode::Esc => Some(FilterKey::Esc),
            KeyCode::Enter => Some(FilterKey::Enter),
            KeyCode::Tab => Some(FilterKey::Tab),
            KeyCode::Backspace => Some(FilterKey::Backspace),
            KeyCode::Char(c) if !key.modifiers.contains(KeyModifiers::CONTROL) => {
                Some(FilterKey::Char(c))
            }
            _ => None,
        }
    }
}

/// Tracks filter state: input mode, draft (preview), and applied pattern.
#[derive(Debug, Clone)]
pub struct Filter {
    input_active: bool,
    draft: String,
    applied: String,
    mode: FilterMatchMode,
}

impl Default for Filter {
    fn default() -> Self {
        Self::new()
    }
}

impl Filter {
    pub fn new() -> Self {
        Self {
            input_active: false,
            draft: String::new(),
            applied: String::new(),
            mode: FilterMatchMode::Regex,
        }
    }

    /// Enters input mode, initializing the draft with the applied pattern.
    pub fn activate(&mut self) {
        self.input_active = true;
        self.draft = self.applied.clone();
    }

    /// Applies the current draft and exits input mode.
    pub fn commit(&mut self) {
        self.applied = std::mem::take(&mut self.draft);
        self.input_active = false;
    }

    /// Discards the draft and exits input mode.
    pub fn cancel(&mut self) {
        self.draft.clear();
        self.input_active = false;
    }

    /// Removes any applied filter and exits input mode.
    pub fn clear(&mut self) {
        self.applied.clear();
        self.draft.clear();
        self.input_active = false;
    }

    pub fn toggle_mode(&mut self) {
        self.mode = match self.mode {
            FilterMatchMode::Regex => FilterMatchMode::Glob,
            FilterMatchMode::Glob => FilterMatchMode::Regex,
        };
    }

    /// Updates the in-progress filter text based on input.
    pub fn update_draft(&mut self, key: FilterKey) {
        match key {
            FilterKey::Backspace => {
                self.draft.pop();
            }
            FilterKey::Char(c) => self.draft.push(c),
            _ => {}
        }
    }

    /// Processes a filter-mode key event; returns true if the state changed
    /// (i.e. the caller should reapply the filter).
    pub fn handle_key(&mut self, key: FilterKey) -> bool {
        match key {
            FilterKey::Esc => {
                if !self.input_active {
                    return false;
                }
                self.cancel();
                true
            }
            FilterKey::Enter => {
                if !self.input_active {
                    return false;
                }
                self.commit();
                true
            }
            FilterKey::Tab => {
                self.toggle_mode();
                true
            }
            FilterKey::Backspace => {
                if self.draft.is_empty() {
                    return false;
                }
                self.update_draft(key);
                true
            }
            FilterKey::Char(_) => {
                self.update_draft(key);
                true
            }
        }
    }

    /// The current filter pattern (draft if active, applied otherwise).
    pub fn query(&self) -> &str {
        if self.input_active {
            &self.draft
        } else {
            &self.applied
        }
    }

    pub fn mode(&self) -> FilterMatchMode {
        self.mode
    }

    /// Whether the filter is in input mode.
    pub fn is_active(&self) -> bool {
        self.input_active
    }

    /// A case-insensitive, unanchored matcher according to the current mode.
    pub fn matcher(&self) -> Matcher {
        compile_text_matcher(self.query(), self.mode)
    }
}

/// A compiled text matcher.
pub enum Matcher {
    All,
    Substring(String),
    Regex(regex::Regex),
    Glob(String),
}

impl Matcher {
    pub fn matches(&self, s: &str) -> bool {
        match self {
            Matcher::All => true,
            Matcher::Substring(q) => s.to_lowercase().contains(q),
            Matcher::Regex(re) => re.is_match(s),
            Matcher::Glob(q) => glob_match_unanchored_case_insensitive(q, s),
        }
    }
}

/// Returns a case-insensitive matcher according to mode. Shared by the
/// generic [`Filter`] and higher-level query parsers so all text filtering
/// uses the same glob/regex semantics.
pub fn compile_text_matcher(query: &str, mode: FilterMatchMode) -> Matcher {
    if query.is_empty() {
        return Matcher::All;
    }

    match mode {
        FilterMatchMode::Glob => Matcher::Glob(query.to_string()),
        FilterMatchMode::Regex => {
            if !has_regex_meta(query) {
                return Matcher::Substring(query.to_lowercase());
            }
            match RegexBuilder::new(query).case_insensitive(true).build() {
                Ok(re) => Matcher::Regex(re),
                Err(_) => Matcher::Substring(query.to_lowercase()),
            }
        }
    }
}

/// Case-insensitive, unanchored glob matching. Supported meta: `*` (any
/// sequence), `?` (any single char). `/` is a normal character.
pub fn glob_match_unanchored_case_insensitive(pattern: &str, s: &str) -> bool {
    let p = pattern.to_lowercase();
    let t = s.to_lowercase();

    if p.is_empty() || p == "*" {
        return true;
    }

    if !p.contains(['*', '?']) {
        return t.contains(&p);
    }

    // Unanchored by default: allow leading/trailing text.
    let mut p = p;
    if !p.starts_with('*') {
        p.insert(0, '*');
    }
    if !p.ends_with('*') {
        p.push('*');
    }

    wildcard_match(p.as_bytes(), t.as_bytes())
}

/// Classic `*`/`?` matcher with backtracking; inputs already lowercased.
fn wildcard_match(p: &[u8], t: &[u8]) -> bool {
    let (mut pi, mut si) = (0usize, 0usize);
    let (mut star, mut matched) = (usize::MAX, 0usize);

    while si < t.len() {
        if pi < p.len() && (p[pi] == b'?' || p[pi] == t[si]) {
            pi += 1;
            si += 1;
        } else if pi < p.len() && p[pi] == b'*' {
            star = pi;
            matched = si;
            pi += 1;
        } else if star != usize::MAX {
            pi = star + 1;
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

/// Whether `s` contains any regexp metacharacters.
fn has_regex_meta(s: &str) -> bool {
    s.chars().any(|r| {
        matches!(
            r,
            '.' | '^' | '$' | '*' | '+' | '?' | '(' | ')' | '[' | ']' | '{' | '}' | '|' | '\\'
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regex_fallback_substring() {
        let m = compile_text_matcher("loss", FilterMatchMode::Regex);
        assert!(m.matches("train/LOSS"));
        assert!(!m.matches("accuracy"));
    }

    #[test]
    fn regex_meta() {
        let m = compile_text_matcher("^train/", FilterMatchMode::Regex);
        assert!(m.matches("train/loss"));
        assert!(!m.matches("val/train"));
    }

    #[test]
    fn invalid_regex_falls_back() {
        let m = compile_text_matcher("a(b", FilterMatchMode::Regex);
        assert!(m.matches("xa(bx"));
    }

    #[test]
    fn glob_unanchored() {
        assert!(glob_match_unanchored_case_insensitive(
            "train*loss",
            "train/foo/loss_x"
        ));
        assert!(glob_match_unanchored_case_insensitive("Loss", "train/loss"));
        assert!(glob_match_unanchored_case_insensitive("l?ss", "xxlossxx"));
        assert!(!glob_match_unanchored_case_insensitive(
            "val*",
            "train/loss"
        ));
        assert!(glob_match_unanchored_case_insensitive("*", "anything"));
    }

    #[test]
    fn draft_applied_lifecycle() {
        let mut f = Filter::new();
        f.activate();
        assert!(f.is_active());
        f.handle_key(FilterKey::Char('a'));
        f.handle_key(FilterKey::Char('b'));
        assert_eq!(f.query(), "ab");
        f.handle_key(FilterKey::Backspace);
        assert_eq!(f.query(), "a");
        f.handle_key(FilterKey::Enter);
        assert!(!f.is_active());
        assert_eq!(f.query(), "a");
        f.activate();
        f.handle_key(FilterKey::Char('z'));
        f.handle_key(FilterKey::Esc);
        assert_eq!(f.query(), "a");
        f.clear();
        assert_eq!(f.query(), "");
    }
}
