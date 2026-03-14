package leet

import (
	"strings"
	"sync"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
)

type brandArtLayout int

const (
	brandArtLayoutStacked brandArtLayout = iota
	brandArtLayoutInline
)

type brandArtGradient int

const (
	brandArtGradientDiagonal brandArtGradient = iota
	brandArtGradientHorizontal
	brandArtGradientVertical
)

type brandArtCell uint8

const (
	brandArtCellEmpty brandArtCell = iota
	brandArtCellShadow
	brandArtCellGlyph
)

type brandArtTheme struct {
	Palette    []compat.AdaptiveColor
	Highlight  compat.AdaptiveColor
	RimShadow  compat.AdaptiveColor
	DropShadow compat.AdaptiveColor
	ShadowRune rune
	Gradient   brandArtGradient
}

// Change this to brandArtNeonPulse or brandArtTealForge to switch looks.
// This is intentionally static and cached.
var defaultBrandArtTheme = brandArtGoldenHour

var (
	brandArtGoldenHour = brandArtTheme{
		Palette: []compat.AdaptiveColor{
			{Light: lipgloss.Color("#A56A00"), Dark: lipgloss.Color("#FFCA4D")},
			{Light: lipgloss.Color("#B87900"), Dark: lipgloss.Color("#FFD564")},
			{Light: lipgloss.Color("#C88800"), Dark: lipgloss.Color("#FFE07A")},
			{Light: lipgloss.Color("#D59809"), Dark: lipgloss.Color("#FFE88F")},
			{Light: lipgloss.Color("#1A818B"), Dark: lipgloss.Color("#69D8E2")},
			{Light: lipgloss.Color("#1399A4"), Dark: lipgloss.Color("#8AE8EF")},
			{Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#C9F7FA")},
		},
		Highlight: compat.AdaptiveColor{
			Light: lipgloss.Color("#F4C861"),
			Dark:  lipgloss.Color("#FFF2BF"),
		},
		RimShadow: compat.AdaptiveColor{
			Light: lipgloss.Color("#7E5300"),
			Dark:  lipgloss.Color("#D7A42A"),
		},
		DropShadow: compat.AdaptiveColor{
			Light: lipgloss.Color("#D7D7D7"),
			Dark:  lipgloss.Color("#23262D"),
		},
		ShadowRune: '▓',
		Gradient:   brandArtGradientDiagonal,
	}

	brandArtNeonPulse = brandArtTheme{
		Palette: []compat.AdaptiveColor{
			{Light: lipgloss.Color("#A128D5"), Dark: lipgloss.Color("#FF94F1")},
			{Light: lipgloss.Color("#8B34DD"), Dark: lipgloss.Color("#F1A9FF")},
			{Light: lipgloss.Color("#7347E5"), Dark: lipgloss.Color("#D8BCFF")},
			{Light: lipgloss.Color("#5862EB"), Dark: lipgloss.Color("#B9CCFF")},
			{Light: lipgloss.Color("#397DEB"), Dark: lipgloss.Color("#9CDEFF")},
			{Light: lipgloss.Color("#1E98E6"), Dark: lipgloss.Color("#7BEFFF")},
			{Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#C7FBFF")},
		},
		Highlight: compat.AdaptiveColor{
			Light: lipgloss.Color("#EAFBFF"),
			Dark:  lipgloss.Color("#FFFFFF"),
		},
		RimShadow: compat.AdaptiveColor{
			Light: lipgloss.Color("#4E2B8F"),
			Dark:  lipgloss.Color("#8A5CE6"),
		},
		DropShadow: compat.AdaptiveColor{
			Light: lipgloss.Color("#D7DBE6"),
			Dark:  lipgloss.Color("#1B2030"),
		},
		ShadowRune: '▒',
		Gradient:   brandArtGradientHorizontal,
	}

	brandArtTealForge = brandArtTheme{
		Palette: []compat.AdaptiveColor{
			{Light: lipgloss.Color("#0E7480"), Dark: lipgloss.Color("#66D9E3")},
			{Light: lipgloss.Color("#118794"), Dark: lipgloss.Color("#7CE1EA")},
			{Light: lipgloss.Color("#149CA6"), Dark: lipgloss.Color("#94E8EE")},
			{Light: lipgloss.Color("#19AFAC"), Dark: lipgloss.Color("#AFEEDF")},
			{Light: lipgloss.Color("#7F9D32"), Dark: lipgloss.Color("#D7ED8F")},
			{Light: lipgloss.Color("#B88918"), Dark: lipgloss.Color("#FFD360")},
			{Light: lipgloss.Color("#D39C21"), Dark: lipgloss.Color("#FFE082")},
		},
		Highlight: compat.AdaptiveColor{
			Light: lipgloss.Color("#EAF7F8"),
			Dark:  lipgloss.Color("#FFF1CC"),
		},
		RimShadow: compat.AdaptiveColor{
			Light: lipgloss.Color("#4A666A"),
			Dark:  lipgloss.Color("#B77A18"),
		},
		DropShadow: compat.AdaptiveColor{
			Light: lipgloss.Color("#D3D7D8"),
			Dark:  lipgloss.Color("#1E2529"),
		},
		ShadowRune: '▒',
		Gradient:   brandArtGradientVertical,
	}
)

var (
	workspaceBrandArtOnce = sync.OnceValue(func() string {
		return renderBrandArt(defaultBrandArtTheme, brandArtLayoutStacked)
	})
	helpBrandArtOnce = sync.OnceValue(func() string {
		return renderBrandArt(defaultBrandArtTheme, brandArtLayoutInline)
	})
)

func renderWorkspaceBrandArt() string {
	return workspaceBrandArtOnce()
}

func renderHelpBrandArt() string {
	return helpBrandArtOnce()
}

func renderBrandArt(theme brandArtTheme, layout brandArtLayout) string {
	if len(theme.Palette) == 0 {
		theme.Palette = []compat.AdaptiveColor{{
			Light: wandbColor,
			Dark:  wandbColor,
		}}
	}
	if theme.ShadowRune == 0 {
		theme.ShadowRune = '▓'
	}

	lines := composeBrandArtLines(layout)
	cells, glyphs := buildBrandArtGrid(lines, theme.ShadowRune)
	return styleBrandArtGrid(cells, glyphs, theme)
}

func composeBrandArtLines(layout brandArtLayout) []string {
	wLines := splitArtLines(wandbArt)
	lLines := splitArtLines(leetArt)

	switch layout {
	case brandArtLayoutInline:
		return joinArtLinesHorizontal(wLines, lLines, 2)
	default:
		return joinArtLinesVertical(wLines, lLines, 1)
	}
}

func splitArtLines(raw string) []string {
	return strings.Split(strings.Trim(raw, "\n"), "\n")
}

func joinArtLinesVertical(top, bottom []string, gap int) []string {
	out := make([]string, 0, len(top)+gap+len(bottom))
	out = append(out, top...)
	for i := 0; i < gap; i++ {
		out = append(out, "")
	}
	out = append(out, bottom...)
	return out
}

func joinArtLinesHorizontal(left, right []string, gap int) []string {
	height := max(len(left), len(right))

	leftWidth := 0
	for _, line := range left {
		leftWidth = max(leftWidth, lipgloss.Width(line))
	}

	spacer := strings.Repeat(" ", gap)
	out := make([]string, 0, height)
	for i := 0; i < height; i++ {
		var l, r string
		if i < len(left) {
			l = left[i]
		}
		if i < len(right) {
			r = right[i]
		}
		out = append(out, padRight(l, leftWidth)+spacer+r)
	}
	return out
}

func padRight(s string, width int) string {
	padding := max(width-lipgloss.Width(s), 0)
	return s + strings.Repeat(" ", padding)
}

func buildBrandArtGrid(lines []string, shadowRune rune) ([][]brandArtCell, [][]rune) {
	height := len(lines) + 1
	width := 1
	for _, line := range lines {
		width = max(width, lipgloss.Width(line)+1)
	}

	cells := make([][]brandArtCell, height)
	glyphs := make([][]rune, height)
	for y := 0; y < height; y++ {
		cells[y] = make([]brandArtCell, width)
		glyphs[y] = make([]rune, width)
	}

	for y, line := range lines {
		x := 0
		for _, r := range line {
			if r != ' ' {
				cells[y][x] = brandArtCellGlyph
				glyphs[y][x] = r
			}
			x++
		}
	}

	for y := 0; y < height-1; y++ {
		for x := 0; x < width-1; x++ {
			if cells[y][x] != brandArtCellGlyph {
				continue
			}
			if cells[y+1][x+1] != brandArtCellEmpty {
				continue
			}
			cells[y+1][x+1] = brandArtCellShadow
			glyphs[y+1][x+1] = shadowRune
		}
	}

	return cells, glyphs
}

func styleBrandArtGrid(
	cells [][]brandArtCell,
	glyphs [][]rune,
	theme brandArtTheme,
) string {
	paletteStyles := make([]lipgloss.Style, len(theme.Palette))
	for i, color := range theme.Palette {
		paletteStyles[i] = lipgloss.NewStyle().
			Foreground(color).
			Bold(true)
	}

	highlightStyle := lipgloss.NewStyle().
		Foreground(theme.Highlight).
		Bold(true)

	rimShadowStyle := lipgloss.NewStyle().
		Foreground(theme.RimShadow).
		Bold(true)

	shadowStyle := lipgloss.NewStyle().
		Foreground(theme.DropShadow)

	artWidth := max(len(cells[0])-1, 1)
	artHeight := max(len(cells)-1, 1)

	var out strings.Builder
	for y := range cells {
		var line strings.Builder
		for x := range cells[y] {
			switch cells[y][x] {
			case brandArtCellGlyph:
				glyph := glyphs[y][x]
				if glyph == 0 {
					glyph = '█'
				}

				style := paletteStyles[brandArtPaletteIndex(
					theme.Gradient,
					x,
					y,
					artWidth,
					artHeight,
					len(paletteStyles),
				)]

				if isBrandArtHighlight(cells, x, y) {
					style = highlightStyle
				} else if isBrandArtRimShadow(cells, x, y) {
					style = rimShadowStyle
				}

				line.WriteString(style.Render(string(glyph)))

			case brandArtCellShadow:
				glyph := glyphs[y][x]
				if glyph == 0 {
					glyph = theme.ShadowRune
				}
				line.WriteString(shadowStyle.Render(string(glyph)))

			default:
				line.WriteByte(' ')
			}
		}

		out.WriteString(strings.TrimRight(line.String(), " "))
		if y < len(cells)-1 {
			out.WriteByte('\n')
		}
	}

	return out.String()
}

func brandArtPaletteIndex(
	gradient brandArtGradient,
	x int,
	y int,
	width int,
	height int,
	paletteSize int,
) int {
	if paletteSize <= 1 {
		return 0
	}

	var pos int
	var span int

	switch gradient {
	case brandArtGradientHorizontal:
		pos = x
		span = max(width-1, 1)
	case brandArtGradientVertical:
		pos = y
		span = max(height-1, 1)
	default:
		pos = x + y
		span = max(width+height-2, 1)
	}

	return pos * (paletteSize - 1) / span
}

func isBrandArtGlyph(cells [][]brandArtCell, x, y int) bool {
	if y < 0 || y >= len(cells) {
		return false
	}
	if x < 0 || x >= len(cells[y]) {
		return false
	}
	return cells[y][x] == brandArtCellGlyph
}

func isBrandArtHighlight(cells [][]brandArtCell, x, y int) bool {
	return !isBrandArtGlyph(cells, x-1, y) || !isBrandArtGlyph(cells, x, y-1)
}

func isBrandArtRimShadow(cells [][]brandArtCell, x, y int) bool {
	return !isBrandArtGlyph(cells, x+1, y) || !isBrandArtGlyph(cells, x, y+1)
}
