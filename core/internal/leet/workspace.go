package leet

import (
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/wandb/wandb/core/internal/observability"
)

// Workspace is the multi‑run view.
//
// Implements tea.Model.
type Workspace struct {
	wandbDir string

	// Configuration and key bindings.
	config *ConfigManager
	keyMap map[string]func(*Workspace, tea.KeyMsg) tea.Cmd

	// Runs sidebar animation state.
	runsAnimState *AnimationState

	// runs is the run selector.
	runs         PagedList
	selectedRuns map[string]bool // runDirName -> selected
	pinnedRun    string          // runDirName or ""

	// Run overview for each run keyed by run path.
	runOverview        map[string]*RunOverview
	runOverviewSidebar *RunOverviewSidebar

	// Run overview preload pipeline for unselected runs.
	overviewPreloader runOverviewPreloader

	// autoSelectLatestRunOnLoad is triggered when at least one run
	// appears in the workspace.
	autoSelectLatestRunOnLoad sync.Once

	// TODO: mark live runs upon selection.

	// TODO: filter for the run selector.
	// TODO: allow filtering by run properties, e.g. projects or tags.
	filter *Filter

	// Multi‑run metrics state.
	focus       *Focus
	metricsGrid *MetricsGrid

	// Per‑run streaming state keyed by runDirName.
	runsByKey map[string]*workspaceRun

	// Heartbeat for live runs.
	liveChan     chan tea.Msg
	heartbeatMgr *HeartbeatManager

	logger *observability.CoreLogger

	width, height int
}

func NewWorkspace(
	wandbDir string,
	cfg *ConfigManager,
	logger *observability.CoreLogger,
) *Workspace {
	logger.Info(fmt.Sprintf("workspace: creating new workspace for wandbDir: %s", wandbDir))

	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	// TODO: refactor to allow non-KeyValue items + make filtered ones pointers
	runs := PagedList{
		Title:  "Runs",
		Active: true,
	}
	runs.SetItemsPerPage(1)

	focus := NewFocus()

	// Heartbeat for all live workspace runs shares a single channel.
	ch := make(chan tea.Msg, 4096)
	hbInterval := cfg.HeartbeatInterval()
	logger.Info(fmt.Sprintf("workspace: heartbeat interval set to %v", hbInterval))

	runOverviewAnimState := NewAnimationState(true, SidebarMinWidth)

	// TODO: make sidebar visibility configurable.
	return &Workspace{
		runsAnimState: NewAnimationState(true, SidebarMinWidth),
		wandbDir:      wandbDir,
		config:        cfg,
		keyMap:        buildKeyMap(WorkspaceKeyBindings()),
		logger:        logger,
		runs:          runs,
		runOverview:   make(map[string]*RunOverview),
		runOverviewSidebar: NewRunOverviewSidebar(
			runOverviewAnimState, NewRunOverview(), SidebarSideRight),
		overviewPreloader: newRunOverviewPreloader(maxConcurrentPreloads),
		selectedRuns:      make(map[string]bool),
		focus:             focus,
		metricsGrid:       NewMetricsGrid(cfg, focus, logger),
		runsByKey:         make(map[string]*workspaceRun),
		liveChan:          ch,
		heartbeatMgr:      NewHeartbeatManager(hbInterval, ch, logger),
		filter:            NewFilter(),
	}
}

// SetSize updates the workspace dimensions and recomputes pagination capacity.
func (w *Workspace) SetSize(width, height int) {
	w.width, w.height = width, height

	// The runs list lives in the main content area (above the status bar).
	contentHeight := max(height-StatusBarHeight, 0)
	available := max(contentHeight-workspaceTopMarginLines-workspaceHeaderLines, 1)

	w.runs.SetItemsPerPage(available)
}

// Init wires up long‑running commands for the workspace.
func (w *Workspace) Init() tea.Cmd {
	var cmds []tea.Cmd

	// Start polling immediately; subsequent polls are scheduled by the handler.
	cmds = append(cmds, w.pollWandbDirCmd(0))

	// Start listening; the heartbeat manager will decide when to emit.
	if w.heartbeatMgr != nil && w.liveChan != nil {
		cmds = append(cmds, w.waitForLiveMsg)
	}

	return tea.Batch(cmds...)
}

func (w *Workspace) Update(msg tea.Msg) tea.Cmd {
	switch t := msg.(type) {
	case tea.WindowSizeMsg:
		w.handleWindowResize(t.Width, t.Height)

	case tea.KeyMsg:
		return w.handleKeyMsg(t)

	case tea.MouseMsg:
		return w.handleMouse(t)

	case WorkspaceRunsAnimationMsg:
		return w.handleRunsAnimation()

	case WorkspaceRunOverviewAnimationMsg:
		return w.handleRunOverviewAnimation()

	case WorkspaceRunInitMsg:
		return w.handleWorkspaceRunInit(t)

	case WorkspaceInitErrMsg:
		return w.handleWorkspaceInitErr(t)

	case WorkspaceRunDirsMsg:
		return w.handleWorkspaceRunDirs(t)

	case WorkspaceRunOverviewPreloadedMsg:
		return w.handleWorkspaceRunOverviewPreloaded(t)

	case WorkspaceChunkedBatchMsg:
		return w.handleWorkspaceChunkedBatch(t)

	case WorkspaceBatchedRecordsMsg:
		return w.handleWorkspaceBatchedRecords(t)

	case WorkspaceFileChangedMsg:
		return w.handleWorkspaceFileChanged(t)

	case HeartbeatMsg:
		return w.handleHeartbeat()
	}

	return nil
}

// View renders the runs section: header + paginated list with zebra rows.
func (w *Workspace) View() string {
	var cols []string

	if w.runsAnimState.IsVisible() {
		cols = append(cols, w.renderRunsList())
	}

	cols = append(cols, w.renderMetrics())

	if w.runOverviewSidebar.IsVisible() {
		cols = append(cols, w.renderRunOverview())
	}

	mainView := lipgloss.JoinHorizontal(lipgloss.Top, cols...)
	statusBar := w.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(w.width, w.height, lipgloss.Left, lipgloss.Top, fullView)
}

func (w *Workspace) dropRun(runKey string) {
	delete(w.selectedRuns, runKey)

	// If we removed the pinned run, unpin it.
	if w.pinnedRun == runKey {
		w.pinnedRun = ""
	}

	run, ok := w.runsByKey[runKey]
	if ok && run != nil {
		if w.metricsGrid != nil && run.wandbPath != "" {
			w.metricsGrid.RemoveSeries(run.wandbPath)
		}
		w.stopWatcher(run)
		if run.reader != nil {
			run.reader.Close()
		}
		delete(w.runsByKey, runKey)
	}

	// If no selected runs remain live, stop heartbeats.
	if w.heartbeatMgr != nil && !w.anyRunRunning() {
		w.heartbeatMgr.Stop()
	}
}

func (w *Workspace) renderRunsList() string {
	startIdx, endIdx := w.syncRunsPage()

	sidebarW := w.runsAnimState.Width()
	sidebarH := max(w.height-StatusBarHeight, 0)
	if sidebarW <= 1 || sidebarH <= 1 {
		return ""
	}
	contentWidth := max(sidebarW-leftSidebarContentPadding, 1)

	lines := w.renderRunLines(contentWidth)

	if len(lines) == 0 {
		lines = []string{"(no runs found)"}
	}

	contentLines := make([]string, 0, 1+len(lines))
	contentLines = append(contentLines, w.renderRunsListHeader(startIdx, endIdx))
	contentLines = append(contentLines, lines...)
	content := strings.Join(contentLines, "\n")

	// The runs sidebar border provides 1 blank line of padding at the top and bottom.
	innerW := max(sidebarW-runsSidebarBorderCols, 0)
	innerH := max(sidebarH-workspaceTopMarginLines, 0)

	styledContent := leftSidebarStyle.
		Width(innerW).
		Height(innerH).
		MaxWidth(innerW).
		MaxHeight(innerH).
		Render(content)

	boxed := leftSidebarBorderStyle.Render(styledContent)
	return lipgloss.Place(sidebarW, sidebarH, lipgloss.Left, lipgloss.Top, boxed)
}

func (w *Workspace) renderRunOverview() string {
	curKey := ""
	if cur, ok := w.runs.CurrentItem(); ok {
		curKey = cur.Key
	}

	ro := w.runOverview[curKey]
	w.runOverviewSidebar.SetRunOverview(ro)
	w.runOverviewSidebar.Sync()

	sidebarH := max(w.height-StatusBarHeight, 0)
	innerH := max(sidebarH-workspaceTopMarginLines, 0)

	return w.runOverviewSidebar.View(innerH)
}

func (w *Workspace) renderMetrics() string {
	contentWidth := max(w.width-w.runsAnimState.Width()-w.runOverviewSidebar.Width(), 0)
	contentHeight := max(w.height-StatusBarHeight, 0)

	if contentWidth <= 0 || contentHeight <= 0 {
		return ""
	}

	// No runs selected: show the logo + spherical cow without any header.
	if len(w.selectedRuns) == 0 || w.metricsGrid == nil {
		artStyle := lipgloss.NewStyle().
			Foreground(colorHeading).
			Bold(true)

		logoContent := lipgloss.JoinVertical(
			lipgloss.Center,
			artStyle.Render(wandbArt),
			artStyle.Render(sphericalCowInAVacuum),
			artStyle.Render(leetArt),
		)

		return lipgloss.Place(
			contentWidth,
			contentHeight,
			lipgloss.Center,
			lipgloss.Center,
			logoContent,
		)
	}

	// When we have selected runs, render the metrics grid.
	dims := w.metricsGrid.CalculateChartDimensions(contentWidth, contentHeight)
	return w.metricsGrid.View(dims)
}

func (w *Workspace) renderStatusBar() string {
	statusText := w.buildStatusText()
	helpText := w.buildHelpText()

	innerWidth := max(w.width-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(w.width).
		MaxWidth(w.width).
		Render(fullStatus)
}

func (w *Workspace) buildStatusText() string {
	// Metrics filter input mode has top priority.
	if w.metricsGrid != nil && w.metricsGrid.IsFilterMode() {
		return w.buildMetricsFilterStatus()
	}

	// Grid layout prompt (rows/cols) for metrics/system grids.
	if w.config != nil && w.config.IsAwaitingGridConfig() {
		return w.config.GridConfigStatus()
	}

	// When we add a run-filter input, it can be handled here similarly.
	return w.buildActiveStatus()
}

func (w *Workspace) buildMetricsFilterStatus() string {
	if w.metricsGrid == nil {
		return ""
	}
	return fmt.Sprintf(
		"Filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
		w.metricsGrid.FilterMode().String(),
		w.metricsGrid.FilterQuery(),
		string(mediumShadeBlock),
		w.metricsGrid.FilteredChartCount(),
		w.metricsGrid.ChartCount(),
	)
}

// buildActiveStatus summarizes the active filters and selection when no
// dedicated input mode (filter / grid config) is active.
func (w *Workspace) buildActiveStatus() string {
	var parts []string

	if w.metricsGrid != nil && w.metricsGrid.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"Filter (%s): %q [%d/%d] (/ to change, ctrl+l to clear)",
			w.metricsGrid.FilterMode().String(),
			w.metricsGrid.FilterQuery(),
			w.metricsGrid.FilteredChartCount(),
			w.metricsGrid.ChartCount(),
		))
	}

	totalRuns := len(w.runs.Items)
	if totalRuns > 0 {
		selected := len(w.selectedRuns)
		if selected == 0 {
			parts = append(parts, fmt.Sprintf("Runs: 0/%d selected", totalRuns))
		} else {
			parts = append(parts, fmt.Sprintf("Runs: %d/%d selected", selected, totalRuns))
		}
	}

	if w.pinnedRun != "" {
		parts = append(parts, fmt.Sprintf("Pinned: %s", w.pinnedRun))
	}

	if len(parts) == 0 {
		return w.wandbDir
	}
	return strings.Join(parts, " • ")
}

// buildHelpText builds the help text for the status bar.
func (w *Workspace) buildHelpText() string {
	// Hide help hint while any workspace-level filter / grid config is active.
	if w.IsFiltering() || w.config.IsAwaitingGridConfig() {
		return ""
	}
	return "h: help"
}

// IsFiltering reports whether any workspace-level filter UI is active.
func (w *Workspace) IsFiltering() bool {
	if w.metricsGrid != nil && w.metricsGrid.IsFilterMode() {
		return true
	}
	if w.filter.IsActive() {
		return true
	}
	return false
}

func (w *Workspace) updateLeftSidebarDimensions(rightSidebarVisible bool) {
	var calculatedWidth int

	if rightSidebarVisible {
		calculatedWidth = int(float64(w.width) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(w.width) * SidebarWidthRatio)
	}

	expandedWidth := clamp(calculatedWidth, SidebarMinWidth, SidebarMaxWidth)
	w.runsAnimState.SetExpandedWidth(expandedWidth)
}

// handleWindowResize handles window resize messages.
func (w *Workspace) handleWindowResize(width, height int) {
	w.SetSize(width, height)

	w.updateLeftSidebarDimensions(w.runOverviewSidebar.IsVisible())
	w.runOverviewSidebar.UpdateDimensions(w.width, w.runsAnimState.IsVisible())

	layout := w.computeViewports()
	w.metricsGrid.UpdateDimensions(layout.mainContentAreaWidth, layout.height)
}

// computeViewports returns (leftW, contentW, rightW, contentH).
func (w *Workspace) computeViewports() Layout {
	leftW, rightW := w.runsAnimState.Width(), w.runOverviewSidebar.Width()

	contentW := max(w.width-leftW-rightW, 1)
	contentH := max(w.height-StatusBarHeight, 1)

	return Layout{leftW, contentW, rightW, contentH}
}

// runsAnimationCmd returns a command to continue the animation on section toggle.
func (w *Workspace) runsAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return WorkspaceRunsAnimationMsg{}
	})
}

// runOverviewAnimationCmd returns a command to continue the animation on section toggle.
func (w *Workspace) runOverviewAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return WorkspaceRunOverviewAnimationMsg{}
	})
}

// syncRunsPage clamps the SectionView page/line against the current item set
// and returns the bounds of the visible slice [startIdx, endIdx).
func (w *Workspace) syncRunsPage() (startIdx, endIdx int) {
	total := len(w.runs.FilteredItems)
	itemsPerPage := w.runs.ItemsPerPage()

	if total == 0 || itemsPerPage <= 0 {
		w.runs.Home()
		return 0, 0
	}

	totalPages := (total + itemsPerPage - 1) / itemsPerPage
	if totalPages <= 0 {
		totalPages = 1
	}
	page := max(w.runs.CurrentPage(), 0)
	if page >= totalPages {
		page = totalPages - 1
	}

	startIdx = page * itemsPerPage
	endIdx = min(startIdx+itemsPerPage, total)

	maxLine := max(endIdx-startIdx-1, 0)
	line := min(max(w.runs.CurrentLine(), 0), maxLine)

	w.runs.SetPageAndLine(page, line)
	return startIdx, endIdx
}

// renderRunsListHeader renders "Runs [X‑Y of N]" (or "[N items]" for single‑page).
func (w *Workspace) renderRunsListHeader(startIdx, endIdx int) string {
	title := runOverviewSidebarSectionHeaderStyle.Render("Runs")

	total := len(w.runs.FilteredItems)
	info := ""

	if total > 0 {
		ipp := w.runs.ItemsPerPage()
		if ipp > 0 && total > ipp {
			// X‑Y are 1‑based indices for the current page.
			info = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total)
		} else {
			info = fmt.Sprintf(" [%d items]", total)
		}
	}

	return title + navInfoStyle.Render(info)
}

// renderRunLines renders the visible slice with zebra background and selection.
func (w *Workspace) renderRunLines(contentWidth int) []string {
	itemsPerPage := w.runs.ItemsPerPage()
	startIdx := w.runs.CurrentPage() * itemsPerPage
	endIdx := min(startIdx+itemsPerPage, len(w.runs.FilteredItems))

	lines := make([]string, 0, endIdx-startIdx)
	selectedLine := w.runs.CurrentLine()

	for i := startIdx; i < endIdx; i++ {
		idxOnPage := i - startIdx
		item := w.runs.FilteredItems[i]

		// Determine row style
		style := evenRunStyle
		if idxOnPage%2 == 1 {
			style = oddRunStyle
		}
		if idxOnPage == selectedLine {
			if w.runs.Active {
				style = selectedRunStyle
			} else {
				style = selectedRunInactiveStyle
			}
		}

		// TODO: Stable mapping for consistent colors: refactor and clean up.
		runKey := item.Key
		runID := extractRunID(runKey)
		runPath := filepath.Join(w.wandbDir, runKey, "run-"+runID+".wandb")

		graphColors := GraphColors(w.config.ColorScheme())
		colorIdx := colorIndex(runPath, len(graphColors))

		isSelected := w.selectedRuns[runKey]
		isPinned := w.pinnedRun == runKey

		// Determine marker
		mark := " "
		if isSelected {
			mark = "●"
		}
		if isPinned {
			mark = "▶" // ✪ ◎ ▲ ▶ ◉ ▬ ◆ ▣ ■
		}

		// Render prefix without background
		prefix := lipgloss.NewStyle().Foreground(graphColors[colorIdx]).Render(mark + " ")
		prefixWidth := lipgloss.Width(prefix)

		// Apply subtle muting to unselected/unpinned runs
		nameStyle := style
		if !isSelected && !isPinned {
			nameStyle = nameStyle.Foreground(colorText)
		}

		// Render name with background and optional muting
		nameWidth := max(contentWidth-prefixWidth, 1)
		name := nameStyle.Render(truncateValue(runKey, nameWidth))

		// Pad the styled name to fill remaining width
		paddingNeeded := contentWidth - prefixWidth - lipgloss.Width(name)
		padding := style.Render(strings.Repeat(" ", max(paddingNeeded, 0)))

		lines = append(lines, prefix+name+padding)
	}

	return lines
}

// SelectedRunWandbFile returns the full path to the .wandb file for the selected run.
//
// Returns empty string if no run is selected.
func (w *Workspace) SelectedRunWandbFile() string {
	total := len(w.runs.FilteredItems)
	if total == 0 {
		return ""
	}

	startIdx := w.runs.CurrentPage() * w.runs.ItemsPerPage()
	idx := startIdx + w.runs.CurrentLine()
	if idx < 0 || idx >= total {
		return ""
	}

	return runWandbFile(w.wandbDir, w.runs.FilteredItems[idx].Key)
}

// refreshPinnedRun ensures the pinned run (if any) is drawn on top in all charts.
func (w *Workspace) refreshPinnedRun() {
	if w.metricsGrid == nil || w.pinnedRun == "" {
		return
	}
	run, ok := w.runsByKey[w.pinnedRun]
	if !ok || run == nil || run.wandbPath == "" {
		return
	}
	w.metricsGrid.PromoteSeriesToTop(run.wandbPath)
}
