package leet

import (
	"fmt"
	"runtime/debug"
	"strings"
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
	// Help screen.
	help *HelpModel

	runPath string

	// Main view size.
	width  int
	height int

	isLoading bool

	// logger is the debug logger for the application.
	logger *observability.CoreLogger

	// shouldRestart is set when the user requests a full restart (Alt+R).
	shouldRestart bool

	// Serialize access to Update / broad model state.
	stateMu sync.RWMutex
}

func NewModel(runPath string, logger *observability.CoreLogger) *Model {
	logger.Info(fmt.Sprintf("model: creating new model for runPath: %s", runPath))

	m := &Model{
		help:    NewHelp(),
		runPath: runPath,
		logger:  logger,
	}

	return m
}

// Init initializes the app model and returns the initial command for the application to run.
//
// Required to implement tea.Model.
func (m *Model) Init() tea.Cmd {
	m.logger.Debug("model: Init called")

	m.isLoading = true

	return tea.Batch(
		windowTitleCmd(), // build-tagged shim (no-op under -race)
	)
}

// Update handles incoming events and updates the model accordingly.
//
// Required to implement tea.Model.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	defer m.recoverPanic("Update")
	m.stateMu.Lock()
	defer m.stateMu.Unlock()

	// 1) Help short-circuit (only thing allowed to consume the message)
	if handled, cmd := m.handleHelp(msg); handled {
		return m, cmd
	}

	var cmds []tea.Cmd

	switch t := msg.(type) {
	case tea.KeyMsg:
		newM, c := m.handleKeyMsg(t)
		if c != nil {
			cmds = append(cmds, c)
		}
		return newM, tea.Batch(cmds...)

	case tea.WindowSizeMsg:
		// Single source of truth for sizing
		m.width, m.height = t.Width, t.Height
		m.help.SetSize(t.Width, t.Height)

		return m, tea.Batch(cmds...)

	default:
		return m, tea.Batch(cmds...)
	}

}

// View renders the UI based on the data in the model.
//
// Required to implement tea.Model.
func (m *Model) View() string {
	// Attempt to recover from any panics in View.
	defer m.recoverPanic("View")
	m.stateMu.RLock()
	defer m.stateMu.RUnlock()

	if m.width == 0 || m.height == 0 {
		return "Loading..."
	}

	// Show loading screen if still loading
	if m.isLoading {
		return m.renderLoadingScreen()
	}

	// Show help screen if active
	if m.help.IsActive() {
		helpView := m.help.View()
		statusBar := m.renderStatusBar()
		// Ensure we use exact height
		content := lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
		return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, content)
	}

	var mainView string

	// Render status bar
	statusBar := m.renderStatusBar()

	// Combine main view and status bar, ensuring exact height
	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)

	// Place the view to ensure it fills the terminal exactly
	return lipgloss.Place(m.width, m.height, lipgloss.Left, lipgloss.Top, fullView)
}

// ShouldRestart reports whether the user requested a full restart.
func (m *Model) ShouldRestart() bool {
	return m.shouldRestart
}

// recoverPanic recovers from panics and logs them
func (m *Model) recoverPanic(context string) {
	if r := recover(); r != nil {
		stackTrace := string(debug.Stack())
		m.logger.CaptureError(fmt.Errorf("PANIC in %s: %v\nStack trace:\n%s", context, r, stackTrace))
	}
}

// renderLoadingScreen shows the wandb leet ASCII art centered on screen
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

// renderStatusBar creates the status bar
//
//gocyclo:ignore
func (m *Model) renderStatusBar() string {
	// Left side content
	statusText := ""

	// Right side content - simplified
	helpText := "h: help "

	// Calculate padding to fill the entire width
	statusLen := lipgloss.Width(statusText)
	helpLen := lipgloss.Width(helpText)
	paddingLen := m.width - statusLen - helpLen
	if paddingLen < 1 {
		paddingLen = 1
	}
	padding := strings.Repeat(" ", paddingLen)

	// Combine all parts
	fullStatus := statusText + padding + helpText

	// Apply the status bar style to the full width
	return statusBarStyle.
		Width(m.width).
		MaxWidth(m.width).
		Render(fullStatus)
}

// handleHelp centralizes help toggle and routing while active.
func (m *Model) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	// Toggle on 'h' / '?'
	if km, ok := msg.(tea.KeyMsg); ok {
		switch km.String() {
		case "h", "?":
			m.help.Toggle()
			return true, nil
		}
	}
	// When help is visible, it owns key/mouse
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
