package leet

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

const symonHeaderLines = 1

// Symon is a standalone full-screen system metrics monitor.
type Symon struct {
	ctx    context.Context
	cancel context.CancelFunc

	config *ConfigManager
	keyMap map[string]func(*Symon, tea.KeyPressMsg) tea.Cmd
	focus  *Focus
	grid   *SystemMetricsGrid
	help   *HelpModel

	width  int
	height int

	sampler *SymonSampler
	logger  *observability.CoreLogger

	shouldRestart bool
}

func NewSymon(cfg *ConfigManager, logger *observability.CoreLogger) *Symon {
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}
	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	ctx, cancel := context.WithCancel(context.Background())
	focus := NewFocus()
	rows, cols := cfg.SymonGrid()
	help := NewHelp()
	help.SetMode(viewModeSymon)

	return &Symon{
		ctx:    ctx,
		cancel: cancel,
		config: cfg,
		keyMap: buildKeyMap(SymonKeyBindings()),
		focus:  focus,
		grid: NewSystemMetricsGrid(
			MinMetricChartWidth*cols,
			MinMetricChartHeight*rows,
			cfg,
			cfg.SymonGrid,
			focus,
			NewFilter(),
			logger,
		),
		help:    help,
		sampler: NewSymonSampler(logger),
		logger:  logger,
	}
}

func (s *Symon) Init() tea.Cmd {
	return s.sampleNowCmd()
}

func (s *Symon) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if ws, ok := msg.(tea.WindowSizeMsg); ok {
		s.width, s.height = ws.Width, ws.Height
		s.help.SetSize(ws.Width, ws.Height)
		s.resizeGrid()
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

	case StatsMsg:
		for metricName, value := range msg.Metrics {
			s.grid.AddDataPoint(metricName, msg.Timestamp, value)
		}
		s.resizeGrid()
		cmd := s.sampleLaterCmd()
		return s, cmd

	default:
		return s, nil
	}
}

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

func (s *Symon) Cleanup() {
	if s.cancel != nil {
		s.cancel()
	}
	if s.sampler != nil {
		s.sampler.Cleanup()
	}
}

func (s *Symon) ShouldRestart() bool {
	return s.shouldRestart
}

func (s *Symon) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	if s.isAwaitingUserInput() {
		return false, nil
	}

	if km, ok := msg.(tea.KeyPressMsg); ok {
		s.help.SetMode(viewModeSymon)
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

func (s *Symon) handlePrevPage(tea.KeyPressMsg) tea.Cmd {
	s.grid.Navigate(-1)
	return nil
}

func (s *Symon) handleNextPage(tea.KeyPressMsg) tea.Cmd {
	s.grid.Navigate(1)
	return nil
}

func (s *Symon) handleToggleFocusedChartLogY(tea.KeyPressMsg) tea.Cmd {
	s.grid.toggleFocusedChartLogY()
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
	if s.focus.Type == FocusSystemChart {
		s.focus.Reset()
	}
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

func (s *Symon) handleMouse(msg tea.MouseMsg) tea.Cmd {
	mouse := msg.Mouse()
	alt := mouse.Mod == tea.ModAlt

	if mouse.Y < symonHeaderLines || mouse.Y >= s.height-StatusBarHeight {
		if _, ok := msg.(tea.MouseClickMsg); ok {
			s.grid.ClearFocus()
		}
		return nil
	}

	adjustedX := mouse.X
	adjustedY := mouse.Y - symonHeaderLines
	if adjustedX < 0 || adjustedY < 0 {
		return nil
	}

	dims := s.grid.calculateChartDimensions()
	row := adjustedY / dims.CellHWithPadding
	col := adjustedX / dims.CellWWithPadding

	switch m := msg.(type) {
	case tea.MouseClickMsg:
		switch m.Button {
		case tea.MouseLeft:
			s.grid.HandleMouseClick(row, col)
		case tea.MouseRight:
			s.grid.StartInspection(adjustedX, row, col, dims, alt)
		}
	case tea.MouseMotionMsg:
		if m.Button == tea.MouseRight {
			s.grid.UpdateInspection(adjustedX, row, col, dims)
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
	return nil
}

func (s *Symon) renderMainView() string {
	header := renderSystemMetricsHeader(s.width, "System Metrics", "", s.grid)
	bodyHeight := max(s.height-StatusBarHeight-symonHeaderLines, 0)
	body := renderSystemMetricsBody(
		s.width,
		bodyHeight,
		s.grid,
		"Collecting system metrics...",
		"No matching system metrics.",
	)
	statusBar := s.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, header, body, statusBar)
	return lipgloss.Place(s.width, s.height, lipgloss.Left, lipgloss.Top, fullView)
}

func (s *Symon) renderStatusBar() string {
	statusText := s.buildStatusText()
	helpText := s.buildHelpText()

	innerWidth := max(s.width-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	return statusBarStyle.
		Width(s.width).
		MaxWidth(s.width).
		Render(statusText + rightAligned)
}

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
	if s.config.IsAwaitingGridConfig() {
		return s.config.GridConfigStatus()
	}
	return s.buildActiveStatus()
}

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

func (s *Symon) renderHelpScreen() string {
	helpView := s.help.View().Content

	helpText := "h: help"
	spaceForHelp := max(s.width-2*StatusBarPadding, 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	statusBar := statusBarStyle.
		Width(s.width).
		MaxWidth(s.width).
		Render(rightAligned)

	content := lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
	return lipgloss.Place(s.width, s.height, lipgloss.Left, lipgloss.Top, content)
}

func (s *Symon) resizeGrid() {
	if s.width <= 0 || s.height <= 0 {
		return
	}
	s.grid.Resize(s.width, max(s.height-StatusBarHeight-symonHeaderLines, 1))
}

func (s *Symon) isAwaitingUserInput() bool {
	return s.grid.IsFilterMode() || s.config.IsAwaitingGridConfig()
}

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
