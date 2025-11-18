package leet

import (
	"regexp"
	"strings"
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

// FilterState tracks the filter state.
//
// Used for filtering run overview or metric charts.
type FilterState struct {
	inputActive bool            // filter input mode
	draft       string          // what the user is typing (preview)
	applied     string          // committed pattern
	mode        FilterMatchMode // current match mode
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

// ApplyFilter applies the filter pattern to charts.
func (mg *MetricsGrid) ApplyFilter(pattern string) {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	mg.filter.applied = pattern
	mg.applyFilterNoLock(pattern)
}

// applyFilterNoLock applies the filter.
//
// Caller must hold the lock mg.mu.
func (mg *MetricsGrid) applyFilterNoLock(pattern string) {
	if pattern == "" {
		// Copy to avoid aliasing the backing array of allCharts
		mg.filtered = append(make([]*EpochLineChart, 0, len(mg.all)), mg.all...)
	} else {
		// Fresh slice, no alias with allCharts.
		filtered := make([]*EpochLineChart, 0, len(mg.all))
		match := buildTitleMatcher(mg.filter.mode, pattern)
		for _, ch := range mg.all {
			if match(ch.Title()) {
				filtered = append(filtered, ch)
			}
		}
		mg.filtered = filtered
	}

	// Keep pagination in sync with what fits now.
	size := mg.effectiveGridSize()
	mg.nav.UpdateTotalPages(len(mg.filtered), ItemsPerPage(size))

	mg.loadCurrentPageNoLock()
}

// FilteredChartCount returns the number of charts matching the current filter.
// When typing (active preview), it estimates live from the draft pattern.
func (mg *MetricsGrid) FilteredChartCount() int {
	if mg.filter.inputActive {
		p := mg.filter.draft
		if p == "" {
			return len(mg.all)
		}

		mg.mu.RLock()
		defer mg.mu.RUnlock()

		count := 0
		match := buildTitleMatcher(mg.filter.mode, p)
		for _, chart := range mg.all {
			if match(chart.Title()) {
				count++
			}
		}
		return count
	}

	mg.mu.RLock()
	defer mg.mu.RUnlock()
	if mg.filter.applied == "" {
		return len(mg.all)
	}
	return len(mg.filtered)
}

// EnterFilterMode enters filter input mode.
func (mg *MetricsGrid) EnterFilterMode() {
	mg.filter.inputActive = true
	mg.filter.draft = mg.filter.applied // Start with current filter
}

// SetFilterDraft updates the in-progress filter text (for live preview).
// It does not apply the filter; call ExitFilterMode(true) or ApplyFilter to commit.
func (mg *MetricsGrid) SetFilterDraft(pattern string) {
	mg.filter.draft = pattern
}

// ExitFilterMode exits filter input mode and optionally applies the filter.
func (mg *MetricsGrid) ExitFilterMode(apply bool) {
	mg.filter.inputActive = false
	if apply {
		// Commit the filter that was being typed.
		mg.filter.applied = mg.filter.draft
	}
	// Always reapply based on the committed filter so Esc cancels preview.
	mg.ApplyFilter(mg.filter.applied)
	mg.drawVisible()
}

// ClearFilter removes the active filter.
func (mg *MetricsGrid) ClearFilter() {
	mg.filter.applied = ""
	mg.filter.draft = ""
	mg.ApplyFilter("")
	mg.drawVisible()
}

// buildTitleMatcher returns a case-insensitive, unanchored matcher according to mode.
// Regex mode falls back to substring if there are no regex metachars or if compile fails.
func buildTitleMatcher(mode FilterMatchMode, pattern string) func(string) bool {
	if pattern == "" {
		return func(string) bool { return true }
	}
	switch mode {
	case FilterModeGlob:
		return func(title string) bool {
			return globMatchUnanchoredCaseInsensitive(pattern, title)
		}
	default: // FilterModeRegex
		if !hasRegexMeta(pattern) {
			lp := strings.ToLower(pattern)
			return func(title string) bool {
				return strings.Contains(strings.ToLower(title), lp)
			}
		}
		// Compile once; if it fails, fall back to substring.
		re, err := regexp.Compile("(?i)" + pattern)
		if err != nil {
			lp := strings.ToLower(pattern)
			return func(title string) bool {
				return strings.Contains(strings.ToLower(title), lp)
			}
		}
		return func(title string) bool { return re.FindStringIndex(title) != nil }
	}
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

// ToggleFilterMode flips regex <-> glob and reapplies current preview/applied.
func (mg *MetricsGrid) ToggleFilterMode() {
	if mg.filter.mode == FilterModeRegex {
		mg.filter.mode = FilterModeGlob
	} else {
		mg.filter.mode = FilterModeRegex
	}
	mg.ApplyFilter(mg.filter.draft)
	mg.drawVisible()
}

// FilterMode exposes the current filter match mode.
func (mg *MetricsGrid) FilterMode() FilterMatchMode { return mg.filter.mode }
