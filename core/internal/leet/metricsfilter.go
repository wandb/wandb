package leet

import "strings"

// FilterState tracks the filter state (for run overview or metric charts).
type FilterState struct {
	active  bool   // filter input mode
	draft   string // what the user is typing
	applied string // committed pattern
}

// GlobMatch matches s against pattern with case-insensitive,
// unanchored glob semantics: '*' = any sequence, '?' = any single char.
// '/' is treated as a normal character.
func GlobMatch(pattern, s string) bool {
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

// applyFilter applies the current filter pattern to charts.
func (m *MetricsGrid) applyFilter(pattern string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.applyFilterNoLock(pattern)
}

// applyFilterNoLock applies the filter assuming the caller holds chartMu.
func (m *MetricsGrid) applyFilterNoLock(pattern string) {
	if pattern == "" {
		// Copy to avoid aliasing the backing array of allCharts
		// (prevents duplicates when appending while iterating).
		m.filtered = append(make([]*EpochLineChart, 0, len(m.all)), m.all...)
	} else {
		// Fresh slice, no alias with allCharts.
		filtered := make([]*EpochLineChart, 0, len(m.all))
		for _, ch := range m.all {
			if GlobMatch(pattern, ch.Title()) {
				filtered = append(filtered, ch)
			}
		}
		m.filtered = filtered
	}

	// Keep pagination in sync with what fits now.
	size := m.effectiveGridSize()
	m.nav.UpdateTotalPages(len(m.filtered), ItemsPerPage(size))

	m.loadCurrentPageNoLock()
}

// filteredChartCount returns the number of charts matching the current filter.
func (m *MetricsGrid) filteredChartCount() int {
	if m.filter.active {
		p := m.filter.draft
		if p == "" {
			return len(m.all)
		}

		m.mu.RLock()
		defer m.mu.RUnlock()

		count := 0
		for _, chart := range m.all {
			if GlobMatch(p, chart.Title()) {
				count++
			}
		}
		return count
	}
	return len(m.filtered)
}

// enterFilterMode enters filter input mode
func (m *MetricsGrid) enterFilterMode() {
	m.filter.active = true
	m.filter.draft = m.filter.applied // Start with current filter
}

// exitFilterMode exits filter input mode and optionally applies the filter
func (m *MetricsGrid) exitFilterMode(apply bool) {
	m.filter.active = false
	if apply {
		// Commit the filter that was being typed.
		m.filter.applied = m.filter.draft
	}
	// Always reapply based on the COMMITTED filter, so Esc cancels preview.
	m.applyFilter(m.filter.applied)
	m.drawVisible()
}

// clearFilter removes the active filter
func (m *MetricsGrid) clearFilter() {
	m.filter.applied = ""
	m.filter.draft = ""
	m.applyFilter("")
	m.drawVisible()
}
