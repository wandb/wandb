package leet

import (
	"fmt"
	"image/color"
	"os"
	"sync"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
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
func blendRGB(r, g, b, tr, tg, tb uint8, alpha float64) color.Color {
	blend := func(base, target uint8) uint8 {
		return uint8(float64(base)*(1-alpha) + float64(target)*alpha)
	}
	return lipgloss.Color(fmt.Sprintf("#%02x%02x%02x",
		blend(r, tr), blend(g, tg), blend(b, tb),
	))
}

// getOddRunStyleColor returns a color 5% darker than the terminal background.
func getOddRunStyleColor() color.Color {
	initTerminalBg()

	if termBgDetected {
		return blendRGB(termBgR, termBgG, termBgB, 128, 128, 128, 0.05)
	}

	return compat.AdaptiveColor{
		Light: lipgloss.Color("#d0d0d0"),
		Dark:  lipgloss.Color("#1c1c1c"),
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
	// Single-run mode.
	DefaultMetricsGridRows = 4
	DefaultMetricsGridCols = 3
	DefaultSystemGridRows  = 6
	DefaultSystemGridCols  = 2

	// Workspace mode.
	DefaultWorkspaceMetricsGridRows = 3
	DefaultWorkspaceMetricsGridCols = 3
	DefaultWorkspaceSystemGridRows  = 3
	DefaultWorkspaceSystemGridCols  = 3
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

	// sidebarVerticalBorderCols is the width (in terminal columns)
	// consumed by a sidebar's vertical border.
	// Both LeftBorder and RightBorder draw a single vertical rule.
	sidebarVerticalBorderCols = 1

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

	// unicodeEmDash is the em dash.
	unicodeEmDash rune = '\u2014'

	// unicodeSpace is the regular whitespace.
	unicodeSpace rune = '\u0020'

	// mediumShadeBlock is a medium-shaded block.
	mediumShadeBlock rune = '\u2592' // ▒
)

// WANDB brand colors.
var (
	// Primary colors.
	moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
)

// Secondary colors.
var teal450 = compat.AdaptiveColor{
	Light: lipgloss.Color("#10BFCC"),
	Dark:  lipgloss.Color("#E1F7FA"),
}

// Functional colors not specific to any visual component.
var (
	// Color for main items such as chart titles.
	colorAccent = compat.AdaptiveColor{
		Light: lipgloss.Color("#6c6c6c"),
		Dark:  lipgloss.Color("#bcbcbc"),
	}

	// Main text color that appears the most frequently on the screen.
	colorText = compat.AdaptiveColor{
		Light: lipgloss.Color("#8a8a8a"), // ANSI color 245
		Dark:  lipgloss.Color("#8a8a8a"),
	}

	// Color for extra or parenthetical text or information.
	// Axis lines in charts.
	colorSubtle = compat.AdaptiveColor{
		Light: lipgloss.Color("#585858"), // ANSI color 240
		Dark:  lipgloss.Color("#585858"),
	}

	// Color for layout elements, like borders and separator lines.
	colorLayout = compat.AdaptiveColor{
		Light: lipgloss.Color("#949494"),
		Dark:  lipgloss.Color("#444444"),
	}

	colorDark = lipgloss.Color("#171717")

	// Color for layout elements when they're highlighted or focused.
	colorLayoutHighlight = teal450

	// Color for top-level headings; least frequent.
	// Leet logo, help page section headings.
	colorHeading = wandbColor

	// Color for lower-level headings; more frequent than headings.
	// Help page keys, metrics grid header.
	colorSubheading = compat.AdaptiveColor{
		Light: lipgloss.Color("#3a3a3a"),
		Dark:  lipgloss.Color("#eeeeee"),
	}

	// Colors for key-value pairs such as run summary or config items.
	colorItemKey   = lipgloss.Color("243")
	colorItemValue = compat.AdaptiveColor{
		Light: lipgloss.Color("#262626"),
		Dark:  lipgloss.Color("#d0d0d0"),
	}

	// Color used for the selected line in lists.
	colorSelected = compat.AdaptiveColor{
		Dark:  lipgloss.Color("#FCBC32"),
		Light: lipgloss.Color("#FCBC32"),
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
var colorSchemes = map[string][]compat.AdaptiveColor{
	"sunset-glow": { // Golden-pink gradient
		compat.AdaptiveColor{Light: lipgloss.Color("#B84FD4"), Dark: lipgloss.Color("#E281FE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#BD5AB9"), Dark: lipgloss.Color("#E78DE3")},
		compat.AdaptiveColor{Light: lipgloss.Color("#BF60AB"), Dark: lipgloss.Color("#E993D5")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C36C91"), Dark: lipgloss.Color("#ED9FBB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C67283"), Dark: lipgloss.Color("#F0A5AD")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C87875"), Dark: lipgloss.Color("#F2AB9F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#CC8451"), Dark: lipgloss.Color("#F6B784")},
		compat.AdaptiveColor{Light: lipgloss.Color("#CE8A45"), Dark: lipgloss.Color("#F8BD78")},
		compat.AdaptiveColor{Light: lipgloss.Color("#D19038"), Dark: lipgloss.Color("#FBC36B")},
		compat.AdaptiveColor{Light: lipgloss.Color("#D59C1C"), Dark: lipgloss.Color("#FFCF4F")},
	},
	"blush-tide": { // Pink-teal gradient
		compat.AdaptiveColor{Light: lipgloss.Color("#D94F8C"), Dark: lipgloss.Color("#F9A7CC")},
		compat.AdaptiveColor{Light: lipgloss.Color("#CA60AC"), Dark: lipgloss.Color("#EEB3E0")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B96FC4"), Dark: lipgloss.Color("#E4BFEE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#A77DD4"), Dark: lipgloss.Color("#DBC9F7")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9489DF"), Dark: lipgloss.Color("#D5D3FC")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8095E5"), Dark: lipgloss.Color("#D1DCFE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#6AA1E6"), Dark: lipgloss.Color("#D0E5FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#50ACE2"), Dark: lipgloss.Color("#D3ECFE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#33B6D9"), Dark: lipgloss.Color("#D8F2FC")},
		compat.AdaptiveColor{
			Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#E1F7FA")}, // == teal450
	},
	"gilded-lagoon": { // Golden-teal gradient
		compat.AdaptiveColor{Light: lipgloss.Color("#D59C1C"), Dark: lipgloss.Color("#FFCF4F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C2A636"), Dark: lipgloss.Color("#EADB74")},
		compat.AdaptiveColor{Light: lipgloss.Color("#AFAD4C"), Dark: lipgloss.Color("#DAE492")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9CB35F"), Dark: lipgloss.Color("#CFEBAB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8AB872"), Dark: lipgloss.Color("#C8EFC0")},
		compat.AdaptiveColor{Light: lipgloss.Color("#77BB83"), Dark: lipgloss.Color("#C5F3D2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#62BE95"), Dark: lipgloss.Color("#C7F5E1")},
		compat.AdaptiveColor{Light: lipgloss.Color("#4CBFA6"), Dark: lipgloss.Color("#CDF6ED")},
		compat.AdaptiveColor{Light: lipgloss.Color("#32C0B9"), Dark: lipgloss.Color("#D5F7F5")},
		compat.AdaptiveColor{
			Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#E1F7FA")}, // == teal450
	},
	"wandb-vibe-10": {
		compat.AdaptiveColor{Light: lipgloss.Color("#8A8D91"), Dark: lipgloss.Color("#B1B4B9")},
		compat.AdaptiveColor{Light: lipgloss.Color("#3DBAC4"), Dark: lipgloss.Color("#58D3DB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#42B88A"), Dark: lipgloss.Color("#5ED6A4")},
		compat.AdaptiveColor{Light: lipgloss.Color("#E07040"), Dark: lipgloss.Color("#FCA36F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#E85565"), Dark: lipgloss.Color("#FF7A88")},
		compat.AdaptiveColor{Light: lipgloss.Color("#5A96E0"), Dark: lipgloss.Color("#7DB1FA")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9AC24A"), Dark: lipgloss.Color("#BBE06B")},
		compat.AdaptiveColor{Light: lipgloss.Color("#E0AD20"), Dark: lipgloss.Color("#FFCF4D")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C85EE8"), Dark: lipgloss.Color("#E180FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9475E8"), Dark: lipgloss.Color("#B199FF")},
	},
	"wandb-vibe-20": {
		compat.AdaptiveColor{Light: lipgloss.Color("#AEAFB3"), Dark: lipgloss.Color("#D4D5D9")},
		compat.AdaptiveColor{Light: lipgloss.Color("#454B54"), Dark: lipgloss.Color("#565C66")},
		compat.AdaptiveColor{Light: lipgloss.Color("#7AD4DB"), Dark: lipgloss.Color("#A9EDF2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#04707F"), Dark: lipgloss.Color("#038194")},
		compat.AdaptiveColor{Light: lipgloss.Color("#6DDBA8"), Dark: lipgloss.Color("#A1F0CB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#00704A"), Dark: lipgloss.Color("#00875A")},
		compat.AdaptiveColor{Light: lipgloss.Color("#EAB08A"), Dark: lipgloss.Color("#FFCFB2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#A84728"), Dark: lipgloss.Color("#C2562F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#EAA0A5"), Dark: lipgloss.Color("#FFC7CA")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B82038"), Dark: lipgloss.Color("#CC2944")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8FBDE8"), Dark: lipgloss.Color("#BDD9FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#2850A8"), Dark: lipgloss.Color("#1F59C4")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B0D470"), Dark: lipgloss.Color("#D0ED9D")},
		compat.AdaptiveColor{Light: lipgloss.Color("#4E7424"), Dark: lipgloss.Color("#5F8A2D")},
		compat.AdaptiveColor{Light: lipgloss.Color("#EAC860"), Dark: lipgloss.Color("#FFE49E")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9A5E10"), Dark: lipgloss.Color("#B8740F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#D99DE8"), Dark: lipgloss.Color("#EFC2FC")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8528A8"), Dark: lipgloss.Color("#9E36C2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B8A8E8"), Dark: lipgloss.Color("#D6C9FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#5538B0"), Dark: lipgloss.Color("#6645D1")},
	},
}

// GraphColors returns the palette for the requested scheme.
//
// If the scheme is unknown, it falls back to DefaultColorScheme.
func GraphColors(scheme string) []compat.AdaptiveColor {
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
				Foreground(compat.AdaptiveColor{
			Light: lipgloss.Color("#111111"),
			Dark:  lipgloss.Color("#EEEEEE"),
		}).
		Background(compat.AdaptiveColor{
			Light: lipgloss.Color("#EEEEEE"),
			Dark:  lipgloss.Color("#333333"),
		})
)

// Status bar styles.
var (
	statusBarStyle = lipgloss.NewStyle().
		Foreground(moon900).
		Background(colorLayoutHighlight).
		Padding(0, StatusBarPadding)
)

var errorStyle = lipgloss.NewStyle()

// Run overview styles.
var (
	runOverviewSidebarSectionHeaderStyle = lipgloss.
						NewStyle().Bold(true).Foreground(colorSubheading)
	runOverviewSidebarSectionStyle    = lipgloss.NewStyle().Foreground(colorText).Bold(true)
	runOverviewSidebarKeyStyle        = lipgloss.NewStyle().Foreground(colorItemKey)
	runOverviewSidebarValueStyle      = lipgloss.NewStyle().Foreground(colorItemValue)
	runOverviewSidebarHighlightedItem = lipgloss.NewStyle().
						Foreground(colorDark).Background(colorSelected)
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
	rightSidebarStyle       = lipgloss.NewStyle().PaddingLeft(1)
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

// Console logs pane styles.
var (
	consoleLogsPaneBorderStyle = lipgloss.NewStyle().
					Border(topOnlyBorder).
					BorderForeground(colorLayout).
					BorderTop(true).
					BorderBottom(false).
					BorderLeft(false).
					BorderRight(false).
					PaddingBottom(1)

	consoleLogsPaneHeaderStyle = lipgloss.NewStyle().
					Bold(true).
					Foreground(colorSubheading).
					PaddingLeft(1)

	consoleLogsPaneTimestampStyle = lipgloss.NewStyle().
					Foreground(colorSubtle).
					PaddingLeft(1)

	consoleLogsPaneValueStyle = lipgloss.NewStyle().
					Foreground(colorItemValue)

	consoleLogsPaneHighlightedTimestampStyle = lipgloss.NewStyle().
							Background(colorSelected).
							Foreground(colorDark).
							PaddingLeft(1)

	consoleLogsPaneHighlightedValueStyle = lipgloss.NewStyle().
						Background(colorSelected).
						Foreground(colorDark)

	// topOnlyBorder draws a single horizontal line at the top of the box.
	topOnlyBorder = lipgloss.Border{
		Top:         string(unicodeEmDash),
		Bottom:      "",
		Left:        "",
		Right:       "",
		TopLeft:     string(unicodeEmDash),
		TopRight:    string(unicodeEmDash),
		BottomLeft:  "",
		BottomRight: "",
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

	colorSelectedRunInactiveStyle = compat.AdaptiveColor{
		Light: lipgloss.Color("#F5D28A"),
		Dark:  lipgloss.Color("#6B5200"),
	}

	evenRunStyle             = lipgloss.NewStyle()
	oddRunStyle              = lipgloss.NewStyle().Background(getOddRunStyleColor())
	selectedRunStyle         = lipgloss.NewStyle().Background(colorSelected)
	selectedRunInactiveStyle = lipgloss.NewStyle().Background(colorSelectedRunInactiveStyle)
)
