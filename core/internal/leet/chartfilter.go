package leet

import "strings"

// matchPattern implements simple glob pattern matching that treats / as a regular character
func matchPattern(pattern, str string) bool {
	// Convert both to lowercase for case-insensitive matching
	pattern = strings.ToLower(pattern)
	str = strings.ToLower(str)

	// Handle special cases
	if pattern == "" {
		return true
	}
	if pattern == "*" {
		return true
	}

	// Simple implementation of glob matching
	pi := 0    // pattern index
	si := 0    // string index
	star := -1 // position of last * in pattern
	match := 0 // position in string matched by *

	for si < len(str) {
		switch {
		case pi < len(pattern) && (pattern[pi] == '?' || pattern[pi] == str[si]):
			// Character match or ? wildcard
			pi++
			si++
		case pi < len(pattern) && pattern[pi] == '*':
			// * wildcard - record position and try to match rest
			star = pi
			match = si
			pi++
		case star != -1:
			// Backtrack to last * and try matching one more character
			pi = star + 1
			match++
			si = match
		default:
			// No match
			return false
		}
	}

	// Check for remaining wildcards in pattern
	for pi < len(pattern) && pattern[pi] == '*' {
		pi++
	}

	return pi == len(pattern)
}

// applyFilter applies the current filter pattern to charts.
func (m *Model) applyFilter(pattern string) {
	m.chartMu.Lock()
	defer m.chartMu.Unlock()
	m.applyFilterNoLock(pattern)
}

// applyFilterNoLock applies the filter assuming the caller holds chartMu.
func (m *Model) applyFilterNoLock(pattern string) {
	if pattern == "" {
		// No filter, use all charts
		m.filteredCharts = m.allCharts
	} else {
		// Apply filter
		m.filteredCharts = make([]*EpochLineChart, 0)

		// If pattern has no wildcards, treat as substring match
		useSubstring := !strings.Contains(pattern, "*") && !strings.Contains(pattern, "?")

		for _, chart := range m.allCharts {
			chartTitle := chart.Title()

			var matched bool
			if useSubstring {
				// Simple substring match (case-insensitive)
				matched = strings.Contains(strings.ToLower(chartTitle), strings.ToLower(pattern))
			} else {
				// Use our custom glob matcher
				matched = matchPattern(pattern, chartTitle)
			}

			if matched {
				m.filteredCharts = append(m.filteredCharts, chart)
			}
		}
	}

	// Recalculate pages based on filtered charts
	m.totalPages = (len(m.filteredCharts) + ChartsPerPage - 1) / ChartsPerPage
	if m.currentPage >= m.totalPages && m.totalPages > 0 {
		m.currentPage = 0
	}

	m.loadCurrentPageNoLock()
}

// enterFilterMode enters filter input mode
func (m *Model) enterFilterMode() {
	m.filterMode = true
	m.filterInput = m.activeFilter // Start with current filter
}

// exitFilterMode exits filter input mode and optionally applies the filter
func (m *Model) exitFilterMode(apply bool) {
	m.filterMode = false
	if apply {
		m.activeFilter = m.filterInput
		m.applyFilter(m.activeFilter)
		m.drawVisibleCharts()
	} else {
		// Restore previous filter
		m.filterInput = m.activeFilter
		m.applyFilter(m.activeFilter)
	}
}

// clearFilter removes the active filter
func (m *Model) clearFilter() {
	m.activeFilter = ""
	m.filterInput = ""
	m.applyFilter("")
	m.drawVisibleCharts()
}

// getFilteredChartCount returns the number of charts matching the current filter
func (m *Model) getFilteredChartCount() int {
	if m.filterMode {
		// Count matches for current input
		count := 0
		pattern := m.filterInput
		if pattern == "" {
			return len(m.allCharts)
		}

		m.chartMu.RLock()
		defer m.chartMu.RUnlock()

		// If pattern has no wildcards, treat as substring match
		useSubstring := !strings.Contains(pattern, "*") && !strings.Contains(pattern, "?")

		for _, chart := range m.allCharts {
			chartTitle := chart.Title()

			var matched bool
			if useSubstring {
				// Simple substring match (case-insensitive)
				matched = strings.Contains(strings.ToLower(chartTitle), strings.ToLower(pattern))
			} else {
				// Use our custom glob matcher
				matched = matchPattern(pattern, chartTitle)
			}

			if matched {
				count++
			}
		}
		return count
	}
	return len(m.filteredCharts)
}
