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

// viewMode represents which top-level view is active.
type viewMode int

const (
	viewModeUndefined viewMode = iota

	// viewModeWorkspace displays the multi-run workspace with a run
	// selector, run overview sidebar, and an overlay metrics grid showing
	// data from all selected runs.
	viewModeWorkspace

	// viewModeRun displays a single run's metrics, overview sidebar,
	// system metrics sidebar, and detailed chart interactions.
	viewModeRun
)

// latestRunLinkName is the conventional symlink name that wandb creates to
// point at the most recently started run directory.
const latestRunLinkName = "latest-run"

// Model is the top-level app model.
//
// It owns the workspace (always present) and optionally a single-run detail
// view. The help overlay is shared across both modes.
//
// Implements tea.Model.
type Model struct {
	// mode tracks which sub-model currently owns the screen and user input.
	mode viewMode

	// workspace is the multi-run view. It is created at startup and kept
	// alive for the entire session so its watchers and heartbeats continue
	// streaming data in the background while the user is in single-run view.
	workspace *Workspace

	// run is the single-run detail view. It is nil when the user is in
	// workspace mode and created on-demand when they press Enter on a run.
	run *Run

	// width and height cache the latest terminal dimensions for layout.
	width, height int

	// help is the full-screen help overlay, shared across both modes.
	help *HelpModel

	// shouldRestart is the restart flag.
	shouldRestart bool

	// config is the shared application configuration (grid sizes, color
	// schemes, sidebar visibility, etc.).
	config *ConfigManager

	logger *observability.CoreLogger
}

type ModelParams struct {
	// WandbDir is the path to the wandb directory (typically "./wandb")
	// that contains run directories and the "latest-run" symlink.
	WandbDir string

	// RunFile, if non-empty, LEET launches directly into the single-run
	// view for the specified .wandb file. When empty, LEET starts in
	// Config.StartupMode.
	RunFile string

	Config *ConfigManager
	Logger *observability.CoreLogger
}

// NewModel creates and returns the top-level Model.
//
// Startup behavior depends on the combination of RunFile and Config.StartupMode:
//
//   - RunFile is set → start in single-run view for that file.
//   - RunFile is empty + StartupModeSingleRunLatest → resolve the "latest-run"
//     symlink and start in single-run view.
//   - RunFile is empty + StartupModeWorkspaceLatest (default) → start in
//     workspace view; the workspace will auto-select the latest run once
//     the directory poll completes.
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

	if params.RunFile != "" {
		m.run = NewRun(params.RunFile, params.Config, params.Logger)
		m.mode = viewModeRun
	}

	return m
}

// Init returns the initial commands for the top-level model.
//
// The workspace is always initialized (directory polling, heartbeat listener)
// regardless of the starting mode. If starting in single-run mode, the run's
// reader and watcher commands are also started.
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

// Update handles incoming events and updates the model accordingly.
//
// Implements tea.Model.Update.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsMsg, ok := msg.(tea.WindowSizeMsg); ok {
		m.width, m.height = wsMsg.Width, wsMsg.Height
		m.help.SetSize(wsMsg.Width, wsMsg.Height)
	}

	if handled, cmd := m.handleHelp(msg); handled {
		return m, cmd
	}

	if handled, cmd := m.handleRestart(msg); handled {
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

// View renders the UI based on the data in the model.
//
// Implements tea.Model.View.
func (m *Model) View() string {
	if m.help.IsActive() {
		return m.renderHelpScreen()
	}

	switch m.mode {
	case viewModeWorkspace:
		return m.workspace.View()
	case viewModeRun:
		return m.run.View()
	default:
		return ""
	}
}

// ShouldRestart reports whether the application should perform a full restart.
func (m *Model) ShouldRestart() bool {
	return m.shouldRestart
}

// --------------------------------------------------------------------
// Input state helpers
// --------------------------------------------------------------------

// isAwaitingUserInput reports whether any sub-component is capturing
// free-form keyboard input (filter text, grid config digit, etc.).
//
// When true, global key bindings like Enter (mode switch) and h (help
// toggle) must be suppressed so keystrokes reach the active input.
func (m *Model) isAwaitingUserInput() bool {
	if m.config != nil && m.config.IsAwaitingGridConfig() {
		return true
	}
	switch m.mode {
	case viewModeWorkspace:
		return m.workspace.IsFiltering()
	case viewModeRun:
		return m.run.IsFiltering()
	default:
		return false
	}
}

// isUserInputMsg reports whether msg originates from direct user interaction.
//
// Used to gate which messages reach the workspace while the user is in
// single-run mode: user input goes exclusively to the run, while data
// messages (file changes, heartbeats, batched records) are forwarded to
// the workspace to keep its background state current.
func isUserInputMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case tea.KeyMsg, tea.MouseMsg:
		return true
	default:
		return false
	}
}

// --------------------------------------------------------------------
// Mode transitions
// --------------------------------------------------------------------

// handleHelp centralizes help toggle and routing while active.
func (m *Model) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	if m.isAwaitingUserInput() {
		return false, nil
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

func (m *Model) handleRestart(msg tea.Msg) (bool, tea.Cmd) {
	// Toggle on 'h' / '?'
	if km, ok := msg.(tea.KeyMsg); ok {
		if km.String() == "alt+r" {
			m.logger.Debug("model: restart requested")
			m.shouldRestart = true

			return true, tea.Quit
		}
	}
	return false, nil
}

// renderHelpScreen renders the help screen.
func (m *Model) renderHelpScreen() string {
	helpView := m.help.View()

	helpText := "h: help"
	spaceForHelp := max(m.width-2*StatusBarPadding, 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	statusBar := statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(rightAligned)

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

// --------------------------------------------------------------------
// Path resolution utilities
// --------------------------------------------------------------------

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
	if _, err = os.Stat(latestWandbFile); err != nil {
		return "", err
	}

	return latestWandbFile, nil
}
