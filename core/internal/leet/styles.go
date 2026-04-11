package leet

import (
	"fmt"
	"image/color"
	"math"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"charm.land/lipgloss/v2"
	"github.com/muesli/termenv"
)

// darkBackground tracks whether the terminal has a dark background.
// Default is true (most terminals are dark). Updated at runtime when
// Bubble Tea delivers tea.BackgroundColorMsg — no terminal query at
// package init, which avoids hangs on Windows.
var darkBackground atomic.Bool

func init() { darkBackground.Store(true) }

// SetDarkBackground updates the cached terminal-background flag.
// Call this from your Bubble Tea Update when you receive
// tea.BackgroundColorMsg.
func SetDarkBackground(dark bool) { darkBackground.Store(dark) }

// IsDarkBackground reports the current cached value.
func IsDarkBackground() bool { return darkBackground.Load() }

// AdaptiveColor picks between Light and Dark variants based on the
// terminal background, using the lipgloss v2 LightDark API.
// This replaces charm.land/lipgloss/v2/AdaptiveColor.
type AdaptiveColor struct {
	Light color.Color
	Dark  color.Color
}

// RGBA implements color.Color by delegating to the appropriate variant.
func (c AdaptiveColor) RGBA() (uint32, uint32, uint32, uint32) {
	return lipgloss.LightDark(darkBackground.Load())(c.Light, c.Dark).RGBA()
}

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

	return AdaptiveColor{
		Light: lipgloss.Color("#d0d0d0"),
		Dark:  lipgloss.Color("#1c1c1c"),
	}
}

// Immutable UI constants.
const (
	StatusBarHeight = 1
	// Horizontal padding for the status bar (left and right).
	StatusBarPadding = 1

	// ContentPadding is the number of blank columns on each side of every
	// content area (sidebars, main-column panes, status bar). This is the
	// single source of truth for horizontal content insets.
	ContentPadding = 1

	// ContentPaddingCols is the total horizontal columns consumed by
	// ContentPadding (left + right).
	ContentPaddingCols = 2 * ContentPadding

	// SidebarBorderCols is the single terminal column occupied by a
	// sidebar's vertical border rule (│).
	SidebarBorderCols = 1

	// SidebarOverhead is the total non-content columns inside a sidebar:
	// one vertical border + ContentPadding on each side.
	SidebarOverhead = SidebarBorderCols + ContentPaddingCols

	// SidebarBottomPadding is the blank row at the bottom of a sidebar
	// that separates content from the status bar.
	SidebarBottomPadding = 1

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

	// Standalone system monitor mode.
	DefaultSymonGridRows = 3
	DefaultSymonGridCols = 3
)

// Sidebar constants.
const (
	// We are using the golden ratio `phi` for visually pleasing layout proportions.
	SidebarWidthRatio     = 0.382 // 1 - 1/phi
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: (1 - 1/phi) / phi ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 120

	// Key/value column width ratio.
	sidebarKeyWidthRatio = 0.4 // 40% of available width for keys

	// Default grid height for system metrics when not calculated from terminal height.
	defaultSystemMetricsGridHeight = 40
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

func uniformAdaptiveColor(hex string) AdaptiveColor {
	c := lipgloss.Color(hex)
	return AdaptiveColor{Light: c, Dark: c}
}

// WANDB brand colors.
var (
	// Primary colors.
	moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
)

// Secondary colors.
var teal450 = AdaptiveColor{
	Light: lipgloss.Color("#10BFCC"),
	Dark:  lipgloss.Color("#E1F7FA"),
}

// Functional colors not specific to any visual component.
var (
	// Color for main items such as chart titles.
	colorAccent = AdaptiveColor{
		Light: lipgloss.Color("#6c6c6c"),
		Dark:  lipgloss.Color("#bcbcbc"),
	}

	// Main text color that appears the most frequently on the screen.
	colorText = AdaptiveColor{
		Light: lipgloss.Color("#8a8a8a"), // ANSI color 245
		Dark:  lipgloss.Color("#8a8a8a"),
	}

	// Color for extra or parenthetical text or information.
	// Axis lines in charts.
	colorSubtle = AdaptiveColor{
		Light: lipgloss.Color("#585858"), // ANSI color 240
		Dark:  lipgloss.Color("#585858"),
	}

	// Color for layout elements, like borders and separator lines.
	colorLayout = AdaptiveColor{
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
	colorSubheading = AdaptiveColor{
		Light: lipgloss.Color("#3a3a3a"),
		Dark:  lipgloss.Color("#eeeeee"),
	}

	// Colors for key-value pairs such as run summary or config items.
	colorItemKey   = lipgloss.Color("243")
	colorItemValue = AdaptiveColor{
		Light: lipgloss.Color("#262626"),
		Dark:  lipgloss.Color("#d0d0d0"),
	}

	// Color used for the selected line in lists.
	colorSelected = AdaptiveColor{
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
var colorSchemes = map[string][]AdaptiveColor{
	"sunset-glow": { // Golden-pink gradient
		AdaptiveColor{Light: lipgloss.Color("#B84FD4"), Dark: lipgloss.Color("#E281FE")},
		AdaptiveColor{Light: lipgloss.Color("#BD5AB9"), Dark: lipgloss.Color("#E78DE3")},
		AdaptiveColor{Light: lipgloss.Color("#BF60AB"), Dark: lipgloss.Color("#E993D5")},
		AdaptiveColor{Light: lipgloss.Color("#C36C91"), Dark: lipgloss.Color("#ED9FBB")},
		AdaptiveColor{Light: lipgloss.Color("#C67283"), Dark: lipgloss.Color("#F0A5AD")},
		AdaptiveColor{Light: lipgloss.Color("#C87875"), Dark: lipgloss.Color("#F2AB9F")},
		AdaptiveColor{Light: lipgloss.Color("#CC8451"), Dark: lipgloss.Color("#F6B784")},
		AdaptiveColor{Light: lipgloss.Color("#CE8A45"), Dark: lipgloss.Color("#F8BD78")},
		AdaptiveColor{Light: lipgloss.Color("#D19038"), Dark: lipgloss.Color("#FBC36B")},
		AdaptiveColor{Light: lipgloss.Color("#D59C1C"), Dark: lipgloss.Color("#FFCF4F")},
	},
	"blush-tide": { // Pink-teal gradient
		AdaptiveColor{Light: lipgloss.Color("#D94F8C"), Dark: lipgloss.Color("#F9A7CC")},
		AdaptiveColor{Light: lipgloss.Color("#CA60AC"), Dark: lipgloss.Color("#EEB3E0")},
		AdaptiveColor{Light: lipgloss.Color("#B96FC4"), Dark: lipgloss.Color("#E4BFEE")},
		AdaptiveColor{Light: lipgloss.Color("#A77DD4"), Dark: lipgloss.Color("#DBC9F7")},
		AdaptiveColor{Light: lipgloss.Color("#9489DF"), Dark: lipgloss.Color("#D5D3FC")},
		AdaptiveColor{Light: lipgloss.Color("#8095E5"), Dark: lipgloss.Color("#D1DCFE")},
		AdaptiveColor{Light: lipgloss.Color("#6AA1E6"), Dark: lipgloss.Color("#D0E5FF")},
		AdaptiveColor{Light: lipgloss.Color("#50ACE2"), Dark: lipgloss.Color("#D3ECFE")},
		AdaptiveColor{Light: lipgloss.Color("#33B6D9"), Dark: lipgloss.Color("#D8F2FC")},
		AdaptiveColor{
			Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#E1F7FA")}, // == teal450
	},
	"gilded-lagoon": { // Golden-teal gradient
		AdaptiveColor{Light: lipgloss.Color("#D59C1C"), Dark: lipgloss.Color("#FFCF4F")},
		AdaptiveColor{Light: lipgloss.Color("#C2A636"), Dark: lipgloss.Color("#EADB74")},
		AdaptiveColor{Light: lipgloss.Color("#AFAD4C"), Dark: lipgloss.Color("#DAE492")},
		AdaptiveColor{Light: lipgloss.Color("#9CB35F"), Dark: lipgloss.Color("#CFEBAB")},
		AdaptiveColor{Light: lipgloss.Color("#8AB872"), Dark: lipgloss.Color("#C8EFC0")},
		AdaptiveColor{Light: lipgloss.Color("#77BB83"), Dark: lipgloss.Color("#C5F3D2")},
		AdaptiveColor{Light: lipgloss.Color("#62BE95"), Dark: lipgloss.Color("#C7F5E1")},
		AdaptiveColor{Light: lipgloss.Color("#4CBFA6"), Dark: lipgloss.Color("#CDF6ED")},
		AdaptiveColor{Light: lipgloss.Color("#32C0B9"), Dark: lipgloss.Color("#D5F7F5")},
		AdaptiveColor{
			Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#E1F7FA")}, // == teal450
	},
	"bootstrap-vibe": { // Badge-friendly palette with familiar utility tones
		AdaptiveColor{Light: lipgloss.Color("#6c757d"), Dark: lipgloss.Color("#a7b0b8")},
		AdaptiveColor{Light: lipgloss.Color("#0d6efd"), Dark: lipgloss.Color("#78aefc")},
		AdaptiveColor{Light: lipgloss.Color("#198754"), Dark: lipgloss.Color("#72cf9d")},
		AdaptiveColor{Light: lipgloss.Color("#0dcaf0"), Dark: lipgloss.Color("#7be3fa")},
		AdaptiveColor{Light: lipgloss.Color("#fd7e14"), Dark: lipgloss.Color("#ffb574")},
		AdaptiveColor{Light: lipgloss.Color("#dc3545"), Dark: lipgloss.Color("#f28a93")},
		AdaptiveColor{Light: lipgloss.Color("#6f42c1"), Dark: lipgloss.Color("#b99aff")},
		AdaptiveColor{Light: lipgloss.Color("#20c997"), Dark: lipgloss.Color("#83e6ca")},
	},
	"wandb-vibe-10": {
		AdaptiveColor{Light: lipgloss.Color("#8A8D91"), Dark: lipgloss.Color("#B1B4B9")},
		AdaptiveColor{Light: lipgloss.Color("#3DBAC4"), Dark: lipgloss.Color("#58D3DB")},
		AdaptiveColor{Light: lipgloss.Color("#42B88A"), Dark: lipgloss.Color("#5ED6A4")},
		AdaptiveColor{Light: lipgloss.Color("#E07040"), Dark: lipgloss.Color("#FCA36F")},
		AdaptiveColor{Light: lipgloss.Color("#E85565"), Dark: lipgloss.Color("#FF7A88")},
		AdaptiveColor{Light: lipgloss.Color("#5A96E0"), Dark: lipgloss.Color("#7DB1FA")},
		AdaptiveColor{Light: lipgloss.Color("#9AC24A"), Dark: lipgloss.Color("#BBE06B")},
		AdaptiveColor{Light: lipgloss.Color("#E0AD20"), Dark: lipgloss.Color("#FFCF4D")},
		AdaptiveColor{Light: lipgloss.Color("#C85EE8"), Dark: lipgloss.Color("#E180FF")},
		AdaptiveColor{Light: lipgloss.Color("#9475E8"), Dark: lipgloss.Color("#B199FF")},
	},
	"wandb-vibe-20": {
		AdaptiveColor{Light: lipgloss.Color("#AEAFB3"), Dark: lipgloss.Color("#D4D5D9")},
		AdaptiveColor{Light: lipgloss.Color("#454B54"), Dark: lipgloss.Color("#565C66")},
		AdaptiveColor{Light: lipgloss.Color("#7AD4DB"), Dark: lipgloss.Color("#A9EDF2")},
		AdaptiveColor{Light: lipgloss.Color("#04707F"), Dark: lipgloss.Color("#038194")},
		AdaptiveColor{Light: lipgloss.Color("#6DDBA8"), Dark: lipgloss.Color("#A1F0CB")},
		AdaptiveColor{Light: lipgloss.Color("#00704A"), Dark: lipgloss.Color("#00875A")},
		AdaptiveColor{Light: lipgloss.Color("#EAB08A"), Dark: lipgloss.Color("#FFCFB2")},
		AdaptiveColor{Light: lipgloss.Color("#A84728"), Dark: lipgloss.Color("#C2562F")},
		AdaptiveColor{Light: lipgloss.Color("#EAA0A5"), Dark: lipgloss.Color("#FFC7CA")},
		AdaptiveColor{Light: lipgloss.Color("#B82038"), Dark: lipgloss.Color("#CC2944")},
		AdaptiveColor{Light: lipgloss.Color("#8FBDE8"), Dark: lipgloss.Color("#BDD9FF")},
		AdaptiveColor{Light: lipgloss.Color("#2850A8"), Dark: lipgloss.Color("#1F59C4")},
		AdaptiveColor{Light: lipgloss.Color("#B0D470"), Dark: lipgloss.Color("#D0ED9D")},
		AdaptiveColor{Light: lipgloss.Color("#4E7424"), Dark: lipgloss.Color("#5F8A2D")},
		AdaptiveColor{Light: lipgloss.Color("#EAC860"), Dark: lipgloss.Color("#FFE49E")},
		AdaptiveColor{Light: lipgloss.Color("#9A5E10"), Dark: lipgloss.Color("#B8740F")},
		AdaptiveColor{Light: lipgloss.Color("#D99DE8"), Dark: lipgloss.Color("#EFC2FC")},
		AdaptiveColor{Light: lipgloss.Color("#8528A8"), Dark: lipgloss.Color("#9E36C2")},
		AdaptiveColor{Light: lipgloss.Color("#B8A8E8"), Dark: lipgloss.Color("#D6C9FF")},
		AdaptiveColor{Light: lipgloss.Color("#5538B0"), Dark: lipgloss.Color("#6645D1")},
	},
	// This palette has been tested with deuteranopia, protanopia, and tritanopia
	// simulators. Those forms of color blindness are less common than deuteranomaly.
	// This palette focuses on siennas/blues/grays only, which
	// are commonly colorblind-friendly across most forms of color blindness.
	// Gradient ordering: warm siennas → cool blues → neutral grays.
	"dusk-shore": {
		AdaptiveColor{Light: lipgloss.Color("#823520"), Dark: lipgloss.Color("#994228")},
		AdaptiveColor{Light: lipgloss.Color("#A84728"), Dark: lipgloss.Color("#C2562F")},
		AdaptiveColor{Light: lipgloss.Color("#BA5028"), Dark: lipgloss.Color("#D96534")},
		AdaptiveColor{Light: lipgloss.Color("#D86030"), Dark: lipgloss.Color("#FC8F58")},
		AdaptiveColor{Light: lipgloss.Color("#E07040"), Dark: lipgloss.Color("#FCA36F")},
		AdaptiveColor{Light: lipgloss.Color("#E89865"), Dark: lipgloss.Color("#FFBA91")},
		AdaptiveColor{Light: lipgloss.Color("#EAB08A"), Dark: lipgloss.Color("#FFCFB2")},
		AdaptiveColor{Light: lipgloss.Color("#78A8E8"), Dark: lipgloss.Color("#A4C9FC")},
		AdaptiveColor{Light: lipgloss.Color("#5A96E0"), Dark: lipgloss.Color("#7DB1FA")},
		AdaptiveColor{Light: lipgloss.Color("#4880DA"), Dark: lipgloss.Color("#629DF5")},
		AdaptiveColor{Light: lipgloss.Color("#2E68CC"), Dark: lipgloss.Color("#397EED")},
		AdaptiveColor{Light: lipgloss.Color("#2258BE"), Dark: lipgloss.Color("#286CE0")},
		AdaptiveColor{Light: lipgloss.Color("#2850A8"), Dark: lipgloss.Color("#1F59C4")},
		AdaptiveColor{Light: lipgloss.Color("#8A8D91"), Dark: lipgloss.Color("#B1B4B9")},
		AdaptiveColor{Light: lipgloss.Color("#606872"), Dark: lipgloss.Color("#79808A")},
		AdaptiveColor{Light: lipgloss.Color("#454B54"), Dark: lipgloss.Color("#565C66")},
	},
	// Same colorblind-friendly sienna/blue/gray palette as "dusk-shore", but with
	// colors interleaved for maximum visual differentiation between adjacent series.
	"clear-signal": {
		AdaptiveColor{Light: lipgloss.Color("#BA5028"), Dark: lipgloss.Color("#D96534")},
		AdaptiveColor{Light: lipgloss.Color("#2258BE"), Dark: lipgloss.Color("#286CE0")},
		AdaptiveColor{Light: lipgloss.Color("#4880DA"), Dark: lipgloss.Color("#629DF5")},
		AdaptiveColor{Light: lipgloss.Color("#823520"), Dark: lipgloss.Color("#994228")},
		AdaptiveColor{Light: lipgloss.Color("#E07040"), Dark: lipgloss.Color("#FCA36F")},
		AdaptiveColor{Light: lipgloss.Color("#EAB08A"), Dark: lipgloss.Color("#FFCFB2")},
		AdaptiveColor{Light: lipgloss.Color("#8A8D91"), Dark: lipgloss.Color("#B1B4B9")},
		AdaptiveColor{Light: lipgloss.Color("#606872"), Dark: lipgloss.Color("#79808A")},
		AdaptiveColor{Light: lipgloss.Color("#5A96E0"), Dark: lipgloss.Color("#7DB1FA")},
		AdaptiveColor{Light: lipgloss.Color("#2850A8"), Dark: lipgloss.Color("#1F59C4")},
		AdaptiveColor{Light: lipgloss.Color("#A84728"), Dark: lipgloss.Color("#C2562F")},
		AdaptiveColor{Light: lipgloss.Color("#D86030"), Dark: lipgloss.Color("#FC8F58")},
		AdaptiveColor{Light: lipgloss.Color("#E89865"), Dark: lipgloss.Color("#FFBA91")},
		AdaptiveColor{Light: lipgloss.Color("#78A8E8"), Dark: lipgloss.Color("#A4C9FC")},
		AdaptiveColor{Light: lipgloss.Color("#2E68CC"), Dark: lipgloss.Color("#397EED")},
		AdaptiveColor{Light: lipgloss.Color("#454B54"), Dark: lipgloss.Color("#565C66")},
	},
	// Sequential palettes suitable for French Fries percentage heatmaps.
	"traffic-light": {
		uniformAdaptiveColor("#1A9850"),
		uniformAdaptiveColor("#3EAE51"),
		uniformAdaptiveColor("#67C35C"),
		uniformAdaptiveColor("#97D168"),
		uniformAdaptiveColor("#C8DE72"),
		uniformAdaptiveColor("#F1DD6B"),
		uniformAdaptiveColor("#FDB863"),
		uniformAdaptiveColor("#F89C5A"),
		uniformAdaptiveColor("#F67C4B"),
		uniformAdaptiveColor("#E85D4F"),
		uniformAdaptiveColor("#D73027"),
	},
	"viridis": {
		uniformAdaptiveColor("#440154"),
		uniformAdaptiveColor("#482475"),
		uniformAdaptiveColor("#414487"),
		uniformAdaptiveColor("#355F8D"),
		uniformAdaptiveColor("#2A788E"),
		uniformAdaptiveColor("#21918C"),
		uniformAdaptiveColor("#22A884"),
		uniformAdaptiveColor("#44BF70"),
		uniformAdaptiveColor("#7AD151"),
		uniformAdaptiveColor("#BDDF26"),
		uniformAdaptiveColor("#FDE725"),
	},
	"plasma": {
		uniformAdaptiveColor("#0D0887"),
		uniformAdaptiveColor("#41049D"),
		uniformAdaptiveColor("#6A00A8"),
		uniformAdaptiveColor("#8F0DA4"),
		uniformAdaptiveColor("#B12A90"),
		uniformAdaptiveColor("#CC4778"),
		uniformAdaptiveColor("#E16462"),
		uniformAdaptiveColor("#F2844B"),
		uniformAdaptiveColor("#FCA636"),
		uniformAdaptiveColor("#FCCE25"),
		uniformAdaptiveColor("#F0F921"),
	},
	"inferno": {
		uniformAdaptiveColor("#000004"),
		uniformAdaptiveColor("#160B39"),
		uniformAdaptiveColor("#420A68"),
		uniformAdaptiveColor("#6A176E"),
		uniformAdaptiveColor("#932667"),
		uniformAdaptiveColor("#BC3754"),
		uniformAdaptiveColor("#DD513A"),
		uniformAdaptiveColor("#F37819"),
		uniformAdaptiveColor("#FCA50A"),
		uniformAdaptiveColor("#F6D746"),
		uniformAdaptiveColor("#FCFFA4"),
	},
	"magma": {
		uniformAdaptiveColor("#000004"),
		uniformAdaptiveColor("#140E36"),
		uniformAdaptiveColor("#3B0F70"),
		uniformAdaptiveColor("#641A80"),
		uniformAdaptiveColor("#8C2981"),
		uniformAdaptiveColor("#B73779"),
		uniformAdaptiveColor("#DE4968"),
		uniformAdaptiveColor("#F7705C"),
		uniformAdaptiveColor("#FE9F6D"),
		uniformAdaptiveColor("#FECF92"),
		uniformAdaptiveColor("#FCFDBF"),
	},
	"cividis": {
		uniformAdaptiveColor("#00224E"),
		uniformAdaptiveColor("#083370"),
		uniformAdaptiveColor("#35456C"),
		uniformAdaptiveColor("#4F576C"),
		uniformAdaptiveColor("#666970"),
		uniformAdaptiveColor("#7D7C78"),
		uniformAdaptiveColor("#948E77"),
		uniformAdaptiveColor("#AEA371"),
		uniformAdaptiveColor("#C8B866"),
		uniformAdaptiveColor("#E5CF52"),
		uniformAdaptiveColor("#FEE838"),
	},
}

func colorSchemeOrDefault(scheme, fallback string) []AdaptiveColor {
	if colors, ok := colorSchemes[scheme]; ok && len(colors) > 0 {
		return colors
	}
	return colorSchemes[fallback]
}

// GraphColors returns the palette for the requested scheme.
//
// If the scheme is unknown, it falls back to DefaultColorScheme.
func GraphColors(scheme string) []AdaptiveColor {
	return colorSchemeOrDefault(scheme, DefaultColorScheme)
}

// FrenchFriesColors returns the palette for the requested French Fries heatmap scheme.
//
// If the scheme is unknown, it falls back to DefaultFrenchFriesColorScheme.
func FrenchFriesColors(scheme string) []AdaptiveColor {
	return colorSchemeOrDefault(scheme, DefaultFrenchFriesColorScheme)
}

// Metrics grid styles.
//
// Main-column panes must render exactly the width assigned by the layout.
// Do not add external margins here: even a 1-column margin makes the
// composed row wider than its allocated box, which clips the rightmost column
// and can force an extra terminal wrap line.
var (
	headerStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading)

	navInfoStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	headerContainerStyle = lipgloss.NewStyle()

	gridContainerStyle = lipgloss.NewStyle()
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
				Foreground(AdaptiveColor{
			Light: lipgloss.Color("#111111"),
			Dark:  lipgloss.Color("#EEEEEE"),
		}).
		Background(AdaptiveColor{
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

// runOverviewTagLightText is the default (white) foreground for tag badges
// when the background is too dark for dark text to be legible.
var runOverviewTagLightText = lipgloss.Color("#ffffff")

// runOverviewTagBackgroundColor returns the background color for a tag badge.
// It deterministically maps tag to a color in the given scheme so that the
// same tag always gets the same color.
func runOverviewTagBackgroundColor(scheme, tag string) AdaptiveColor {
	colors := GraphColors(scheme)
	return colors[colorIndex(tag, len(colors))]
}

// runOverviewTagForegroundColor picks a foreground color (light or dark) for
// each adaptive variant of bg that satisfies WCAG contrast requirements.
func runOverviewTagForegroundColor(bg AdaptiveColor) AdaptiveColor {
	return AdaptiveColor{
		Light: runOverviewTagTextColor(bg.Light),
		Dark:  runOverviewTagTextColor(bg.Dark),
	}
}

// runOverviewTagTextColor returns white or dark text for a single background
// color, choosing whichever yields the higher WCAG contrast ratio.
func runOverviewTagTextColor(bg any) color.Color {
	r, g, b, ok := parseHexColor(fmt.Sprint(bg))
	if !ok {
		return runOverviewTagLightText
	}

	lightContrast := contrastRatioRGB(r, g, b, 0xff, 0xff, 0xff)
	darkContrast := contrastRatioRGB(r, g, b, 0x17, 0x17, 0x17)
	if darkContrast >= lightContrast {
		return colorDark
	}

	return runOverviewTagLightText
}

// parseHexColor extracts 8-bit RGB components from a "#RRGGBB" hex string.
// It returns false if hex is not in the expected format.
func parseHexColor(hex string) (uint8, uint8, uint8, bool) {
	var r, g, b uint8
	if _, err := fmt.Sscanf(hex, "#%02x%02x%02x", &r, &g, &b); err != nil {
		return 0, 0, 0, false
	}
	return r, g, b, true
}

// contrastRatioRGB computes the WCAG 2.x contrast ratio between two RGB colors.
// The returned value ranges from 1 (identical) to 21 (black vs white).
func contrastRatioRGB(r1, g1, b1, r2, g2, b2 uint8) float64 {
	l1 := relativeLuminance(r1, g1, b1)
	l2 := relativeLuminance(r2, g2, b2)
	if l1 < l2 {
		l1, l2 = l2, l1
	}
	return (l1 + 0.05) / (l2 + 0.05)
}

// relativeLuminance returns the WCAG relative luminance of an sRGB color.
// See https://www.w3.org/TR/WCAG21/#dfn-relative-luminance.
//
// Note: WCAG = Web Content Accessibility Guidelines.
func relativeLuminance(r, g, b uint8) float64 {
	return 0.2126*srgbToLinear(r) + 0.7152*srgbToLinear(g) + 0.0722*srgbToLinear(b)
}

// srgbToLinear converts a single 8-bit sRGB channel value to linear-light
// using the IEC 61966-2-1 transfer function.
func srgbToLinear(c uint8) float64 {
	v := float64(c) / 255.0
	if v <= 0.04045 {
		return v / 12.92
	}
	return math.Pow((v+0.055)/1.055, 2.4)
}

// runOverviewTagStyle returns the complete lipgloss badge style for a tag.
// The background is derived from the color scheme and the foreground is
// automatically chosen (light or dark) to ensure readable contrast.
func runOverviewTagStyle(scheme, tag string) lipgloss.Style {
	bg := runOverviewTagBackgroundColor(scheme, tag)
	fg := runOverviewTagForegroundColor(bg)
	return lipgloss.NewStyle().
		Foreground(fg).
		Background(bg).
		Padding(0, 1).
		Bold(true)
}

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
	leftSidebarStyle       = lipgloss.NewStyle().Padding(0, ContentPadding)
	leftSidebarBorderStyle = lipgloss.NewStyle().
				Border(RightBorder).
				BorderForeground(colorLayout).
				BorderTop(false).
				BorderBottom(false).
				BorderLeft(false)
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
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, ContentPadding)
	rightSidebarBorderStyle = lipgloss.NewStyle().
				Border(LeftBorder).
				BorderForeground(colorLayout).
				BorderTop(false).
				BorderBottom(false).
				BorderRight(false)
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
)

// renderHorizontalSeparator draws a full-width em-dash separator line.
// This is used between vertically stacked panes in the central column
// instead of per-pane top borders.
func renderHorizontalSeparator(width int) string {
	if width <= 0 {
		return ""
	}
	line := strings.Repeat(string(unicodeEmDash), width)
	return lipgloss.NewStyle().Foreground(colorLayout).Render(line)
}

// joinWithSeparators joins rendered sections with horizontal separator lines.
func joinWithSeparators(sections []string, width int) string {
	if len(sections) == 0 {
		return ""
	}
	sep := renderHorizontalSeparator(width)
	result := sections[0]
	for _, s := range sections[1:] {
		result = lipgloss.JoinVertical(lipgloss.Left, result, sep, s)
	}
	return result
}

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
	workspaceHeaderLines = 1

	colorSelectedRunInactiveStyle = AdaptiveColor{
		Light: lipgloss.Color("#F5D28A"),
		Dark:  lipgloss.Color("#6B5200"),
	}

	evenRunStyle             = lipgloss.NewStyle()
	oddRunStyle              = lipgloss.NewStyle().Background(getOddRunStyleColor())
	selectedRunStyle         = lipgloss.NewStyle().Background(colorSelected)
	selectedRunInactiveStyle = lipgloss.NewStyle().Background(colorSelectedRunInactiveStyle)
)

// Symon mode styles.
var (
	symonContainerStyle = lipgloss.NewStyle().
		Padding(0, ContentPadding)
)
