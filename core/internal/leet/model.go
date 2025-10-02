package leet

import (
	"fmt"
	"runtime/debug"
	"sync"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

// Model describes the application state.
//
// Implements tea.Model.
//
// NOTE: Bubble Tea programs are comprised of a model and three methods on it:
//   - Init returns an initial command for the application to run.
//   - Update handles incoming events and updates the model accordingly.
//   - View renders the UI based on the data in the model.
type Model struct {
	// Serialize access to Update / broad model state.
	stateMu sync.RWMutex

	// runPath is the path to the .wandb file.
	runPath string

	// Main view size.
	width, height int

	isLoading bool

	// shouldRestart is set when the user requests a full restart (Alt+R).
	shouldRestart bool

	// logger is the debug logger for the application.
	logger *observability.CoreLogger
}

func NewModel(runPath string, logger *observability.CoreLogger) *Model {
	logger.Info(fmt.Sprintf("model: creating new model for runPath: %s", runPath))

	m := &Model{
		runPath: runPath,
		logger:  logger,
	}

	return m
}

// Init initializes the app model and returns the initial command for the application to run.
//
// Implements tea.Model.Init.
func (m *Model) Init() tea.Cmd {
	m.logger.Debug("model: Init called")

	m.isLoading = true

	return tea.Batch(
		windowTitleCmd(),
	)
}

// Update handles incoming events and updates the model accordingly.
//
// Implements tea.Model.Update.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	defer m.logPanic("Update")
	m.stateMu.Lock()
	defer m.stateMu.Unlock()

	var cmds []tea.Cmd

	switch t := msg.(type) {
	case tea.KeyMsg:
		newM, c := m.handleKeyMsg(t)
		if c != nil {
			cmds = append(cmds, c)
		}
		return newM, tea.Batch(cmds...)

	case tea.WindowSizeMsg:
		m.width, m.height = t.Width, t.Height

		return m, tea.Batch(cmds...)

	default:
		return m, tea.Batch(cmds...)
	}

}

// View renders the UI based on the data in the model.
//
// Implements tea.Model.View.
func (m *Model) View() string {
	defer m.logPanic("View")
	m.stateMu.RLock()
	defer m.stateMu.RUnlock()

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	if m.isLoading {
		return m.renderLoadingScreen()
	}

	var mainView string

	statusBar := m.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)

	return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, fullView)
}

// ShouldRestart reports whether the user requested a full restart.
func (m *Model) ShouldRestart() bool {
	return m.shouldRestart
}

// logPanic logs panics to Sentry before re-panicing.
func (m *Model) logPanic(context string) {
	if r := recover(); r != nil {
		stackTrace := string(debug.Stack())
		m.logger.CaptureError(fmt.Errorf("PANIC in %s: %v\nStack trace:\n%s", context, r, stackTrace))

		panic(r)
	}
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen.
func (m *Model) renderLoadingScreen() string {
	artStyle := lipgloss.NewStyle().
		Foreground(wandbColor).
		Bold(true)

	logoContent := lipgloss.JoinVertical(
		lipgloss.Center,
		artStyle.Render(wandbArt),
		artStyle.Render(leetArt),
	)

	centeredLogo := lipgloss.Place(
		m.width,
		m.height-StatusBarHeight,
		lipgloss.Center,
		lipgloss.Center,
		logoContent,
	)

	statusBar := m.renderStatusBar()
	return lipgloss.JoinVertical(lipgloss.Left, centeredLogo, statusBar)
}

// renderStatusBar creates the status bar.
func (m *Model) renderStatusBar() string {
	// Left side content
	statusText := ""

	// Right side content
	helpText := ""

	rightAligned := lipgloss.PlaceHorizontal(
		m.width-lipgloss.Width(statusText),
		lipgloss.Right,
		helpText,
	)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(fullStatus)
}
