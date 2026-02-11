package leet

import (
	"fmt"
	"os"
	"sync"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/muesli/termenv"
)

// Terminal background detection (cached).
var (
	termBgOnce     sync.Once
	termBgR        uint8
	termBgG        uint8
	termBgB        uint8
	termBgDetected bool
)

// initTerminalBg queries the terminal for its background color (once).
func initTerminalBg() {
	termBgOnce.Do(func() {
		output := termenv.NewOutput(os.Stdout)
		bg := output.BackgroundColor()
		if bg == nil {
			return
		}

		// termenv.RGBColor is a string type like "#RRGGBB"
		if rgb, ok := bg.(termenv.RGBColor); ok {
			var r, g, b uint8
			if _, err := fmt.Sscanf(string(rgb), "#%02x%02x%02x", &r, &g, &b); err != nil {
				return
			}
			termBgR, termBgG, termBgB = r, g, b
			termBgDetected = true
		}
	})
}

// blendRGB blends (r,g,b) toward (tr,tg,tb) by alpha (0.0–1.0).
func blendRGB(r, g, b, tr, tg, tb uint8, alpha float64) lipgloss.Color {
	blend := func(base, target uint8) uint8 {
		return uint8(float64(base)*(1-alpha) + float64(target)*alpha)
	}
	return lipgloss.Color(fmt.Sprintf("#%02x%02x%02x",
		blend(r, tr), blend(g, tg), blend(b, tb),
	))
}

// getOddRunStyleColor returns a color 5% darker than the terminal background.
func getOddRunStyleColor() lipgloss.TerminalColor {
	initTerminalBg()

	if termBgDetected {
		return blendRGB(termBgR, termBgG, termBgB, 128, 128, 128, 0.05)
	}

	return lipgloss.AdaptiveColor{
		Light: "#d0d0d0",
		Dark:  "#1c1c1c",
	}
}

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
	ChartHeaderHeight    = 1
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
	sidebarKeyWidthRatio = 0.4 // 40% of available width for keys

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
	// verticalLine rune = '\u007C' // |

	// BoxLightVertical is U+2502 and is "taller" than verticalLine.
	boxLightVertical rune = '\u2502' // │

	// unicodeSpace is the regular whitespace.
	unicodeSpace rune = '\u0020'

	// mediumShadeBlock is a medium-shaded block.
	mediumShadeBlock rune = '\u2592' // ▒
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
var (
	// Color for main items such as chart titles.
	colorAccent = lipgloss.AdaptiveColor{
		Light: "#6c6c6c",
		Dark:  "#bcbcbc",
	}

	// Main text color that appears the most frequently on the screen.
	colorText = lipgloss.AdaptiveColor{
		Light: "#8a8a8a", // ANSI color 245
		Dark:  "#8a8a8a",
	}

	// Color for extra or parenthetical text or information.
	// Axis lines in charts.
	colorSubtle = lipgloss.AdaptiveColor{
		Light: "#585858", // ANSI color 240
		Dark:  "#585858",
	}

	// Color for layout elements, like borders and separator lines.
	colorLayout = lipgloss.AdaptiveColor{
		Light: "#949494",
		Dark:  "#444444",
	}

	colorDark = lipgloss.Color("#171717")

	// Color for layout elements when they're highlighted or focused.
	colorLayoutHighlight = teal450

	// Color for top-level headings; least frequent.
	// Leet logo, help page section headings.
	colorHeading = wandbColor

	// Color for lower-level headings; more frequent than headings.
	// Help page keys, metrics grid header.
	colorSubheading = lipgloss.AdaptiveColor{
		Light: "#3a3a3a",
		Dark:  "#eeeeee",
	}

	// Colors for key-value pairs such as run summary or config items.
	colorItemKey   = lipgloss.Color("243")
	colorItemValue = lipgloss.AdaptiveColor{
		Light: "#262626",
		Dark:  "#d0d0d0",
	}
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
var colorSchemes = map[string][]lipgloss.AdaptiveColor{
	"sunset-glow": { // Golden-pink gradient
		lipgloss.AdaptiveColor{Light: "#B84FD4", Dark: "#E281FE"},
		lipgloss.AdaptiveColor{Light: "#BD5AB9", Dark: "#E78DE3"},
		lipgloss.AdaptiveColor{Light: "#BF60AB", Dark: "#E993D5"},
		lipgloss.AdaptiveColor{Light: "#C36C91", Dark: "#ED9FBB"},
		lipgloss.AdaptiveColor{Light: "#C67283", Dark: "#F0A5AD"},
		lipgloss.AdaptiveColor{Light: "#C87875", Dark: "#F2AB9F"},
		lipgloss.AdaptiveColor{Light: "#CC8451", Dark: "#F6B784"},
		lipgloss.AdaptiveColor{Light: "#CE8A45", Dark: "#F8BD78"},
		lipgloss.AdaptiveColor{Light: "#D19038", Dark: "#FBC36B"},
		lipgloss.AdaptiveColor{Light: "#D59C1C", Dark: "#FFCF4F"},
	},
	"blush-tide": { // Pink-teal gradient
		lipgloss.AdaptiveColor{Light: "#D94F8C", Dark: "#F9A7CC"},
		lipgloss.AdaptiveColor{Light: "#CA60AC", Dark: "#EEB3E0"},
		lipgloss.AdaptiveColor{Light: "#B96FC4", Dark: "#E4BFEE"},
		lipgloss.AdaptiveColor{Light: "#A77DD4", Dark: "#DBC9F7"},
		lipgloss.AdaptiveColor{Light: "#9489DF", Dark: "#D5D3FC"},
		lipgloss.AdaptiveColor{Light: "#8095E5", Dark: "#D1DCFE"},
		lipgloss.AdaptiveColor{Light: "#6AA1E6", Dark: "#D0E5FF"},
		lipgloss.AdaptiveColor{Light: "#50ACE2", Dark: "#D3ECFE"},
		lipgloss.AdaptiveColor{Light: "#33B6D9", Dark: "#D8F2FC"},
		lipgloss.AdaptiveColor{Light: "#10BFCC", Dark: "#E1F7FA"}, // == teal450
	},
	"gilded-lagoon": { // Golden-teal gradient
		lipgloss.AdaptiveColor{Light: "#D59C1C", Dark: "#FFCF4F"},
		lipgloss.AdaptiveColor{Light: "#C2A636", Dark: "#EADB74"},
		lipgloss.AdaptiveColor{Light: "#AFAD4C", Dark: "#DAE492"},
		lipgloss.AdaptiveColor{Light: "#9CB35F", Dark: "#CFEBAB"},
		lipgloss.AdaptiveColor{Light: "#8AB872", Dark: "#C8EFC0"},
		lipgloss.AdaptiveColor{Light: "#77BB83", Dark: "#C5F3D2"},
		lipgloss.AdaptiveColor{Light: "#62BE95", Dark: "#C7F5E1"},
		lipgloss.AdaptiveColor{Light: "#4CBFA6", Dark: "#CDF6ED"},
		lipgloss.AdaptiveColor{Light: "#32C0B9", Dark: "#D5F7F5"},
		lipgloss.AdaptiveColor{Light: "#10BFCC", Dark: "#E1F7FA"}, // == teal450
	},
	"wandb-vibe-10": {
		lipgloss.AdaptiveColor{Light: "#8A8D91", Dark: "#B1B4B9"},
		lipgloss.AdaptiveColor{Light: "#3DBAC4", Dark: "#58D3DB"},
		lipgloss.AdaptiveColor{Light: "#42B88A", Dark: "#5ED6A4"},
		lipgloss.AdaptiveColor{Light: "#E07040", Dark: "#FCA36F"},
		lipgloss.AdaptiveColor{Light: "#E85565", Dark: "#FF7A88"},
		lipgloss.AdaptiveColor{Light: "#5A96E0", Dark: "#7DB1FA"},
		lipgloss.AdaptiveColor{Light: "#9AC24A", Dark: "#BBE06B"},
		lipgloss.AdaptiveColor{Light: "#E0AD20", Dark: "#FFCF4D"},
		lipgloss.AdaptiveColor{Light: "#C85EE8", Dark: "#E180FF"},
		lipgloss.AdaptiveColor{Light: "#9475E8", Dark: "#B199FF"},
	},
	"wandb-vibe-20": {
		lipgloss.AdaptiveColor{Light: "#AEAFB3", Dark: "#D4D5D9"},
		lipgloss.AdaptiveColor{Light: "#454B54", Dark: "#565C66"},
		lipgloss.AdaptiveColor{Light: "#7AD4DB", Dark: "#A9EDF2"},
		lipgloss.AdaptiveColor{Light: "#04707F", Dark: "#038194"},
		lipgloss.AdaptiveColor{Light: "#6DDBA8", Dark: "#A1F0CB"},
		lipgloss.AdaptiveColor{Light: "#00704A", Dark: "#00875A"},
		lipgloss.AdaptiveColor{Light: "#EAB08A", Dark: "#FFCFB2"},
		lipgloss.AdaptiveColor{Light: "#A84728", Dark: "#C2562F"},
		lipgloss.AdaptiveColor{Light: "#EAA0A5", Dark: "#FFC7CA"},
		lipgloss.AdaptiveColor{Light: "#B82038", Dark: "#CC2944"},
		lipgloss.AdaptiveColor{Light: "#8FBDE8", Dark: "#BDD9FF"},
		lipgloss.AdaptiveColor{Light: "#2850A8", Dark: "#1F59C4"},
		lipgloss.AdaptiveColor{Light: "#B0D470", Dark: "#D0ED9D"},
		lipgloss.AdaptiveColor{Light: "#4E7424", Dark: "#5F8A2D"},
		lipgloss.AdaptiveColor{Light: "#EAC860", Dark: "#FFE49E"},
		lipgloss.AdaptiveColor{Light: "#9A5E10", Dark: "#B8740F"},
		lipgloss.AdaptiveColor{Light: "#D99DE8", Dark: "#EFC2FC"},
		lipgloss.AdaptiveColor{Light: "#8528A8", Dark: "#9E36C2"},
		lipgloss.AdaptiveColor{Light: "#B8A8E8", Dark: "#D6C9FF"},
		lipgloss.AdaptiveColor{Light: "#5538B0", Dark: "#6645D1"},
	},
}

// GraphColors returns the palette for the requested scheme.
//
// If the scheme is unknown, it falls back to DefaultColorScheme.
func GraphColors(scheme string) []lipgloss.AdaptiveColor {
	if colors, ok := colorSchemes[scheme]; ok {
		return colors
	}
	return colorSchemes[DefaultColorScheme]
}

// Metrics grid styles.
var (
	headerStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading)

	navInfoStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	headerContainerStyle = lipgloss.NewStyle().MarginLeft(1).MarginTop(0).MarginBottom(0)

	gridContainerStyle = lipgloss.NewStyle().MarginLeft(1).MarginRight(1)
)

// Chart styles.
var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(colorLayout)

	titleStyle = lipgloss.NewStyle().Foreground(colorAccent).Bold(true)

	seriesCountStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	focusedBorderStyle = borderStyle.BorderForeground(colorLayoutHighlight)

	axisStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	labelStyle = lipgloss.NewStyle().Foreground(colorText)

	inspectionLineStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	inspectionLegendStyle = lipgloss.NewStyle().
				Foreground(lipgloss.AdaptiveColor{Light: "#111111", Dark: "#EEEEEE"}).
				Background(lipgloss.AdaptiveColor{Light: "#EEEEEE", Dark: "#333333"})
)

// Status bar styles.
var (
	statusBarStyle = lipgloss.NewStyle().
		Foreground(moon900).
		Background(colorLayoutHighlight).
		Padding(0, StatusBarPadding)
)

// Run overview styles.
var (
	runOverviewSidebarSectionHeaderStyle = lipgloss.
						NewStyle().Bold(true).Foreground(colorSubheading)
	runOverviewSidebarSectionStyle    = lipgloss.NewStyle().Foreground(colorText).Bold(true)
	runOverviewSidebarKeyStyle        = lipgloss.NewStyle().Foreground(colorItemKey)
	runOverviewSidebarValueStyle      = lipgloss.NewStyle().Foreground(colorItemValue)
	runOverviewSidebarHighlightedItem = lipgloss.NewStyle().
						Foreground(colorDark).Background(colorSelectedRunStyle)
)

// Left sidebar styles.
var (
	leftSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	leftSidebarBorderStyle = lipgloss.NewStyle().
				Border(RightBorder).
				BorderForeground(colorLayout).
				BorderTop(false)
	leftSidebarHeaderStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(colorSubheading).
				MarginBottom(0)
	RightBorder = lipgloss.Border{
		Top:         string(unicodeSpace),
		Bottom:      string(unicodeSpace),
		Left:        "",
		Right:       string(boxLightVertical),
		TopLeft:     string(unicodeSpace),
		TopRight:    string(unicodeSpace),
		BottomLeft:  string(unicodeSpace),
		BottomRight: string(unicodeSpace),
	}
)

// Right sidebar styles.
var (
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	rightSidebarBorderStyle = lipgloss.NewStyle().
				Border(LeftBorder).
				BorderForeground(colorLayout).
				BorderTop(false)
	rightSidebarHeaderStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(colorSubheading).
				MarginLeft(0)
	LeftBorder = lipgloss.Border{
		Top:         string(unicodeSpace),
		Bottom:      string(unicodeSpace),
		Left:        string(boxLightVertical),
		Right:       "",
		TopLeft:     string(unicodeSpace),
		TopRight:    string(unicodeSpace),
		BottomLeft:  string(unicodeSpace),
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
	helpKeyStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading).Width(24)

	helpDescStyle = lipgloss.NewStyle().Foreground(colorText)

	helpSectionStyle = lipgloss.NewStyle().Bold(true).Foreground(colorHeading)

	helpContentStyle = lipgloss.NewStyle().MarginLeft(2).MarginTop(1)
)

// Workspace view mode styles.
var (
	workspaceTopMarginLines = 1
	workspaceHeaderLines    = 1
	runsSidebarBorderCols   = 2

	colorSelectedRunStyle = lipgloss.AdaptiveColor{
		Dark:  "#FCBC32",
		Light: "#FCBC32",
	}

	colorSelectedRunInactiveStyle = lipgloss.AdaptiveColor{
		Light: "#F5D28A",
		Dark:  "#6B5200",
	}

	evenRunStyle             = lipgloss.NewStyle()
	oddRunStyle              = lipgloss.NewStyle().Background(getOddRunStyleColor())
	selectedRunStyle         = lipgloss.NewStyle().Background(colorSelectedRunStyle)
	selectedRunInactiveStyle = lipgloss.NewStyle().Background(colorSelectedRunInactiveStyle)
)
