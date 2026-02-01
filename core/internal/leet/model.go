package leet

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// viewMode represents which top-level view is active.
type viewMode int

const (
	viewModeUndefined viewMode = iota
	viewModeWorkspace
	viewModeRun
	viewModeSymon
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
	cmds := []tea.Cmd{}

	var source tea.Cmd
	if strings.HasPrefix(m.run.runPath, "wandb://") {
		source = InitializeParquetHistorySource(m.run.runPath, m.logger)
	} else {
		source = InitializeLevelDBHistorySource(m.run.runPath, m.logger)
	}
	cmds = append(cmds, source)

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

	// Snapshot before sub-models consume the key — a filter's Enter
	// exits filter mode, so checking after would miss it.
	awaitingInput := m.isAwaitingUserInput()

	cmds := m.updateSubComponents(msg)

	if cmd := m.handleModeSwitch(msg, awaitingInput); cmd != nil {
		return m, cmd
	}

	return m, tea.Batch(cmds...)
}

// updateSubComponents forwards the message to the active sub-models.
func (m *Model) updateSubComponents(msg tea.Msg) []tea.Cmd {
	var cmds []tea.Cmd
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
	return cmds
}

// handleModeSwitch checks for Enter/Esc and transitions between views.
//
// awaitingInput must be snapshotted before sub-components process the
// message, because an Enter in filter mode exits the filter and would
// otherwise fall through to a view switch.
func (m *Model) handleModeSwitch(msg tea.Msg, awaitingInput bool) tea.Cmd {
	keyMsg, ok := msg.(tea.KeyPressMsg)
	if !ok {
		return nil
	}

	switch m.mode {
	case viewModeWorkspace:
		if keyMsg.Code == tea.KeyEnter &&
			!awaitingInput &&
			m.workspace.RunSelectorActive() {
			return m.enterRunView()
		}
	case viewModeRun:
		runCapturesEsc := m.run != nil && m.run.MediaFullscreen()
		if keyMsg.Code == tea.KeyEsc &&
			!awaitingInput && !runCapturesEsc {
			return m.exitRunView()
		}
	}
	return nil
}

// View renders the UI based on the data in the model.
//
// Implements tea.Model.View.
func (m *Model) View() tea.View {
	var vs string

	if m.help.IsActive() {
		vs = m.renderHelpScreen()
	} else {
		switch m.mode {
		case viewModeWorkspace:
			vs = m.workspace.View().Content
		case viewModeRun:
			vs = m.run.View().Content
		}
	}

	v := tea.NewView(vs)

	v.WindowTitle = "wandb leet"
	v.AltScreen = true
	v.MouseMode = tea.MouseModeCellMotion

	return v
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
	case tea.KeyPressMsg, tea.MouseMsg:
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
	if km, ok := msg.(tea.KeyPressMsg); ok {
		switch km.Code {
		case 'h', '?':
			m.help.SetMode(m.mode)
			m.help.Toggle()
			return true, nil
		}
	}

	// When help is visible, it owns key/mouse events.
	if m.help.IsActive() {
		switch msg.(type) {
		case tea.KeyPressMsg, tea.MouseMsg:
			updated, cmd := m.help.Update(msg)
			m.help = updated
			return true, cmd
		}
	}
	return false, nil
}

func (m *Model) handleRestart(msg tea.Msg) (bool, tea.Cmd) {
	// Toggle on 'h' / '?'
	if km, ok := msg.(tea.KeyPressMsg); ok {
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
	helpView := m.help.View().Content

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

	// Share the workspace's media store so data persists across transitions.
	runKey := m.workspace.SelectedRunKey()
	if store := m.workspace.MediaStoreForRun(runKey); store != nil {
		m.run.SetMediaStore(store)
	}
	// Restore saved media pane view state (scroll position, selection).
	if state := m.workspace.LoadMediaPaneState(runKey); state != nil {
		m.run.mediaPane.RestoreViewState(*state)
	}

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
	if m.run != nil {
		// Save media pane view state for later restoration.
		runKey := m.workspace.SelectedRunKey()
		if runKey != "" {
			m.workspace.SaveMediaPaneState(runKey, m.run.mediaPane.SaveViewState())
			// Force the workspace pane to re-sync from the saved per-run state on return.
			m.workspace.currentMediaRunKey = ""
		}
		m.run.Cleanup()
		m.run = nil
	}

	m.mode = viewModeWorkspace
	return nil
}

// --------------------------------------------------------------------
// Path resolution utilities
// --------------------------------------------------------------------

var runDirRe = regexp.MustCompile(`run-\d{8}_\d{6}-`)

// extractRunID extracts the run ID from a run directory name.
//
// The expected formats are:
//
//	"run-YYYYMMDD_HHMMSS-<run_id>"
//	"offline-run-YYYYMMDD_HHMMSS-<run_id>"
//
// Returns "" if the folder name doesn't match.
func extractRunID(folderName string) string {
	loc := runDirRe.FindStringIndex(folderName)
	if len(loc) == 0 || loc[1] == len(folderName) {
		return ""
	}
	return folderName[loc[1]:]
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
