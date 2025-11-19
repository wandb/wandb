package leet

import (
	"regexp"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

// FilterMatchMode selects the string-matching engine for metric titles.
type FilterMatchMode int

const (
	FilterModeRegex FilterMatchMode = iota
	FilterModeGlob
)

func (m FilterMatchMode) String() string {
	switch m {
	case FilterModeGlob:
		return "glob"
	default:
		return "regex"
	}
}

// Filter tracks the filter state.
//
// Used for filtering run overview items and metric charts.
type Filter struct {
	inputActive bool            // filter input mode
	draft       string          // what the user is typing (preview)
	applied     string          // committed pattern
	mode        FilterMatchMode // current match mode
}

// Activate enters input mode, initializing the draft with the current applied pattern.
func (f *Filter) Activate() {
	f.inputActive = true
	f.draft = f.applied
}

// Commit applies the current draft and exits input mode.
func (f *Filter) Commit() {
	f.applied = f.draft
	f.draft = ""
	f.inputActive = false
}

// Cancel discards the draft and exits input mode without changing the applied pattern.
func (f *Filter) Cancel() {
	f.draft = ""
	f.inputActive = false
}

// Clear removes any applied filter and exits input mode.
func (f *Filter) Clear() {
	f.applied = ""
	f.draft = ""
	f.inputActive = false
}

func (f *Filter) ToggleMode() {
	if f.mode == FilterModeRegex {
		f.mode = FilterModeGlob
	} else {
		f.mode = FilterModeRegex
	}
}

// UpdateDraft updates the in-progress filter text based on provided input.
func (f *Filter) UpdateDraft(msg tea.KeyMsg) {
	switch msg.Type {
	case tea.KeyBackspace:
		if len(f.draft) > 0 {
			f.draft = f.draft[:len(f.draft)-1]
		}
	case tea.KeySpace:
		f.draft += " "
	case tea.KeyRunes:
		f.draft += string(msg.Runes)
	}
}

// Query returns the current filter pattern (draft if active, applied otherwise).
func (f *Filter) Query() string {
	if f.inputActive {
		return f.draft
	}
	return f.applied
}

// Mode returns the current matching mode.
func (f *Filter) Mode() FilterMatchMode {
	return f.mode
}

// IsActive reports whether the filter is in input mode.
func (f *Filter) IsActive() bool {
	return f.inputActive
}

// Matcher returns a case-insensitive, unanchored matcher according to mode.
//
// In regex mode falls back to substring if there are no regex metachars
// or if compile fails.
func (f *Filter) Matcher() func(string) bool {
	if f.Query() == "" {
		return func(string) bool { return true }
	}
	switch f.mode {
	case FilterModeGlob:
		return func(title string) bool {
			return globMatchUnanchoredCaseInsensitive(f.Query(), title)
		}
	default: // FilterModeRegex
		if !hasRegexMeta(f.Query()) {
			lp := strings.ToLower(f.Query())
			return func(title string) bool {
				return strings.Contains(strings.ToLower(title), lp)
			}
		}
		// Compile once; if it fails, fall back to substring.
		re, err := regexp.Compile("(?i)" + f.Query())
		if err != nil {
			lp := strings.ToLower(f.Query())
			return func(title string) bool {
				return strings.Contains(strings.ToLower(title), lp)
			}
		}
		return func(title string) bool { return re.FindStringIndex(title) != nil }
	}
}

// globMatchUnanchoredCaseInsensitive reports whether s matches pattern using
// case-insensitive, unanchored glob semantics.
//
// Supported meta: '*' (any sequence), '?' (any single char).
// '/' is treated as a normal character (not a separator).
func globMatchUnanchoredCaseInsensitive(pattern, s string) bool {
	p := strings.ToLower(pattern)
	t := strings.ToLower(s)

	// Empty or single '*' matches everything.
	if p == "" || p == "*" {
		return true
	}

	// No wildcards -> substring match.
	if !strings.ContainsAny(p, "*?") {
		return strings.Contains(t, p)
	}

	// Unanchored by default: allow leading/trailing text.
	if !strings.HasPrefix(p, "*") {
		p = "*" + p
	}
	if !strings.HasSuffix(p, "*") {
		p += "*"
	}

	return wildcardMatch(p, t)
}

// wildcardMatch is a classic '*'/'?' matcher with backtracking.
// Assumes inputs are already lowercased.
func wildcardMatch(p, t string) bool {
	pi, si := 0, 0
	star, match := -1, 0

	for si < len(t) {
		switch {
		case pi < len(p) && (p[pi] == '?' || p[pi] == t[si]):
			pi++
			si++
		case pi < len(p) && p[pi] == '*':
			star = pi
			match = si
			pi++
		case star != -1:
			pi = star + 1
			match++
			si = match
		default:
			return false
		}
	}
	for pi < len(p) && p[pi] == '*' {
		pi++
	}
	return pi == len(p)
}

// hasRegexMeta reports whether s contains any Go regexp metacharacters.
func hasRegexMeta(s string) bool {
	for _, r := range s {
		switch r {
		case '.', '^', '$', '*', '+', '?', '(', ')', '[', ']', '{', '}', '|', '\\':
			return true
		}
	}
	return false
}
