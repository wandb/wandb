package leet

import (
	tea "github.com/charmbracelet/bubbletea"
)

// ApplyFilter applies the filter pattern to charts.
func (mg *MetricsGrid) ApplyFilter() {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	mg.applyFilterNoLock()
}

// applyFilterNoLock applies the filter.
//
// Caller must hold the lock mg.mu.
func (mg *MetricsGrid) applyFilterNoLock() {
	// Fresh slice, no alias with allCharts.
	filtered := make([]*EpochLineChart, 0, len(mg.all))
	matcher := mg.filter.Matcher()
	for _, ch := range mg.all {
		if matcher(ch.Title()) {
			filtered = append(filtered, ch)
		}
	}
	mg.filtered = filtered

	// Keep pagination in sync with what fits now.
	size := mg.effectiveGridSize()
	mg.nav.UpdateTotalPages(len(mg.filtered), ItemsPerPage(size))

	mg.loadCurrentPageNoLock()
}

// FilteredChartCount returns the number of charts matching the current filter.
func (mg *MetricsGrid) FilteredChartCount() int {
	mg.mu.RLock()
	defer mg.mu.RUnlock()
	return len(mg.filtered)
}

// EnterFilterMode enters filter input mode.
func (mg *MetricsGrid) EnterFilterMode() {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	mg.filter.Activate()
}

// UpdateFilterDraft updates the in-progress filter text (for live preview).
func (mg *MetricsGrid) UpdateFilterDraft(msg tea.KeyMsg) {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	mg.filter.UpdateDraft(msg)
}

// ExitFilterMode exits filter input mode and optionally applies the filter.
func (mg *MetricsGrid) ExitFilterMode(apply bool) {
	mg.mu.Lock()
	if apply {
		mg.filter.Commit()
	} else {
		mg.filter.Cancel()
	}
	mg.mu.Unlock()
	mg.ApplyFilter()
	mg.drawVisible()
}

// ClearFilter removes the active filter.
func (mg *MetricsGrid) ClearFilter() {
	mg.mu.Lock()
	mg.filter.Clear()
	mg.mu.Unlock()
	mg.ApplyFilter()
	mg.drawVisible()
}

// ToggleFilterMatchMode flips regex <-> glob and reapplies current preview/applied.
func (mg *MetricsGrid) ToggleFilterMatchMode() {
	mg.mu.Lock()
	mg.filter.ToggleMode()
	mg.mu.Unlock()
	mg.ApplyFilter()
	mg.drawVisible()
}

// FilterMode exposes the current filter match mode.
func (mg *MetricsGrid) FilterMode() FilterMatchMode {
	mg.mu.RLock()
	defer mg.mu.RUnlock()
	return mg.filter.Mode()
}
