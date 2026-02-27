package leet

import (
	tea "github.com/charmbracelet/bubbletea"
)

// ApplyFilter applies the current filter pattern to system metric charts.
func (g *SystemMetricsGrid) ApplyFilter() {
	if g == nil || g.filter == nil {
		return
	}

	filtered := g.filtered[:0]
	matcher := g.filter.Matcher()
	for _, ch := range g.ordered {
		if matcher(ch.Title()) {
			filtered = append(filtered, ch)
		}
	}
	g.filtered = filtered

	size := g.effectiveGridSize()
	g.nav.UpdateTotalPages(len(g.filtered), ItemsPerPage(size))
	g.LoadCurrentPage()
}

// FilteredChartCount returns the number of charts matching the current filter.
func (g *SystemMetricsGrid) FilteredChartCount() int {
	return len(g.filtered)
}

// EnterFilterMode enters filter input mode.
func (g *SystemMetricsGrid) EnterFilterMode() {
	g.filter.Activate()
}

// UpdateFilterDraft updates the in-progress filter text (for live preview).
func (g *SystemMetricsGrid) UpdateFilterDraft(msg tea.KeyMsg) {
	g.filter.UpdateDraft(msg)
}

// ExitFilterMode exits filter input mode and optionally applies the filter.
func (g *SystemMetricsGrid) ExitFilterMode(apply bool) {
	if apply {
		g.filter.Commit()
	} else {
		g.filter.Cancel()
	}
	g.ApplyFilter()
}

// ClearFilter removes the active filter.
func (g *SystemMetricsGrid) ClearFilter() {
	g.filter.Clear()
	g.ApplyFilter()
}

// ToggleFilterMatchMode flips regex <-> glob and reapplies current preview/applied.
func (g *SystemMetricsGrid) ToggleFilterMatchMode() {
	g.filter.ToggleMode()
	g.ApplyFilter()
}

// FilterMode exposes the current filter match mode.
func (g *SystemMetricsGrid) FilterMode() FilterMatchMode {
	return g.filter.Mode()
}

// IsFilterMode reports whether we are currently typing a filter.
func (g *SystemMetricsGrid) IsFilterMode() bool {
	return g.filter.IsActive()
}

// IsFiltering reports whether we have an applied filter (not just input mode).
func (g *SystemMetricsGrid) IsFiltering() bool {
	return !g.filter.IsActive() && g.filter.Query() != ""
}

// FilterQuery returns the current filter pattern (draft if active, applied otherwise).
func (g *SystemMetricsGrid) FilterQuery() string {
	return g.filter.Query()
}

func (g *SystemMetricsGrid) handleSystemMetricsFilterKey(msg tea.KeyMsg) {
	switch msg.Type {
	case tea.KeyEsc:
		g.ExitFilterMode(false)
		return
	case tea.KeyEnter:
		g.ExitFilterMode(true)
		return
	case tea.KeyTab:
		g.ToggleFilterMatchMode()
		return
	case tea.KeyBackspace, tea.KeySpace, tea.KeyRunes:
		g.UpdateFilterDraft(msg)
		g.ApplyFilter()
		return
	default:
		return
	}
}
