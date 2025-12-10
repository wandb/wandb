// model.go
package leet

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/observability"
)

type viewMode int

const (
	viewModeUndefined viewMode = iota
	viewModeWorkspace
	viewModeRun
)

type Model struct {
	mode      viewMode
	workspace *Workspace
	run       *RunModel

	width, height int

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

	ws := NewWorkspace(params.WandbDir, params.Config, params.Logger)

	m := &Model{
		mode:      viewModeWorkspace,
		workspace: ws,
		config:    params.Config,
		logger:    params.Logger,
	}

	// If a run file is specified, start in single-run mode.
	if params.RunFile != "" {
		m.run = NewRunModel(params.RunFile, params.Config, params.Logger)
		m.mode = viewModeRun
	}

	return m
}

func (m *Model) Init() tea.Cmd {
	cmds := []tea.Cmd{windowTitleCmd()}

	if m.mode == viewModeRun && m.run != nil {
		cmds = append(cmds, m.run.Init())
	}

	return tea.Batch(cmds...)
}

func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if wsMsg, ok := msg.(tea.WindowSizeMsg); ok {
		m.width, m.height = wsMsg.Width, wsMsg.Height
	}

	// Handle mode switching.
	if keyMsg, ok := msg.(tea.KeyMsg); ok {
		switch m.mode {
		case viewModeWorkspace:
			if keyMsg.Type == tea.KeyEnter {
				return m, m.enterRunView()
			}
		case viewModeRun:
			if keyMsg.Type == tea.KeyEsc {
				return m, m.exitRunView()
			}
		}
	}

	var cmd tea.Cmd
	switch m.mode {
	case viewModeWorkspace:
		cmd = m.workspace.Update(msg)
	case viewModeRun:
		_, cmd = m.run.Update(msg)
	}

	return m, cmd
}

func (m *Model) View() string {
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

// enterRunView switches to single-run view for the selected run.
func (m *Model) enterRunView() tea.Cmd {
	wandbFile := m.workspace.SelectedRunWandbFile()
	if wandbFile == "" {
		return nil
	}

	m.run = NewRunModel(wandbFile, m.config, m.logger)
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
