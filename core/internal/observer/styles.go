package observer

import "github.com/charmbracelet/lipgloss"

// Layout constants
const (
	GridRows        = 3
	GridCols        = 5
	ChartsPerPage   = GridRows * GridCols
	StatusBarHeight = 1
	MinChartWidth   = 20
	MinChartHeight  = 5
)

// System metrics grid configuration
const (
	MetricsGridRows      = 3
	MetricsGridCols      = 2
	MetricsPerPage       = MetricsGridRows * MetricsGridCols
	MinMetricChartWidth  = 18
	MinMetricChartHeight = 4
)

// Sidebar constants
const (
	SidebarWidthRatio     = 0.382
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: 0.382 * 0.618 ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 80
)

// WANDB brand color
// const wandbColor = lipgloss.Color("#FFBE00")
const wandbColor = lipgloss.Color("#FCBC32")
// fcbc32

// ASCII art for the loading screen
var wandbArt = `
██     ██  █████  ███    ██ ██████  ██████
██     ██ ██   ██ ████   ██ ██   ██ ██   ██
██  █  ██ ███████ ██ ██  ██ ██   ██ ██████
██ ███ ██ ██   ██ ██  ██ ██ ██   ██ ██   ██
 ███ ███  ██   ██ ██   ████ ██████  ██████

`
var observerArt = `
 ██████  ██████  ███████ ███████ ██████  ██    ██ ███████ ██████
██    ██ ██   ██ ██      ██      ██   ██ ██    ██ ██      ██   ██
██    ██ ██████  ███████ █████   ██████  ██    ██ █████   ██████
██    ██ ██   ██      ██ ██      ██   ██  ██  ██  ██      ██   ██
 ██████  ██████  ███████ ███████ ██   ██   ████   ███████ ██   ██

`

// Chart colors
// TODO: talk to design, adhere to our official color scheme.
var graphColors = []string{"4", "10", "5", "6", "3", "2", "13", "14", "11", "9", "12", "1", "7", "8", "15"}

// Chart styles
var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("238")) // dark gray

	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("250")). // light gray
			Bold(true)

	focusedBorderStyle = borderStyle.BorderForeground(lipgloss.Color("4"))

	axisStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")) // gray

	labelStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245")) // light gray
)

// Status bar styles
var (
	pageInfoStyle = lipgloss.NewStyle().
			Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}).
			Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#0C8599"}).
			Padding(0, 1)

	statusBarStyle = lipgloss.NewStyle().
			Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
			Background(lipgloss.AdaptiveColor{Light: "#45B7D1", Dark: "#1864AB"})
)

// Sidebar styles
var (
	sidebarStyle        = lipgloss.NewStyle().Padding(0, 1)
	sidebarBorderStyle  = lipgloss.NewStyle().Border(lipgloss.Border{Right: "│"}).BorderForeground(lipgloss.Color("238"))
	sidebarHeaderStyle  = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("230")).MarginLeft(1)
	sidebarSectionStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("245")).Bold(true)
	sidebarKeyStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("241"))
	sidebarValueStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("252"))

	RightBorder = lipgloss.Border{
		Top:         " ",
		Bottom:      " ",
		Left:        "",
		Right:       "│",
		TopLeft:     " ",
		TopRight:    "│",
		BottomLeft:  " ",
		BottomRight: "│",
	}
)

// Right sidebar styles
var (
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	rightSidebarBorderStyle = lipgloss.NewStyle().Border(lipgloss.Border{Left: "│"}).BorderForeground(lipgloss.Color("238"))
	rightSidebarHeaderStyle = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("230")).MarginLeft(1)

	LeftBorder = lipgloss.Border{
		Top:         " ",
		Bottom:      " ",
		Left:        "│",
		Right:       "",
		TopLeft:     "|",
		TopRight:    " ",
		BottomLeft:  "|",
		BottomRight: " ",
	}
)

// Help screen styles
var (
	helpKeyStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("230")).
			Width(20) // helpKeyWidth

	helpDescStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245"))

	helpSectionStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(wandbColor).
				MarginTop(1).
				MarginBottom(1)

	helpContentStyle = lipgloss.NewStyle().
				MarginLeft(2).
				MarginTop(2)
)
