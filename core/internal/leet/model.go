package leet

import (
	"os"
	"strings"

	"github.com/charmbracelet/bubbles/viewport"
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

type Model struct {
	mode viewMode

	// workspace view
	workspace *Workspace

	// current selected run
	run *RunModel

	config *ConfigManager

	logger *observability.CoreLogger

	width, height int
}

func NewModel(wandbDirPath string, cfg *ConfigManager, logger *observability.CoreLogger) *Model {
	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	return &Model{
		workspace: &Workspace{
			wandbDirPath: wandbDirPath,
			runPicker:    viewport.New(80, 20),
		},
		config: cfg,
		logger: logger,
	}
}

type Workspace struct {
	// move to runPicker
	wandbDirPath string

	runPicker viewport.Model

	// runPicker *runPicker --> This is an unnecessary level of abstraction, just use Workspace.
	// filesystem view of the wandb dir.
	// each line is selectable with Space.
	// selecting a run loads metric data of the run in the container
	// and turns on watching if it's a live run.
	// display a colored block next to run id; use that color for the run's plots
	// option to "pin" a run. "queue" for the "order"?

	// wandbDirWatcher *WandbDirWatcher. make it part of the runPicker!
	// watch for new runs, or simply ls the wandb dir every N seconds.
	// once a run is added, add it to the container.

	// runs container. make it part of the runPicker!
	// on load, populated with everything in the wandb dir and
	// selects the latest run or the exact one provided in the command.
	// preloads basic run metadata from the run record.
	// marks finished runs? or only after one is selected?
	// selected runs add data to a container in epochlinecharts.
	// draw method pulls data to plot from there based on the current
	// selected runs.
	//
	// when no run is selected, display the wandb leet ascii art.

	filter Filter

	config *ConfigManager

	logger *observability.CoreLogger
}

func (w *Workspace) View() string {
	runs, err := os.ReadDir(w.wandbDirPath)
	if err != nil {
		return "ERROR"
	}

	evenLineStyle := lipgloss.NewStyle().Background(colorItemValue)
	oddLineStyle := lipgloss.NewStyle().Background(colorAccent)

	content := ""

	for i, run := range runs {
		if !strings.HasPrefix(run.Name(), "run") && !strings.HasPrefix(run.Name(), "offline-run") {
			continue
		}
		// TODO: check that it's a folder that contains a .wandb file

		// TODO: apply the filter

		if i%2 == 0 {
			content += evenLineStyle.Render(run.Name()) + "\n"
		} else {
			content += oddLineStyle.Render(run.Name()) + "\n"
		}

	}
	w.runPicker.SetContent(content)

	runPickerContentStyle := lipgloss.NewStyle().MarginLeft(2).MarginTop(2)

	return runPickerContentStyle.Render(w.runPicker.View())
}

func (m *Model) Init() tea.Cmd {
	return tea.Batch(
		windowTitleCmd(),
		// initializeWorkspace(wandbDirPath string), // do I need this at all? prob not
	)
}

func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch t := msg.(type) {
	case tea.KeyMsg:
		newM, c := m.handleKeyMsg(t)
		if c != nil {
			cmds = append(cmds, c)
		}
		return newM, tea.Batch(cmds...)
	case tea.WindowSizeMsg:
		m.handleWindowResize(t)
		return m, tea.Batch(cmds...)
	}

	return m, nil
}

// handleWindowResize handles window resize messages.
func (m *Model) handleWindowResize(msg tea.WindowSizeMsg) {
	m.width, m.height = msg.Width, msg.Height
	m.workspace.runPicker.Width, m.workspace.runPicker.Height = msg.Width, msg.Height
}

func (m *Model) handleKeyMsg(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	// TODO: build and use a keyMap, similar to RunModel

	var cmd tea.Cmd

	switch msg.String() {
	case "q":
		return m, tea.Quit
	default:
		m.workspace.runPicker, cmd = m.workspace.runPicker.Update(msg)
	}

	return m, cmd
}

func (m *Model) View() string {
	return m.workspace.View()
}
