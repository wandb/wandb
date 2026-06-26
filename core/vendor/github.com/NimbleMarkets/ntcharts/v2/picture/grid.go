package picture

import (
	"image"
	"image/color"
	"image/draw"

	xdraw "golang.org/x/image/draw"
)

// GridImageConfig configures a GridImage compositor for logical-cell UIs.
//
// LogicalCols and LogicalRows are logical grid dimensions. TerminalColsPerCell
// and TerminalRowsPerCell are the number of terminal cells occupied by each
// logical cell; zero values default to 1. CellPixelWidth and CellPixelHeight
// are terminal-cell pixel dimensions; zero values use picture's defaults.
//
// Scaler controls how backgrounds and sprites are scaled into their target
// rectangles. It defaults to golang.org/x/image/draw.NearestNeighbor because
// games, boards, and tile maps usually need crisp pixel edges; pass
// draw.CatmullRom or another scaler when smoother image scaling is desired.
//
// When the resulting image is rendered by Model, configure the Model with:
//
//	picture.Config{Fit: picture.FitFill}
//	model.SetSize(
//		cfg.LogicalCols*cfg.TerminalColsPerCell,
//		cfg.LogicalRows*cfg.TerminalRowsPerCell,
//	)
//
// That keeps logical cell rectangles aligned with the Kitty placement.
type GridImageConfig struct {
	LogicalCols int
	LogicalRows int

	TerminalColsPerCell int
	TerminalRowsPerCell int

	CellPixelWidth  int
	CellPixelHeight int

	Scaler xdraw.Scaler

	// Background is scaled to the full grid image with Scaler. If this is a
	// photo or other smooth image, set Scaler to a non-nearest scaler such as
	// golang.org/x/image/draw.CatmullRom.
	Background image.Image

	BackgroundColor color.Color
}

// GridImage composes sprites into a bitmap whose pixel geometry maps directly
// to a terminal-cell placement. It is intended for games, boards, tile maps,
// and other coordinate-aligned UIs rendered through picture.Model.
type GridImage struct {
	img *image.RGBA

	logicalCols, logicalRows int
	terminalColsPerCell      int
	terminalRowsPerCell      int
	cellPixelW               int
	cellPixelH               int
	scaler                   xdraw.Scaler
}

// NewGridImage creates a grid-aligned image compositor. Invalid non-positive
// LogicalCols or LogicalRows produce an empty image; draw methods return false.
func NewGridImage(cfg GridImageConfig) *GridImage {
	if cfg.LogicalCols < 0 {
		cfg.LogicalCols = 0
	}
	if cfg.LogicalRows < 0 {
		cfg.LogicalRows = 0
	}
	if cfg.TerminalColsPerCell <= 0 {
		cfg.TerminalColsPerCell = 1
	}
	if cfg.TerminalRowsPerCell <= 0 {
		cfg.TerminalRowsPerCell = 1
	}
	if cfg.CellPixelWidth <= 0 {
		cfg.CellPixelWidth = defaultCellPixelW
	}
	if cfg.CellPixelHeight <= 0 {
		cfg.CellPixelHeight = defaultCellPixelH
	}
	if cfg.BackgroundColor == nil {
		cfg.BackgroundColor = color.Transparent
	}
	if cfg.Scaler == nil {
		cfg.Scaler = xdraw.NearestNeighbor
	}

	width := cfg.LogicalCols * cfg.TerminalColsPerCell * cfg.CellPixelWidth
	height := cfg.LogicalRows * cfg.TerminalRowsPerCell * cfg.CellPixelHeight

	img := image.NewRGBA(image.Rect(0, 0, width, height))
	if !img.Bounds().Empty() {
		draw.Draw(img, img.Bounds(), &image.Uniform{C: cfg.BackgroundColor}, image.Point{}, draw.Src)
		if cfg.Background != nil {
			cfg.Scaler.Scale(img, img.Bounds(), cfg.Background, cfg.Background.Bounds(), draw.Over, nil)
		}
	}

	return &GridImage{
		img:                 img,
		logicalCols:         cfg.LogicalCols,
		logicalRows:         cfg.LogicalRows,
		terminalColsPerCell: cfg.TerminalColsPerCell,
		terminalRowsPerCell: cfg.TerminalRowsPerCell,
		cellPixelW:          cfg.CellPixelWidth,
		cellPixelH:          cfg.CellPixelHeight,
		scaler:              cfg.Scaler,
	}
}

// Image returns the composed image.
func (g *GridImage) Image() image.Image {
	if g == nil {
		return image.NewRGBA(image.Rectangle{})
	}
	return g.img
}

// TerminalSize returns the terminal-cell dimensions needed to display Image
// with one logical cell occupying TerminalColsPerCell by TerminalRowsPerCell
// terminal cells.
func (g *GridImage) TerminalSize() (cols, rows int) {
	if g == nil {
		return 0, 0
	}
	return g.logicalCols * g.terminalColsPerCell, g.logicalRows * g.terminalRowsPerCell
}

// CellRect returns the pixel rectangle for a logical grid cell. Out-of-range
// cells return an empty rectangle.
func (g *GridImage) CellRect(col, row int) image.Rectangle {
	if g == nil || col < 0 || row < 0 || col >= g.logicalCols || row >= g.logicalRows {
		return image.Rectangle{}
	}
	x0 := col * g.terminalColsPerCell * g.cellPixelW
	y0 := row * g.terminalRowsPerCell * g.cellPixelH
	return image.Rect(
		x0,
		y0,
		x0+g.terminalColsPerCell*g.cellPixelW,
		y0+g.terminalRowsPerCell*g.cellPixelH,
	)
}

// DrawCell scales src into one logical cell and composites it over the current
// image. It returns false for nil sources or out-of-range cells.
func (g *GridImage) DrawCell(col, row int, src image.Image) bool {
	if g == nil || src == nil {
		return false
	}
	rect := g.CellRect(col, row)
	if rect.Empty() || src.Bounds().Empty() {
		return false
	}
	g.scaler.Scale(g.img, rect, src, src.Bounds(), draw.Over, nil)
	return true
}

// DrawOverlay scales src to the full grid image and composites it over the
// current image. Use this for whole-board decorations such as grid lines,
// highlights, or weather effects.
func (g *GridImage) DrawOverlay(src image.Image) bool {
	if g == nil || src == nil {
		return false
	}
	rect := g.img.Bounds()
	if rect.Empty() || src.Bounds().Empty() {
		return false
	}
	g.scaler.Scale(g.img, rect, src, src.Bounds(), draw.Over, nil)
	return true
}

// FillCell fills one logical cell with c. It returns false for out-of-range
// cells.
func (g *GridImage) FillCell(col, row int, c color.Color) bool {
	if g == nil {
		return false
	}
	rect := g.CellRect(col, row)
	if rect.Empty() {
		return false
	}
	draw.Draw(g.img, rect, &image.Uniform{C: c}, image.Point{}, draw.Src)
	return true
}
