package leet

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/wandb/wandb/core/internal/observability"
)

type viewMode int

const (
	viewModeUndefined viewMode = iota
	viewModeWorkspace
	viewModeRun
)

const latestRunLinkName = "latest-run"

type Model struct {
	mode      viewMode
	workspace *Workspace
	run       *Run

	width, height int

	help *HelpModel

	config *ConfigManager
	logger *observability.CoreLogger
}

type ModelParams struct {
	WandbDir string
	RunFile  string
	Config   *ConfigManager
	Logger   *observability.CoreLogger
}

func NewModel(params ModelParams) *Model {
	if params.Config == nil {
		params.Config = NewConfigManager(leetConfigPath(), params.Logger)
	}

	if params.RunFile == "" && params.Config.StartupMode() == StartupModeSingleRunLatest {
		latest, err := wandbFileFromLatestRunLink(params.WandbDir)
		if err != nil {
			params.Logger.Error(fmt.Sprintf("model: failed to find latest run: %v", err))
		}
		if latest != "" {
			params.RunFile = latest
		}
	}

	m := &Model{
		mode:      viewModeWorkspace,
		workspace: NewWorkspace(params.WandbDir, params.Config, params.Logger),
		help:      NewHelp(),
		config:    params.Config,
		logger:    params.Logger,
	}

	// If a run file is specified, start in single-run mode.
	if params.RunFile != "" {
		m.run = NewRun(params.RunFile, params.Config, params.Logger)
		m.mode = viewModeRun
	}

	return m
}

func (m *Model) Init() tea.Cmd {
	cmds := []tea.Cmd{windowTitleCmd()}

	// Workspace always exists; initialize its long‑running commands.
	if m.workspace != nil {
		if cmd := m.workspace.Init(); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	if m.mode == viewModeRun && m.run != nil {
		cmds = append(cmds, m.run.Init())
	}

	return tea.Batch(cmds...)
}

func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsMsg, ok := msg.(tea.WindowSizeMsg); ok {
		m.width, m.height = wsMsg.Width, wsMsg.Height
		m.help.SetSize(wsMsg.Width, wsMsg.Height)
	}

	if handled, cmd := m.handleHelp(msg); handled {
		return m, cmd
	}

	// Snapshot input state before sub-models see this key.
	awaitingUserInput := m.isAwaitingUserInput()

	var cmds []tea.Cmd

	// Handle sub-component updates.
	switch m.mode {
	case viewModeWorkspace:
		if cmd := m.workspace.Update(msg); cmd != nil {
			cmds = append(cmds, cmd)
		}
	case viewModeRun:
		// Keep the workspace's background tasks (watchers/heartbeats) alive
		// while we're in the single-run view while omitting user input.
		if !isUserInputMsg(msg) {
			if cmd := m.workspace.Update(msg); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
		if _, cmd := m.run.Update(msg); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}

	// Handle mode switching.
	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch m.mode {
		case viewModeWorkspace:
			if keyMsg.Type == tea.KeyEnter && !awaitingUserInput {
				cmd := m.enterRunView()
				return m, cmd
			}
		case viewModeRun:
			if keyMsg.Type == tea.KeyEsc && !awaitingUserInput {
				cmd := m.exitRunView()
				return m, cmd
			}
		}
	}

	return m, tea.Batch(cmds...)
}

func (m *Model) View() string {
	if m.help.IsActive() {
		return m.renderHelpScreen()
	}

	switch m.mode {
	case viewModeWorkspace:
		return m.workspace.View()
	case viewModeRun:
		if m.run != nil {
			return m.run.View()
		}
		return ""
	default:
		return ""
	}
}

func (m *Model) ShouldRestart() bool {
	// TODO: wire this up.
	return false
}

func (m *Model) isAwaitingUserInput() bool {
	if m.config != nil && m.config.IsAwaitingGridConfig() {
		return true
	}
	switch m.mode {
	case viewModeWorkspace:
		return m.workspace != nil && m.workspace.IsFiltering()
	case viewModeRun:
		return m.run != nil && m.run.IsFiltering()
	default:
		return false
	}
}

func isUserInputMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case tea.KeyMsg, tea.MouseMsg:
		return true
	default:
		return false
	}
}

// handleHelp centralizes help toggle and routing while active.
func (m *Model) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	switch m.mode {
	case viewModeWorkspace:
		if m.workspace.IsFiltering() {
			return false, nil
		}
	case viewModeRun:
		if m.run.IsFiltering() {
			return false, nil
		}
	}

	// Toggle on 'h' / '?'
	if km, ok := msg.(tea.KeyMsg); ok {
		switch km.String() {
		case "h", "?":
			m.help.SetMode(m.mode)
			m.help.Toggle()
			return true, nil
		}
	}

	// When help is visible, it owns key/mouse events.
	if m.help.IsActive() {
		switch msg.(type) {
		case tea.KeyMsg, tea.MouseMsg:
			updated, cmd := m.help.Update(msg)
			m.help = updated
			return true, cmd
		}
	}
	return false, nil
}

// renderHelpScreen renders the help screen.
func (m *Model) renderHelpScreen() string {
	helpView := m.help.View()

	helpText := "h: help"
	spaceForHelp := max(max(m.width-2*StatusBarPadding, 0), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	fullStatus := rightAligned

	statusBar := statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(fullStatus)

	content := lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
	return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, content)
}

// enterRunView switches to single-run view for the selected run.
func (m *Model) enterRunView() tea.Cmd {
	wandbFile := m.workspace.SelectedRunWandbFile()
	if wandbFile == "" {
		return nil
	}

	m.run = NewRun(wandbFile, m.config, m.logger)
	m.mode = viewModeRun

	// Initialize with current dimensions and start loading.
	return tea.Batch(
		m.run.Init(),
		func() tea.Msg {
			return tea.WindowSizeMsg{Width: m.width, Height: m.height}
		},
	)
}

// exitRunView returns to the workspace view.
func (m *Model) exitRunView() tea.Cmd {
	// TODO: add caching?
	if m.run != nil {
		m.run.Cleanup()
		m.run = nil
	}

	m.mode = viewModeWorkspace
	return nil
}

// extractRunID extracts the run ID from a folder name.
//
// "run-20250731_170606-iazb7i1k" -> "iazb7i1k"
// "offline-run-20250731_170606-abc123" -> "abc123"
func extractRunID(folderName string) string {
	lastHyphen := strings.LastIndex(folderName, "-")
	if lastHyphen == -1 || lastHyphen == len(folderName)-1 {
		return ""
	}
	return folderName[lastHyphen+1:]
}

// runWandbFile returns the full path to the .wandb file for the given run folder.
func runWandbFile(wandbDir, runDir string) string {
	runID := extractRunID(runDir)
	if runID == "" {
		return ""
	}
	return filepath.Join(wandbDir, runDir, "run-"+runID+".wandb")
}

func wandbFileFromLatestRunLink(wandbDir string) (string, error) {
	latestRunPath, err := filepath.Abs(filepath.Join(wandbDir, latestRunLinkName))
	if err != nil {
		return "", err
	}

	info, err := os.Stat(latestRunPath) // follows symlinks
	if err != nil || !info.IsDir() {
		return "", err
	}

	resolvedLatestRunPath, err := os.Readlink(latestRunPath)
	if err != nil {
		return "", err
	}

	latestWandbFile := runWandbFile(wandbDir, resolvedLatestRunPath)
	info, err = os.Stat(latestRunPath)
	if err != nil {
		return "", err
	}

	return latestWandbFile, nil
}
