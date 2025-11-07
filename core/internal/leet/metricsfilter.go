package leet

import "strings"

// FilterState tracks the filter state.
//
// Used for filtering run overview or metric charts.
type FilterState struct {
	inputActive bool   // filter input mode
	draft       string // what the user is typing (preview)
	applied     string // committed pattern
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
		for _, ch := range mg.all {
			if globMatchUnanchoredCaseInsensitive(pattern, ch.Title()) {
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
		for _, chart := range mg.all {
			if globMatchUnanchoredCaseInsensitive(p, chart.Title()) {
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

// EnterFilterMode enters filter input mode
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
