package leet

// buildRunFocusManager constructs the FocusManager for the single-run view.
//
// Called once from NewRun after all UI components are initialized. The closures
// capture the *Run pointer so availability checks always reflect live state.
func (r *Run) buildRunFocusManager() *FocusManager {
	return NewFocusManager([]FocusRegionDef{
		{
			Target:     FocusTargetOverview,
			Available:  r.overviewFocusAvailable,
			Activate:   r.activateOverviewFocus,
			Deactivate: r.deactivateOverviewFocus,
		},
		{
			Target:     FocusTargetMetricsGrid,
			Available:  r.metricsGridFocusAvailable,
			Activate:   r.activateMetricsGridFocus,
			Deactivate: r.deactivateMetricsGridFocus,
		},
		{
			Target:     FocusTargetSystemMetrics,
			Available:  r.systemMetricsFocusAvailable,
			Activate:   r.activateSystemMetricsFocus,
			Deactivate: r.deactivateSystemMetricsFocus,
		},
		{
			Target:     FocusTargetMedia,
			Available:  r.mediaFocusAvailable,
			Activate:   r.activateMediaFocus,
			Deactivate: r.deactivateMediaFocus,
		},
		{
			Target:     FocusTargetConsoleLogs,
			Available:  r.logsFocusAvailable,
			Activate:   r.activateLogsFocus,
			Deactivate: r.deactivateLogsFocus,
		},
	})
}

// ---- Availability ----

func (r *Run) overviewFocusAvailable() bool {
	firstSec, _ := r.leftSidebar.focusableSectionBounds()
	return r.leftSidebar.animState.IsExpanded() && firstSec != -1
}

func (r *Run) metricsGridFocusAvailable() bool {
	return r.metricsGridAnimState.IsExpanded() && r.metricsGrid.ChartCount() > 0
}

func (r *Run) systemMetricsFocusAvailable() bool {
	return r.rightSidebar.IsVisible() && r.rightSidebar.metricsGrid.ChartCount() > 0
}

func (r *Run) mediaFocusAvailable() bool {
	return r.mediaPane.IsExpanded() && r.mediaPane.HasData()
}

func (r *Run) logsFocusAvailable() bool {
	return r.consoleLogsPane.IsExpanded()
}

// ---- Activate ----

func (r *Run) activateOverviewFocus(direction int) {
	firstSec, lastSec := r.leftSidebar.focusableSectionBounds()
	if direction >= 0 {
		r.leftSidebar.setActiveSection(firstSec)
	} else {
		r.leftSidebar.setActiveSection(lastSec)
	}
}

func (r *Run) activateMetricsGridFocus(_ int) {
	r.focus.Type = FocusMainChart
	if r.focus.Row < 0 || r.focus.Col < 0 {
		r.focus.Row = 0
		r.focus.Col = 0
	}
	r.metricsGrid.NavigateFocus(0, 0)
}

func (r *Run) activateSystemMetricsFocus(_ int) {
	r.focus.Type = FocusSystemChart
	if r.focus.Row < 0 || r.focus.Col < 0 {
		r.focus.Row = 0
		r.focus.Col = 0
	}
	r.rightSidebar.metricsGrid.NavigateFocus(0, 0)
}

func (r *Run) activateMediaFocus(_ int) {
	r.mediaPane.SetActive(true)
}

func (r *Run) activateLogsFocus(_ int) {
	r.consoleLogsPane.SetActive(true)
}

// ---- Deactivate ----

func (r *Run) deactivateOverviewFocus() {
	r.leftSidebar.deactivateAllSections()
}

func (r *Run) deactivateMetricsGridFocus() {
	if r.focus.Type == FocusMainChart {
		r.focus.Reset()
	}
}

func (r *Run) deactivateSystemMetricsFocus() {
	if r.focus.Type == FocusSystemChart {
		r.focus.Reset()
	}
}

func (r *Run) deactivateMediaFocus() {
	r.mediaPane.SetActive(false)
}

func (r *Run) deactivateLogsFocus() {
	r.consoleLogsPane.SetActive(false)
}

// ---- Within-region cycling ----

// cycleRunOverviewSection tries to move within overview sections.
// Returns true if the navigation was handled (i.e. we're not at a boundary).
func (r *Run) cycleRunOverviewSection(direction int) bool {
	firstSec, lastSec := r.leftSidebar.focusableSectionBounds()
	if !r.leftSidebar.animState.IsExpanded() || firstSec == -1 {
		return false
	}

	atBoundary := (direction == 1 && r.leftSidebar.activeSection == lastSec) ||
		(direction == -1 && r.leftSidebar.activeSection == firstSec)
	if atBoundary {
		return false
	}

	r.leftSidebar.navigateSection(direction)
	return true
}
