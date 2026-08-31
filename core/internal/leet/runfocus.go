package leet

import tea "charm.land/bubbletea/v2"

// buildRunFocusManager constructs the FocusManager for the single-run view.
//
// The region order follows the spatial layout so Tab flows naturally:
// left sidebar (overview) → main column top-to-bottom (metrics, media,
// logs) → right sidebar (system metrics).
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
		{
			Target:     FocusTargetSystemMetrics,
			Available:  r.systemMetricsFocusAvailable,
			Activate:   r.activateSystemMetricsFocus,
			Deactivate: r.deactivateSystemMetricsFocus,
		},
	})
}

// ---- Availability ----
//
// A region is available when its pane's target state is visible and it has
// content to interact with. Empty panes are skipped by Tab navigation.

func (r *Run) overviewFocusAvailable() bool {
	firstSec, _ := r.leftSidebar.focusableSectionBounds()
	return r.leftSidebar.animState.TargetVisible() && firstSec != -1
}

func (r *Run) metricsGridFocusAvailable() bool {
	return r.metricsGridAnimState.TargetVisible() && r.metricsGrid.ChartCount() > 0
}

func (r *Run) systemMetricsFocusAvailable() bool {
	return r.rightSidebar.animState.TargetVisible() &&
		r.rightSidebar.metricsGrid.ChartCount() > 0
}

func (r *Run) mediaFocusAvailable() bool {
	return r.mediaPane.animState.TargetVisible() && r.mediaPane.HasData()
}

func (r *Run) logsFocusAvailable() bool {
	return r.consoleLogsPane.animState.TargetVisible() && r.consoleLogsPane.HasData()
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

// Chart focus is seeded via NavigateFocus(0, 0): activation always follows a
// deactivation that reset the shared Focus, so the grid's no-focus path lands
// on the first populated cell and sets the full focus state (including the
// chart title shown in the status bar). Writing Type/Row/Col here directly
// would fool that path into treating focus as already applied.

func (r *Run) activateMetricsGridFocus(_ int) {
	r.metricsGrid.NavigateFocus(0, 0)
}

func (r *Run) activateSystemMetricsFocus(_ int) {
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
	// Fullscreen follows focus: once focus leaves the pane, no key path
	// could exit fullscreen and Esc would be captured forever.
	r.mediaPane.ExitFullscreen()
	r.mediaPane.SetActive(false)
}

func (r *Run) deactivateLogsFocus() {
	r.consoleLogsPane.SetActive(false)
}

// resolveFocusAfterData keeps focus consistent as data streams in.
//
// The first time any region becomes available, focus is seeded there so
// keyboard navigation works immediately after load. From then on, incoming
// data never moves focus; it is only cleared if the focused pane disappears.
func (r *Run) resolveFocusAfterData() {
	if r.focusSeeded {
		r.focusMgr.Resolve()
		return
	}
	if r.focusMgr.Current() == FocusTargetNone {
		r.focusMgr.Tab(1)
	}
	r.focusSeeded = r.focusMgr.Current() != FocusTargetNone
}

// HasPaneFocus reports whether any pane currently holds focus.
func (r *Run) HasPaneFocus() bool {
	return r.focusMgr.Current() != FocusTargetNone
}

// handleEscape clears pane focus. When nothing is focused, the parent model
// handles Esc by exiting back to the workspace.
func (r *Run) handleEscape(tea.KeyPressMsg) tea.Cmd {
	// An explicit unfocus ends the initial-focus seeding era: later data
	// must not move focus back.
	r.focusSeeded = true
	r.focusMgr.ClearAll()
	return nil
}

// ---- Within-region cycling ----

// cycleRunOverviewSection tries to move within overview sections.
// Returns true if the navigation was handled (i.e. we're not at a boundary).
func (r *Run) cycleRunOverviewSection(direction int) bool {
	firstSec, lastSec := r.leftSidebar.focusableSectionBounds()
	if !r.overviewFocusAvailable() {
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
