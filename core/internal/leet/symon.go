package leet

import (
	"context"
	"fmt"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// symonHeaderLines is the number of rows reserved above the chart guides for the
// shared system metrics header.
const symonHeaderLines = 1

// SymonParams configures the standalone SYMON view.
type SymonParams struct {
	// Config provides grid dimensions and chart styling. Nil uses the default
	// on-disk LEET configuration.
	Config *ConfigManager

	// SamplingInterval controls how frequently the sampler collects a new system
	// metrics snapshot. Values less than or equal to zero use the default.
	SamplingInterval time.Duration

	// Logger receives debug logs and captured errors. Nil uses a no-op logger.
	Logger *observability.CoreLogger
}

// Symon is a standalone full-screen system metrics monitor.
//
// Unlike the run view's system metrics pane, Symon is not tied to a specific
// run. It owns its own chart guides, filter state, help overlay, and live sampler
// while reusing the shared charting and monitor plumbing from the rest of LEET.
type Symon struct {
	ctx    context.Context
	cancel context.CancelFunc

	config   *ConfigManager
	keyMap   map[string]func(*Symon, tea.KeyPressMsg) tea.Cmd
	focus    *Focus
	focusMgr *FocusManager
	grid     *SystemMetricsGrid
	sidebar  *symonSidebar
	help     *HelpModel

	// drag owns mouse resizing of the sidebar border.
	drag paneDragger

	width  int
	height int

	// hostname titles the header; latest holds the most recent sample for
	// the values shown outside the charts.
	hostname string
	latest   map[string]float64

	sampler *SymonSampler
	logger  *observability.CoreLogger

	shouldRestart bool
}

func NewSymon(params SymonParams) *Symon {
	logger := params.Logger
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}

	cfg := params.Config
	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	ctx, cancel := context.WithCancel(context.Background())
	focus := NewFocus()
	rows, cols := cfg.SymonGrid()
	help := NewHelp()
	help.SetMode(viewModeSymon)

	grid := NewSystemMetricsGrid(
		MinMetricChartWidth*cols,
		MinMetricChartHeight*rows,
		cfg,
		cfg.SymonGrid,
		focus,
		NewFilter(),
		logger,
	)
	grid.SetChartRank(symonChartRank)

	hostname, err := os.Hostname()
	if err != nil {
		hostname = "System Metrics"
	}

	s := &Symon{
		ctx:      ctx,
		cancel:   cancel,
		config:   cfg,
		keyMap:   buildKeyMap(SymonKeyBindings()),
		focus:    focus,
		grid:     grid,
		sidebar:  newSymonSidebar(cfg),
		help:     help,
		hostname: hostname,
		sampler: NewSymonSampler(SymonSamplerParams{
			Interval: params.SamplingInterval,
			Logger:   logger,
		}),
		logger: logger,
	}
	s.drag = paneDragger{
		saved:    cfg.SymonLayout,
		persist:  cfg.SetSymonLayout,
		relayout: s.resizeGrid,
		logger:   logger,
	}
	s.focusMgr = NewFocusManager([]FocusRegionDef{
		{
			Target:     FocusTargetProcessList,
			Available:  func() bool { return s.sidebarWidth() > 0 && len(s.sidebar.procs.FilteredItems) > 0 },
			Activate:   func(int) { s.sidebar.procs.Active = true },
			Deactivate: func() { s.sidebar.procs.Active = false },
		},
		{
			Target:     FocusTargetSystemMetrics,
			Available:  func() bool { return s.grid.ChartCount() > 0 },
			Activate:   func(int) { s.grid.NavigateFocus(0, 0) },
			Deactivate: s.grid.ClearFocus,
		},
	})
	return s
}

// symonChartOrder lists the charts that open the first page by base key,
// most important first. Other charts follow in title order.
var symonChartOrder = []string{
	"cpu.cpu_percent",
	"memory_percent",
	"swap.used_percent",
	"network.recvBps",
	"network.sentBps",
	"disk.io_rate_per_device",
	"cpu.avg_temp",
	"gpu.gpu",
	"gpu.memoryAllocated",
	"gpu.temp",
	"gpu.powerWatts",
	"cpu.pcpu_percent",
	"cpu.ecpu_percent",
	"system.powerWatts",
}

func symonChartRank(baseKey string) int {
	if i := slices.Index(symonChartOrder, baseKey); i >= 0 {
		return i
	}
	return len(symonChartOrder)
}

// Init starts the initial sampling pass and the host probe.
func (s *Symon) Init() tea.Cmd {
	return tea.Batch(tea.RequestBackgroundColor, s.sampleNowCmd(), s.probeCmd())
}

// Update handles resize events, help/restart shortcuts, user input, and live
// samples from the sampler.
func (s *Symon) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if ws, ok := msg.(tea.WindowSizeMsg); ok {
		s.width, s.height = ws.Width, ws.Height
		s.help.SetSize(ws.Width, ws.Height)
		s.resizeGrid()
	}

	if bgMsg, ok := msg.(tea.BackgroundColorMsg); ok {
		SetDarkBackground(bgMsg.IsDark())
		SetTerminalBackground(bgMsg)
	}

	if handled, cmd := s.handleHelp(msg); handled {
		return s, cmd
	}
	if handled, cmd := s.handleRestart(msg); handled {
		return s, cmd
	}

	switch msg := msg.(type) {
	case tea.KeyPressMsg:
		if s.grid.IsFilterMode() {
			s.grid.handleFilterKey(msg)
			return s, nil
		}
		if s.sidebar.filter.IsActive() {
			s.sidebar.handleProcessFilterKey(msg)
			s.focusMgr.Resolve()
			return s, nil
		}
		if s.config.IsAwaitingGridConfig() {
			s.handleConfigNumberKey(msg)
			return s, nil
		}
		if handler, ok := s.keyMap[normalizeKey(msg.String())]; ok {
			return s, handler(s, msg)
		}
		return s, nil

	case tea.MouseMsg:
		cmd := s.handleMouse(msg)
		return s, cmd

	case SymonSampleMsg:
		s.latest = msg.Metrics
		s.sidebar.setProcesses(msg.Processes)
		s.grid.ProcessStats(msg.StatsMsg)
		s.grid.drawVisible()
		s.focusMgr.Resolve()
		cmd := s.sampleLaterCmd()
		return s, cmd

	case SymonProbeMsg:
		s.sidebar.probe = msg
		return s, nil

	default:
		return s, nil
	}
}

// View renders the standalone system monitor or its help overlay.
func (s *Symon) View() tea.View {
	if s.width == 0 || s.height == 0 {
		return tea.NewView("Loading...")
	}

	var content string
	if s.help.IsActive() {
		content = s.renderHelpScreen()
	} else {
		content = s.renderMainView()
	}

	view := tea.NewView(content)
	view.WindowTitle = "wandb leet symon"
	view.AltScreen = true
	view.MouseMode = tea.MouseModeCellMotion
	return view
}

// Cleanup stops outstanding sampling work and releases sampler-owned resources.
func (s *Symon) Cleanup() {
	if s.cancel != nil {
		s.cancel()
	}
	if s.sampler != nil {
		s.sampler.Cleanup()
	}
}

// ShouldRestart reports whether the user requested a full-process restart.
func (s *Symon) ShouldRestart() bool {
	return s.shouldRestart
}

// --------------------------------------------------------------------
// Input helpers
// --------------------------------------------------------------------

// handleHelp toggles the help overlay and routes input to it while active.
func (s *Symon) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	if s.isAwaitingUserInput() {
		return false, nil
	}

	// The help mode is fixed to viewModeSymon at construction.
	if km, ok := msg.(tea.KeyPressMsg); ok {
		switch km.Code {
		case 'h', '?':
			s.help.Toggle()
			return true, nil
		}
	}

	if s.help.IsActive() {
		switch msg.(type) {
		case tea.KeyPressMsg, tea.MouseMsg:
			updated, cmd := s.help.Update(msg)
			s.help = updated
			return true, cmd
		}
	}
	return false, nil
}

// handleRestart quits the program after marking the model for restart.
func (s *Symon) handleRestart(msg tea.Msg) (bool, tea.Cmd) {
	km, ok := msg.(tea.KeyPressMsg)
	if !ok || km.String() != "alt+r" {
		return false, nil
	}

	s.logger.Debug("symon: restart requested")
	s.shouldRestart = true
	return true, tea.Quit
}

func (s *Symon) handleQuit(tea.KeyPressMsg) tea.Cmd {
	return tea.Quit
}

// handleTab moves focus between the process list and the chart grid.
func (s *Symon) handleTab(msg tea.KeyPressMsg) tea.Cmd {
	direction := 1
	if msg.String() == "shift+tab" {
		direction = -1
	}
	s.focusMgr.Tab(direction)
	return nil
}

func (s *Symon) processListFocused() bool {
	return s.focusMgr.IsTarget(FocusTargetProcessList)
}

func (s *Symon) handlePrevPage(tea.KeyPressMsg) tea.Cmd {
	if s.processListFocused() {
		s.sidebar.procs.PageUp()
		return nil
	}
	s.grid.Navigate(-1)
	return nil
}

func (s *Symon) handleNextPage(tea.KeyPressMsg) tea.Cmd {
	if s.processListFocused() {
		s.sidebar.procs.PageDown()
		return nil
	}
	s.grid.Navigate(1)
	return nil
}

func (s *Symon) handleNavHome(tea.KeyPressMsg) tea.Cmd {
	if s.processListFocused() {
		s.sidebar.procs.Home()
		return nil
	}
	s.grid.NavigateHome()
	return nil
}

func (s *Symon) handleNavEnd(tea.KeyPressMsg) tea.Cmd {
	if s.processListFocused() {
		s.sidebar.procs.End()
		return nil
	}
	s.grid.NavigateEnd()
	return nil
}

// handleGridNav moves the process cursor while the list has focus, and
// the chart focus otherwise. Page, home and end keys have their own
// handlers.
func (s *Symon) handleGridNav(msg tea.KeyPressMsg) tea.Cmd {
	intent := DecodeNav(msg)
	if s.processListFocused() {
		switch intent {
		case NavIntentUp:
			s.sidebar.procs.Up()
		case NavIntentDown:
			s.sidebar.procs.Down()
		}
		return nil
	}

	switch intent {
	case NavIntentUp:
		s.grid.NavigateFocus(-1, 0)
	case NavIntentDown:
		s.grid.NavigateFocus(1, 0)
	case NavIntentLeft:
		s.grid.NavigateFocus(0, -1)
	case NavIntentRight:
		s.grid.NavigateFocus(0, 1)
	}
	if s.focus.Type == FocusSystemChart {
		s.focusMgr.AdoptTarget(FocusTargetSystemMetrics)
	}
	return nil
}

func (s *Symon) handleEnterProcessFilter(tea.KeyPressMsg) tea.Cmd {
	s.sidebar.filter.Activate()
	return nil
}

func (s *Symon) handleClearProcessFilter(tea.KeyPressMsg) tea.Cmd {
	s.sidebar.clearProcessFilter()
	s.focusMgr.Resolve()
	return nil
}

func (s *Symon) handleCycleFocusedChartMode(tea.KeyPressMsg) tea.Cmd {
	s.grid.cycleFocusedChartMode()
	return nil
}

func (s *Symon) handleToggleFocusedChartLogY(msg tea.KeyPressMsg) tea.Cmd {
	return s.handleCycleFocusedChartMode(msg)
}

func (s *Symon) handleCycleChartGuides(tea.KeyPressMsg) tea.Cmd {
	guides := nextChartGuides(s.config.ChartGuides())
	if err := s.config.SetChartGuides(guides); err != nil {
		s.logger.Error(fmt.Sprintf("symon: failed to save chart guides: %v", err))
	}
	s.grid.SetChartGuides(guides)
	return nil
}

func (s *Symon) handleEnterSystemMetricsFilter(tea.KeyPressMsg) tea.Cmd {
	s.grid.EnterFilterMode()
	s.grid.ApplyFilter()
	return nil
}

func (s *Symon) handleClearSystemMetricsFilter(tea.KeyPressMsg) tea.Cmd {
	if s.grid.FilterQuery() != "" {
		s.grid.ClearFilter()
	}
	if !s.processListFocused() {
		s.grid.NavigateFocus(0, 0)
	}
	return nil
}

func (s *Symon) handleToggleSidebar(tea.KeyPressMsg) tea.Cmd {
	s.sidebar.visible = !s.sidebar.visible
	if err := s.config.SetSymonSidebarVisible(s.sidebar.visible); err != nil {
		s.logger.Error(fmt.Sprintf("symon: failed to save sidebar visibility: %v", err))
	}
	s.resizeGrid()
	s.focusMgr.Resolve()
	return nil
}

// handleResetLayout restores the default sidebar width.
func (s *Symon) handleResetLayout(tea.KeyPressMsg) tea.Cmd {
	s.drag.reset()
	return nil
}

func (s *Symon) handleToggleProcessSort(tea.KeyPressMsg) tea.Cmd {
	s.sidebar.sortByMemory = !s.sidebar.sortByMemory
	s.sidebar.sortProcesses()
	return nil
}

func (s *Symon) handleToggleSidebar(tea.KeyPressMsg) tea.Cmd {
	s.sidebar.visible = !s.sidebar.visible
	if err := s.config.SetSymonSidebarVisible(s.sidebar.visible); err != nil {
		s.logger.Error(fmt.Sprintf("symon: failed to save sidebar visibility: %v", err))
	}
	s.resizeGrid()
	return nil
}

func (s *Symon) handleToggleProcessSort(tea.KeyPressMsg) tea.Cmd {
	s.sidebar.sortByMemory = !s.sidebar.sortByMemory
	return nil
}

func (s *Symon) handleConfigSystemCols(tea.KeyPressMsg) tea.Cmd {
	s.config.SetPendingGridConfig(gridConfigSymonCols)
	return nil
}

func (s *Symon) handleConfigSystemRows(tea.KeyPressMsg) tea.Cmd {
	s.config.SetPendingGridConfig(gridConfigSymonRows)
	return nil
}

// handleConfigNumberKey applies a pending grid-size edit triggered by the
// configuration hotkeys.
func (s *Symon) handleConfigNumberKey(msg tea.KeyPressMsg) {
	defer s.config.SetPendingGridConfig(gridConfigNone)

	if msg.String() == "esc" {
		return
	}

	num, err := strconv.Atoi(msg.String())
	if err != nil {
		return
	}
	if _, err := s.config.SetGridConfig(num); err != nil {
		s.logger.Error(fmt.Sprintf("symon: failed to update grid config: %v", err))
		return
	}
	s.resizeGrid()
}

// handleMouse resizes the sidebar on border drags and maps other mouse
// events in the terminal coordinate space onto the system metrics grid.
func (s *Symon) handleMouse(msg tea.MouseMsg) tea.Cmd {
	sidebarWidth := s.sidebarWidth()
	layout := Layout{
		leftSidebarWidth:       sidebarWidth,
		mainContentAreaWidth:   max(s.width-sidebarWidth, 0),
		totalContentAreaHeight: max(s.height-StatusBarHeight, 0),
	}
	if s.drag.handleMouse(msg, layout, dragTargets{
		width:        s.width,
		height:       s.height,
		leftExpanded: sidebarWidth > 0,
	}) {
		return nil
	}

	mouse := msg.Mouse()
	_, clicked := msg.(tea.MouseClickMsg)

	if mouse.X < sidebarWidth && mouse.Y < s.height-StatusBarHeight {
		if clicked {
			s.sidebar.selectProcessAt(mouse.Y)
			s.focusMgr.SetTarget(FocusTargetProcessList, 1)
		}
		return nil
	}
	if mouse.Y < symonHeaderLines || mouse.Y >= s.height-StatusBarHeight {
		if clicked {
			s.focusMgr.ClearAll()
		}
		return nil
	}

	adjustedX := mouse.X - sidebarWidth - ContentPadding
	adjustedY := mouse.Y - symonHeaderLines
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	dims := s.grid.calculateChartDimensions()
	if dims.CellHWithPadding == 0 || dims.CellWWithPadding == 0 {
		return nil
	}
	s.handleGridMouse(msg, adjustedX, adjustedY, dims)
	return nil
}

// handleGridMouse focuses, inspects and zooms charts at grid coordinates.
func (s *Symon) handleGridMouse(msg tea.MouseMsg, adjustedX, adjustedY int, dims GridDims) {
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding
	alt := msg.Mouse().Mod == tea.ModAlt

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			if s.grid.HandleMouseClick(row, col) {
				s.focusMgr.AdoptTarget(FocusTargetSystemMetrics)
			} else {
				s.focusMgr.ClearAll()
			}
		case tea.MouseRight:
			s.grid.StartInspection(adjustedX, adjustedY, row, col, dims, alt)
			s.focusMgr.AdoptTarget(FocusTargetSystemMetrics)
		}
	case tea.MouseMotionMsg:
		if m.Button == tea.MouseRight {
			s.grid.UpdateInspection(adjustedX, adjustedY, row, col, dims)
		}
	case tea.MouseReleaseMsg:
		if m.Button == tea.MouseRight {
			s.grid.EndInspection()
		}
	case tea.MouseWheelMsg:
		switch m.Button {
		case tea.MouseWheelUp:
			s.grid.HandleWheel(adjustedX, row, col, dims, true)
		case tea.MouseWheelDown:
			s.grid.HandleWheel(adjustedX, row, col, dims, false)
		}
	}
}

// --------------------------------------------------------------------
// Rendering helpers
// --------------------------------------------------------------------

// renderMainView renders the sidebar, the header and system metrics grid,
// and the status bar.
func (s *Symon) renderMainView() string {
	sidebarWidth := s.sidebarWidth()
	contentHeight := max(s.height-StatusBarHeight, 0)
	innerW := max(s.width-sidebarWidth-ContentPaddingCols, 0)

	header := symonContainerStyle.Render(
		renderSystemMetricsHeader(innerW, s.hostname, s.hostStatus(), s.grid))
	body := symonContainerStyle.Render(renderSystemMetricsBody(
		innerW,
		max(contentHeight-symonHeaderLines, 0),
		s.grid,
		"Collecting system metrics...",
		"No matching system metrics.",
	))
	mainView := lipgloss.JoinVertical(lipgloss.Left, header, body)
	if sidebarWidth > 0 {
		sidebar := s.sidebar.View(sidebarWidth, contentHeight, s.latest,
			s.drag.cue().boundary == dragBoundaryLeftSidebar)
		mainView = lipgloss.JoinHorizontal(lipgloss.Top, sidebar, mainView)
	}
	statusBar := s.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(s.width, s.height, lipgloss.Left, lipgloss.Top, fullView)
}

// hostStatus summarizes the host's uptime and load average from the latest
// sample.
func (s *Symon) hostStatus() string {
	var parts []string
	if uptime, ok := s.latest["system.uptime"]; ok {
		parts = append(parts, "up "+formatUptime(time.Duration(uptime)*time.Second))
	}
	load1, ok1 := s.latest["system.load1"]
	load5, ok5 := s.latest["system.load5"]
	load15, ok15 := s.latest["system.load15"]
	if ok1 && ok5 && ok15 {
		parts = append(parts, fmt.Sprintf("load %.2f %.2f %.2f", load1, load5, load15))
	}
	return strings.Join(parts, " • ")
}

// formatUptime renders a duration the way uptime(1) does: days and hours,
// hours and minutes, or minutes.
func formatUptime(d time.Duration) string {
	days := int(d.Hours()) / 24
	hours := int(d.Hours()) % 24
	minutes := int(d.Minutes()) % 60
	switch {
	case days > 0:
		return fmt.Sprintf("%dd %dh", days, hours)
	case hours > 0:
		return fmt.Sprintf("%dh %dm", hours, minutes)
	default:
		return fmt.Sprintf("%dm", minutes)
	}
}

// renderStatusBar renders the left-aligned state summary and right-aligned help
// hint shown at the bottom of the screen.
func (s *Symon) renderStatusBar() string {
	return s.renderStatusBarWith(s.buildStatusText(), s.buildHelpText())
}

// renderStatusBarWith lays out the W&B LEET badge, the status text and the
// right-aligned help hint across the terminal width.
func (s *Symon) renderStatusBarWith(statusText, helpText string) string {
	badge := statusBarBadgeStyle.Render(statusBarBadge)
	barWidth := max(s.width-lipgloss.Width(badge), 0)

	innerWidth := max(barWidth-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	bar := statusBarStyle.
		Width(barWidth).
		MaxWidth(barWidth).
		Render(statusText + rightAligned)
	return lipgloss.JoinHorizontal(lipgloss.Top, badge, bar)
}

// buildStatusText chooses the status-bar text for the current interaction mode.
func (s *Symon) buildStatusText() string {
	if s.grid.IsFilterMode() {
		return fmt.Sprintf(
			"System filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
			s.grid.FilterMode().String(),
			s.grid.FilterQuery(),
			string(mediumShadeBlock),
			s.grid.FilteredChartCount(),
			s.grid.ChartCount(),
		)
	}
	if s.sidebar.filter.IsActive() {
		return fmt.Sprintf(
			"Process filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
			s.sidebar.filter.Mode().String(),
			s.sidebar.filter.Query(),
			string(mediumShadeBlock),
			len(s.sidebar.procs.FilteredItems),
			len(s.sidebar.procs.Items),
		)
	}
	if s.config.IsAwaitingGridConfig() {
		return s.config.GridConfigStatus()
	}
	return s.buildActiveStatus()
}

// buildActiveStatus summarizes the current chart count, filter, and focused
// chart details while the user is not editing text input.
func (s *Symon) buildActiveStatus() string {
	parts := make([]string, 0, 4)
	if count := s.grid.ChartCount(); count > 0 {
		parts = append(parts, fmt.Sprintf("%d charts", count))
	}
	if s.grid.IsFiltering() {
		parts = append(parts, fmt.Sprintf(
			"System filter (%s): %q [%d/%d] (\\ to change, ctrl+\\ to clear)",
			s.grid.FilterMode().String(),
			s.grid.FilterQuery(),
			s.grid.FilteredChartCount(),
			s.grid.ChartCount(),
		))
	}
	if query := s.sidebar.filter.Query(); query != "" {
		parts = append(parts, fmt.Sprintf(
			"Process filter (%s): %q [%d/%d] (f to change, ctrl+f to clear)",
			s.sidebar.filter.Mode().String(),
			query,
			len(s.sidebar.procs.FilteredItems),
			len(s.sidebar.procs.Items),
		))
	}
	if title := s.grid.FocusedChartTitle(); title != "" {
		parts = append(parts, title)
		if viewMode := s.grid.FocusedChartViewModeLabel(); viewMode != "" {
			parts = append(parts, viewMode)
		}
		if scaleLabel := s.grid.FocusedChartScaleLabel(); scaleLabel != "" {
			parts = append(parts, scaleLabel)
		}
	}
	if len(parts) == 0 {
		return "symon"
	}
	return "symon • " + strings.Join(parts, " • ")
}

func (s *Symon) buildHelpText() string {
	if s.isAwaitingUserInput() {
		return ""
	}
	return "h: help"
}

// renderHelpScreen renders the full-screen help overlay with the standard LEET
// status bar treatment.
func (s *Symon) renderHelpScreen() string {
	helpView := s.help.View().Content
	statusBar := s.renderStatusBarWith("symon", "h: help")

	content := lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
	return lipgloss.Place(s.width, s.height, lipgloss.Left, lipgloss.Top, content)
}

// resizeGrid keeps the chart guides sized to the currently available content
// area below the header and above the status bar.
func (s *Symon) resizeGrid() {
	if s.width <= 0 || s.height <= 0 {
		return
	}
	s.grid.Resize(
		max(s.width-s.sidebarWidth()-ContentPaddingCols, 0),
		max(s.height-StatusBarHeight-symonHeaderLines, 1),
	)
}

// sidebarWidth returns the sidebar's width: the dragged fraction of the
// terminal or the golden-ratio default, and zero when the sidebar is hidden
// or the charts would not fit beside it.
func (s *Symon) sidebarWidth() int {
	if !s.sidebar.visible {
		return 0
	}
	w := expandedSidebarWidth(s.width, false, s.drag.overrides().LeftSidebar)
	w, _ = fitSidebarWidths(s.width, w, 0)
	return w
}

// isAwaitingUserInput reports whether a child component currently owns free-form
// keyboard input.
func (s *Symon) isAwaitingUserInput() bool {
	return s.grid.IsFilterMode() || s.sidebar.filter.IsActive() || s.config.IsAwaitingGridConfig()
}

// probeCmd gathers the host facts shown in the sidebar.
func (s *Symon) probeCmd() tea.Cmd {
	ctx := s.ctx
	return func() tea.Msg {
		return s.sampler.Probe(ctx)
	}
}

// sampleNowCmd triggers an immediate sampling pass.
func (s *Symon) sampleNowCmd() tea.Cmd {
	ctx := s.ctx
	return func() tea.Msg {
		select {
		case <-ctx.Done():
			return nil
		default:
			return s.sampler.Sample()
		}
	}
}

// sampleLaterCmd schedules the next sampling pass after the configured interval.
//
// The tick is started only after the current sample has been processed, which
// avoids overlapping sampling work when a collector is slow.
func (s *Symon) sampleLaterCmd() tea.Cmd {
	ctx := s.ctx
	interval := s.sampler.Interval()
	return tea.Tick(interval, func(time.Time) tea.Msg {
		select {
		case <-ctx.Done():
			return nil
		default:
			return s.sampler.Sample()
		}
	})
}
