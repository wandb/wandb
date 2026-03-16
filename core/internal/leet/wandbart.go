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
	brandArtGradientSolid brandArtGradient = iota
	brandArtGradientHorizontal
	brandArtGradientDiagonal
)

type brandArtPreset string

const (
	brandArtFlatGradient brandArtPreset = "flat-gradient"
	brandArtSoftShadow   brandArtPreset = "soft-shadow"
	brandArtSplitBrand   brandArtPreset = "split-brand"
	brandArtAurora       brandArtPreset = "aurora"
)

// Change this single line to try the different looks.
const defaultBrandArtPreset = brandArtSplitBrand

type brandArtStyle struct {
	Palette     []compat.AdaptiveColor
	Gradient    brandArtGradient
	Shadow      bool
	ShadowColor compat.AdaptiveColor
}

type brandArtPresetConfig struct {
	Wandb      brandArtStyle
	Leet       brandArtStyle
	InlineGap  int
	StackedGap int
}

type brandArtCellKind uint8

const (
	brandArtCellEmpty brandArtCellKind = iota
	brandArtCellGlyph
	brandArtCellShadow
)

type brandArtCell struct {
	glyph rune
	kind  brandArtCellKind
}

type brandArtGrid struct {
	cells     [][]brandArtCell
	artWidth  int
	artHeight int
}

func ac(light, dark string) compat.AdaptiveColor {
	return compat.AdaptiveColor{
		Light: lipgloss.Color(light),
		Dark:  lipgloss.Color(dark),
	}
}

var (
	brandArtGildedLagoonPalette = []compat.AdaptiveColor{
		ac("#A56A00", "#FFCA4D"),
		ac("#C18200", "#FFD866"),
		ac("#98AA44", "#D9EA8F"),
		ac("#4BBBA4", "#A8EFDA"),
		ac("#10BFCC", "#E1F7FA"),
	}

	brandArtGoldPalette = []compat.AdaptiveColor{
		ac("#8C5900", "#F5BD31"),
		ac("#B67600", "#FFCB4D"),
		ac("#D39212", "#FFDD78"),
		ac("#E8B84C", "#FFF0B8"),
	}

	brandArtTealPalette = []compat.AdaptiveColor{
		ac("#0A7280", "#6FD9E3"),
		ac("#0E8996", "#89E4EB"),
		ac("#0FA5B1", "#B7F1F5"),
		ac("#10BFCC", "#E1F7FA"),
	}

	brandArtAuroraPalette = []compat.AdaptiveColor{
		ac("#8A35C9", "#E8A7FF"),
		ac("#6F53D8", "#D8C3FF"),
		ac("#4E75E0", "#B7D7FF"),
		ac("#10BFCC", "#D8FAFF"),
	}

	brandArtShadowColor = ac("#D2D2D2", "#20242B")
)

var brandArtPresets = map[brandArtPreset]brandArtPresetConfig{
	brandArtFlatGradient: {
		Wandb: brandArtStyle{
			Palette:  brandArtGildedLagoonPalette,
			Gradient: brandArtGradientHorizontal,
		},
		Leet: brandArtStyle{
			Palette:  brandArtGildedLagoonPalette,
			Gradient: brandArtGradientHorizontal,
		},
		InlineGap:  3,
		StackedGap: 1,
	},

	brandArtSoftShadow: {
		Wandb: brandArtStyle{
			Palette:     brandArtGildedLagoonPalette,
			Gradient:    brandArtGradientHorizontal,
			Shadow:      true,
			ShadowColor: brandArtShadowColor,
		},
		Leet: brandArtStyle{
			Palette:     brandArtGildedLagoonPalette,
			Gradient:    brandArtGradientHorizontal,
			Shadow:      true,
			ShadowColor: brandArtShadowColor,
		},
		InlineGap:  3,
		StackedGap: 1,
	},

	brandArtSplitBrand: {
		Wandb: brandArtStyle{
			Palette:     brandArtGoldPalette,
			Gradient:    brandArtGradientHorizontal,
			Shadow:      true,
			ShadowColor: brandArtShadowColor,
		},
		Leet: brandArtStyle{
			Palette:     brandArtTealPalette,
			Gradient:    brandArtGradientHorizontal,
			Shadow:      true,
			ShadowColor: brandArtShadowColor,
		},
		InlineGap:  3,
		StackedGap: 1,
	},

	brandArtAurora: {
		Wandb: brandArtStyle{
			Palette:  brandArtAuroraPalette,
			Gradient: brandArtGradientDiagonal,
		},
		Leet: brandArtStyle{
			Palette:  brandArtAuroraPalette,
			Gradient: brandArtGradientDiagonal,
		},
		InlineGap:  3,
		StackedGap: 1,
	},
}

var (
	workspaceBrandArtOnce = sync.OnceValue(func() string {
		return renderBrandArt(defaultBrandArtPreset, brandArtLayoutStacked)
	})
	helpBrandArtOnce = sync.OnceValue(func() string {
		return renderBrandArt(defaultBrandArtPreset, brandArtLayoutInline)
	})
)

func renderWorkspaceBrandArt() string {
	return workspaceBrandArtOnce()
}

func renderHelpBrandArt() string {
	return helpBrandArtOnce()
}

func renderBrandArt(preset brandArtPreset, layout brandArtLayout) string {
	cfg, ok := brandArtPresets[preset]
	if !ok {
		cfg = brandArtPresets[brandArtSplitBrand]
	}

	wandb := renderBrandArtBlock(wandbArt, cfg.Wandb)
	leet := renderBrandArtBlock(leetArt, cfg.Leet)

	switch layout {
	case brandArtLayoutInline:
		return joinRenderedBlocksHorizontal(wandb, leet, cfg.InlineGap)
	default:
		return joinRenderedBlocksVertical(wandb, leet, cfg.StackedGap)
	}
}

func renderBrandArtBlock(raw string, style brandArtStyle) string {
	if len(style.Palette) == 0 {
		style.Palette = []compat.AdaptiveColor{
			ac("#FCBC32", "#FCBC32"),
		}
	}

	grid := buildBrandArtGrid(splitArtLines(raw), style.Shadow)
	return styleBrandArtGrid(grid, style)
}

func splitArtLines(raw string) []string {
	return strings.Split(strings.Trim(raw, "\n"), "\n")
}

func buildBrandArtGrid(lines []string, withShadow bool) brandArtGrid {
	artWidth := 1
	for _, line := range lines {
		artWidth = max(artWidth, lipgloss.Width(line))
	}
	artHeight := max(len(lines), 1)

	width := artWidth
	height := artHeight
	if withShadow {
		width++
		height++
	}

	cells := make([][]brandArtCell, height)
	for y := range cells {
		cells[y] = make([]brandArtCell, width)
	}

	for y, line := range lines {
		x := 0
		for _, r := range line {
			if r != ' ' {
				cells[y][x] = brandArtCell{
					glyph: r,
					kind:  brandArtCellGlyph,
				}
			}
			x++
		}
	}

	if withShadow {
		for y := 0; y < artHeight; y++ {
			for x := 0; x < artWidth; x++ {
				if cells[y][x].kind != brandArtCellGlyph {
					continue
				}
				sx, sy := x+1, y+1
				if cells[sy][sx].kind != brandArtCellEmpty {
					continue
				}
				cells[sy][sx] = brandArtCell{
					glyph: cells[y][x].glyph,
					kind:  brandArtCellShadow,
				}
			}
		}
	}

	return brandArtGrid{
		cells:     cells,
		artWidth:  artWidth,
		artHeight: artHeight,
	}
}

func styleBrandArtGrid(grid brandArtGrid, style brandArtStyle) string {
	paletteStyles := make([]lipgloss.Style, len(style.Palette))
	for i, color := range style.Palette {
		paletteStyles[i] = lipgloss.NewStyle().
			Foreground(color).
			Bold(true)
	}

	shadowStyle := lipgloss.NewStyle().Foreground(style.ShadowColor)

	var out strings.Builder
	for y, row := range grid.cells {
		last := lastNonEmptyCell(row)
		if last >= 0 {
			for x := 0; x <= last; x++ {
				cell := row[x]
				switch cell.kind {
				case brandArtCellGlyph:
					idx := brandArtPaletteIndex(
						style.Gradient,
						x,
						y,
						grid.artWidth,
						grid.artHeight,
						len(paletteStyles),
					)
					out.WriteString(paletteStyles[idx].Render(string(cell.glyph)))
				case brandArtCellShadow:
					out.WriteString(shadowStyle.Render(string(cell.glyph)))
				default:
					out.WriteByte(' ')
				}
			}
		}
		if y < len(grid.cells)-1 {
			out.WriteByte('\n')
		}
	}

	return out.String()
}

func lastNonEmptyCell(row []brandArtCell) int {
	for i := len(row) - 1; i >= 0; i-- {
		if row[i].kind != brandArtCellEmpty {
			return i
		}
	}
	return -1
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

	switch gradient {
	case brandArtGradientSolid:
		return 0
	case brandArtGradientDiagonal:
		span := max(width+height-2, 1)
		return (x + y) * (paletteSize - 1) / span
	default:
		span := max(width-1, 1)
		return x * (paletteSize - 1) / span
	}
}

func joinRenderedBlocksVertical(top, bottom string, gap int) string {
	parts := []string{top}
	for i := 0; i < gap; i++ {
		parts = append(parts, "")
	}
	parts = append(parts, bottom)
	return lipgloss.JoinVertical(lipgloss.Center, parts...)
}

func joinRenderedBlocksHorizontal(left, right string, gap int) string {
	leftLines := strings.Split(strings.TrimRight(left, "\n"), "\n")
	rightLines := strings.Split(strings.TrimRight(right, "\n"), "\n")
	height := max(len(leftLines), len(rightLines))

	leftWidth := 0
	for _, line := range leftLines {
		leftWidth = max(leftWidth, lipgloss.Width(line))
	}

	padLeft := lipgloss.NewStyle().Width(leftWidth)
	spacer := strings.Repeat(" ", gap)

	out := make([]string, 0, height)
	for i := 0; i < height; i++ {
		var l, r string
		if i < len(leftLines) {
			l = leftLines[i]
		}
		if i < len(rightLines) {
			r = rightLines[i]
		}
		out = append(out, padLeft.Render(l)+spacer+r)
	}

	return strings.Join(out, "\n")
}
