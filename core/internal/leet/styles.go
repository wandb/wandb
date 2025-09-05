package leet

import (
	"time"

	"github.com/charmbracelet/lipgloss"
)

// Default layout constants.
var (
	GridRows        = 3
	GridCols        = 5
	ChartsPerPage   = GridRows * GridCols
	StatusBarHeight = 1
	MinChartWidth   = 20
	MinChartHeight  = 5
)

// Default system metrics grid configuration.
var (
	MetricsGridRows      = 3
	MetricsGridCols      = 2
	MetricsPerPage       = MetricsGridRows * MetricsGridCols
	MinMetricChartWidth  = 18
	MinMetricChartHeight = 4
)

// Sidebar constants.
const (
	SidebarWidthRatio     = 0.382
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: 0.382 * 0.618 ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 80
)

// WANDB brand colors.
const (
	// Primary
	// moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
	// moon50     = lipgloss.Color("#FDFDFD")
	// Secondary
	// teal450 = lipgloss.Color("#10BFCC")
	// moon450 = lipgloss.Color("#8F949E")
)

// ASCII art for the loading screen and the help page.
var wandbArt = `
██     ██  █████  ███    ██ ██████  ██████
██     ██ ██   ██ ████   ██ ██   ██ ██   ██
██  █  ██ ███████ ██ ██  ██ ██   ██ ██████
██ ███ ██ ██   ██ ██  ██ ██ ██   ██ ██   ██
 ███ ███  ██   ██ ██   ████ ██████  ██████

`

const leetArt = `
██      ███████ ███████ ████████
██      ██      ██         ██
██      █████   █████      ██
██      ██      ██         ██
███████ ███████ ███████    ██
`

// Color schemes.
var colorSchemes = map[string][]string{
	"sunset-glow": { // Golden-pink gradient
		"#E281FE",
		"#E78DE3",
		"#E993D5",
		"#ED9FBB",
		"#F0A5AD",
		"#F2AB9F",
		"#F6B784",
		"#F8BD78",
		"#FBC36B",
		"#FFCF4F",
	},
	"wandb-vibe-10": {
		"#B1B4B9",
		"#58D3DB",
		"#5ED6A4",
		"#FCA36F",
		"#FF7A88",
		"#7DB1FA",
		"#BBE06B",
		"#FFCF4D",
		"#E180FF",
		"#B199FF",
	},
	"wandb-vibe-20": {
		"#D4D5D9",
		"#565C66",
		"#A9EDF2",
		"#038194",
		"#A1F0CB",
		"#00875A",
		"#FFCFB2",
		"#C2562F",
		"#FFC7CA",
		"#CC2944",
		"#BDD9FF",
		"#1F59C4",
		"#D0ED9D",
		"#5F8A2D",
		"#FFE49E",
		"#B8740F",
		"#EFC2FC",
		"#9E36C2",
		"#D6C9FF",
		"#6645D1",
	},
}

// GetGraphColors returns the colors for the current color scheme.
func GetGraphColors() []string {
	return colorSchemes["sunset-glow"]
}

// UpdateGridDimensions updates the grid dimensions from config.
func UpdateGridDimensions() {
	cfg := GetConfig()

	rows, cols := cfg.GetMetricsGrid()
	GridRows = rows
	GridCols = cols
	ChartsPerPage = GridRows * GridCols

	sysRows, sysCols := cfg.GetSystemGrid()
	MetricsGridRows = sysRows
	MetricsGridCols = sysCols
	MetricsPerPage = MetricsGridRows * MetricsGridCols
}

// Metrics grid styles.
var (
	headerStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("230"))

	navInfoStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240"))

	headerContainerStyle = lipgloss.NewStyle().
				MarginLeft(1).
				MarginTop(1).
				MarginBottom(0)

	gridContainerStyle = lipgloss.NewStyle().
				MarginLeft(1).
				MarginRight(1)
)

// Chart styles.
var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("238")) // dark gray

	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("250")). // light gray
			Bold(true)

	focusedBorderStyle = borderStyle.BorderForeground(lipgloss.Color("#E1F7FA"))

	axisStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")) // gray

	labelStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245")) // light gray
)

// Status bar styles.
var (
	// pageInfoStyle = lipgloss.NewStyle().
	// 	// Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}).
	// 	// Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#0C8599"}).
	// 	Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#2B3038"}).
	// 	Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#A9FDF2"}).
	// 	Padding(0, 1)

	statusBarStyle = lipgloss.NewStyle().
		// Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
		// Background(lipgloss.AdaptiveColor{Light: "#45B7D1", Dark: "#1864AB"})
		Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#2B3038"}).
		Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#E1F7FA"})
	// Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#A9FDF2"})
)

// Sidebar styles.
var (
	sidebarStyle        = lipgloss.NewStyle().Padding(0, 1)
	sidebarBorderStyle  = lipgloss.NewStyle().Border(lipgloss.Border{Right: "│"}).BorderForeground(lipgloss.Color("238"))
	sidebarHeaderStyle  = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("230")).MarginBottom(1)
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

// Right sidebar styles.
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

// AnimationDuration is the duration for sidebar animations.
const AnimationDuration = 150 * time.Millisecond

// AnimationSteps is the number of steps in sidebar animations.
const AnimationSteps = 10

// Help screen styles.
var (
	helpKeyStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("230")).
			Width(20)

	helpDescStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245"))

	helpSectionStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(wandbColor)

	helpContentStyle = lipgloss.NewStyle().
				MarginLeft(2).
				MarginTop(1)
)
