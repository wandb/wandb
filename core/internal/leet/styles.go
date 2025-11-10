package leet

import (
	"time"

	"github.com/charmbracelet/lipgloss"
)

// Immutable UI constants.
const (
	StatusBarHeight = 1
	// Horizontal padding for the status bar (left and right).
	StatusBarPadding = 1

	MinChartWidth        = 20
	MinChartHeight       = 5
	MinMetricChartWidth  = 18
	MinMetricChartHeight = 4
	ChartBorderSize      = 2
	ChartTitleHeight     = 1
	ChartHeaderHeight    = 2
)

// Default grid sizes
const (
	DefaultMetricsGridRows = 4
	DefaultMetricsGridCols = 3
	DefaultSystemGridRows  = 6
	DefaultSystemGridCols  = 2
)

// Sidebar constants.
const (
	// We are using the golden ratio `phi` for visually pleasing layout proportions.
	SidebarWidthRatio     = 0.382 // 1 - 1/phi
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: (1 - 1/phi) / phi ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 120

	// Sidebar internal content padding (accounts for borders).
	leftSidebarContentPadding = 4

	// Key/value column width ratio.
	leftSidebarKeyWidthRatio = 0.4 // 40% of available width for keys

	// Sidebar content padding (accounts for borders and internal spacing).
	rightSidebarContentPadding = 3

	// Default grid height for system metrics when not calculated from terminal height.
	defaultSystemMetricsGridHeight = 40

	// Mouse click coordinate adjustments for border/padding.
	rightSidebarMouseClickPaddingOffset = 1
)

// Rune constants for UI drawing.
const (
	// verticalLine is ASCII vertical bar U+007C.
	verticalLine rune = '\u007C' // |

	// BoxLightVertical is U+2502 and is "taller" than verticalLine.
	boxLightVertical rune = '\u2502' // │

	// unicodeSpace is the regular whitespace.
	unicodeSpace rune = '\u0020'
)

// WANDB brand colors.
const (
	// Primary colors.
	moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
)

// Secondary colors.
var teal450 = lipgloss.AdaptiveColor{
	Light: "#10BFCC",
	Dark:  "#E1F7FA",
}

// Functional colors not specific to any visual component.
// Ideally these should be adaptive!
var (
	// Color for main items such as chart titles.
	colorAccent = lipgloss.Color("250")

	// Main text color that appears the most frequently on the screen.
	colorText = lipgloss.Color("245")

	// Color for extra or parenthetical text or information.
	// Axis lines in charts.
	colorSubtle = lipgloss.Color("240")

	// Color for layout elements, like borders and separator lines.
	colorLayout = lipgloss.Color("238")

	// Color for layout elements when they're highlighted or focused.
	colorLayoutHighlight = teal450

	// Color for top-level headings; least frequent.
	// Leet logo, help page section headings.
	colorHeading = wandbColor

	// Color for lower-level headings; more frequent than headings.
	// Help page keys, metrics grid header.
	colorSubheading = lipgloss.Color("230")

	// Colors for key-value pairs such as run summary or config items.
	colorItemKey   = lipgloss.Color("243")
	colorItemValue = lipgloss.Color("252")
	colorSelected  = lipgloss.Color("238")
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

// GraphColors returns the colors for the current color scheme.
func GraphColors() []string {
	return colorSchemes[DefaultColorScheme]
}

// Metrics grid styles.
var (
	headerStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading)

	navInfoStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	headerContainerStyle = lipgloss.NewStyle().MarginLeft(1).MarginTop(1).MarginBottom(0)

	gridContainerStyle = lipgloss.NewStyle().MarginLeft(1).MarginRight(1)
)

// Chart styles.
var (
	borderStyle = lipgloss.NewStyle().BorderStyle(lipgloss.RoundedBorder()).BorderForeground(colorLayout)

	titleStyle = lipgloss.NewStyle().Foreground(colorAccent).Bold(true)

	seriesCountStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	focusedBorderStyle = borderStyle.BorderForeground(colorLayoutHighlight)

	axisStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	labelStyle = lipgloss.NewStyle().Foreground(colorText)
)

// Status bar styles.
var (
	statusBarStyle = lipgloss.NewStyle().
		Foreground(moon900).
		Background(colorLayoutHighlight).
		Padding(0, StatusBarPadding)
)

// Left sidebar styles.
var (
	leftSidebarStyle              = lipgloss.NewStyle().Padding(0, 1)
	leftSidebarBorderStyle        = lipgloss.NewStyle().Border(RightBorder).BorderForeground(colorLayout)
	leftSidebarHeaderStyle        = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading).MarginBottom(1)
	leftSidebarSectionHeaderStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading)
	leftSidebarSectionStyle       = lipgloss.NewStyle().Foreground(colorText).Bold(true)
	leftSidebarKeyStyle           = lipgloss.NewStyle().Foreground(colorItemKey)
	leftSidebarValueStyle         = lipgloss.NewStyle().Foreground(colorItemValue)
	RightBorder                   = lipgloss.Border{
		Top:         string(unicodeSpace),
		Bottom:      string(unicodeSpace),
		Left:        "",
		Right:       string(boxLightVertical),
		TopLeft:     string(unicodeSpace),
		TopRight:    string(unicodeSpace),
		BottomLeft:  string(unicodeSpace),
		BottomRight: string(boxLightVertical),
	}
)

// Right sidebar styles.
var (
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	rightSidebarBorderStyle = lipgloss.NewStyle().Border(LeftBorder).BorderForeground(colorLayout)
	rightSidebarHeaderStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading).MarginLeft(1)
	LeftBorder              = lipgloss.Border{
		Top:         string(unicodeSpace),
		Bottom:      string(unicodeSpace),
		Left:        string(boxLightVertical),
		Right:       "",
		TopLeft:     string(unicodeSpace),
		TopRight:    string(unicodeSpace),
		BottomLeft:  string(verticalLine),
		BottomRight: string(unicodeSpace),
	}
)

// AnimationDuration is the duration for sidebar animations.
const AnimationDuration = 150 * time.Millisecond

// AnimationSteps is the number of steps in sidebar animations.
const AnimationSteps = 10

// AnimationFrame is the tick interval used for sidebar animations.
const AnimationFrame = AnimationDuration / AnimationSteps

// Help screen styles.
var (
	helpKeyStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading).Width(20)

	helpDescStyle = lipgloss.NewStyle().Foreground(colorText)

	helpSectionStyle = lipgloss.NewStyle().Bold(true).Foreground(colorHeading)

	helpContentStyle = lipgloss.NewStyle().MarginLeft(2).MarginTop(1)
)
