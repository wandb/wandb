package leet

import (
	"time"

	"github.com/charmbracelet/lipgloss"
)

// Immutable UI constants.
const (
	StatusBarHeight      = 1
	MinChartWidth        = 20
	MinChartHeight       = 5
	MinMetricChartWidth  = 18
	MinMetricChartHeight = 4
)

// Default grid sizes
const (
	DefaultMetricsGridRows = 4
	DefaultMetricsGridCols = 3
	DefaultSystemGridRows  = 6
	DefaultSystemGridCols  = 2
)

// Sidebar constants.
//
// We are using the golden ratio `phi` for visually pleasing layout proportions.
const (
	SidebarWidthRatio     = 0.382 // 1 - 1/phi
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: (1 - 1/phi) / phi ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 120
)

// WANDB brand colors.
const (
	// Primary
	moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
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

// Color schemes for displaying data (metrics and system metrics) on the charts.
//
// Each scheme consists of an ordered list of colors,
// where each new graph, and/or a line on a multi-line graph takes the next color.
// Colors get reused in a cyclic manner.
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

// Status bar styles.
var (
	statusBarStyle = lipgloss.NewStyle().
		Foreground(moon900).
		Background(lipgloss.AdaptiveColor{
			Light: "#10BFCC", // teal450 - W&B secondary color
			Dark:  "#E1F7FA",
		})
)

// AnimationDuration is the duration for sidebar animations.
const AnimationDuration = 150 * time.Millisecond

// AnimationSteps is the number of steps in sidebar animations.
const AnimationSteps = 10
