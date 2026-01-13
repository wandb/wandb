// ntcharts - Copyright (c) 2024 Neomantra Corp.

// Package canvas implements an abstract 2D area used to plot
// arbitary runes that can be displayed using the bubbletea framework.
package canvas

// File contains a Model using the bubbletea framework
// representing the state of the canvas,
// types and functions of the coordinates system used by the canvas
// and types and functions of the contents of the canvas.

import (
	"image"
	"math"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	zone "github.com/lrstanley/bubblezone"
)

// Point is alias for image.Point
type Point = image.Point

// Float64Point represents a point in a coordinate system
// with floating point precision.
type Float64Point struct {
	X float64
	Y float64
}

// NewFloat64PointFromPoint returns a new Float64Point from a given Point.
func NewFloat64PointFromPoint(p Point) Float64Point {
	return Float64Point{X: float64(p.X), Y: float64(p.Y)}
}

// Mul returns a Float64Point with both X and Y values
// multiplied by the X and Y values of the given Float64Point.
func (p Float64Point) Mul(f Float64Point) Float64Point {
	return Float64Point{p.X * f.X, p.Y * f.Y}
}

// Add returns a Float64Point with both X and Y values
// added to the X and Y values of the given Float64Point.
func (p Float64Point) Add(f Float64Point) Float64Point {
	return Float64Point{p.X + f.X, p.Y + f.Y}
}

// Sub returns a Float64Point with both X and Y values
// subtracted by the X and Y values of the given Float64Point.
func (p Float64Point) Sub(f Float64Point) Float64Point {
	return Float64Point{p.X - f.X, p.Y - f.Y}
}

// NewPointFromFloat64Point returns a new Point from a given Float64Point.
func NewPointFromFloat64Point(f Float64Point) Point {
	return Point{int(math.Round(f.X)), int(math.Round(f.Y))}
}

// CanvasYCoordinates returns a sequence of Y coordinates in the
// canvas coordinates system (X,Y is top left) from a given sequence of Y coordinates
// in the Cartesian coordinates system (X,Y is bottom left)
// by passing the graph X axis in the canvas coordinates system.
func CanvasYCoordinates(xAxis int, seq []int) (r []int) {
	r = make([]int, 0, len(seq))
	for _, v := range seq {
		r = append(r, CanvasYCoordinate(xAxis, v))
	}
	return
}

// CanvasYCoordinate returns a Y coordinates in the
// canvas coordinates system (X,Y is top left) from a Y coordinate
// in the Cartesian coordinates system (X,Y is bottom left)
// by passing the graph X axis in the canvas coordinates system.
func CanvasYCoordinate(xAxis int, y int) (r int) {
	return xAxis - y
}

// CanvasPoints returns a sequence of Points in the
// canvas coordinates system (X,Y is top left) from a given sequence of Points
// in the Cartesian coordinates system (X,Y is bottom left)
// by passing the graph origin in the canvas coordinates system.
func CanvasPoints(origin Point, seq []Point) (r []Point) {
	r = make([]Point, 0, len(seq))
	for _, v := range seq {
		r = append(r, CanvasPoint(origin, v))
	}
	return
}

// CanvasPoint returns a Point in the
// canvas coordinates system (X,Y is top left) from a given Point
// in the Cartesian coordinates system (X,Y is bottom left)
// by passing the graph origin in the canvas coordinates system.
func CanvasPoint(origin Point, p Point) (r Point) {
	return Point{origin.X + p.X, origin.Y - p.Y}
}

// CanvasPointFromFloat64Point returns a Point
// in the canvas coordinates systems (X,Y is top left)
// from a canvas Float64Point in the
// Cartesian coordinates system (X,Y is bottom left)
// by passing the graph origin in the canvas coordinates system.
func CanvasPointFromFloat64Point(origin Point, f Float64Point) Point {
	// round coordinates to nearest integer and
	// convert Cartesian coordinates to canvas coordinates
	return CanvasPoint(origin, NewPointFromFloat64Point(f))
}

// CanvasFloat64Point returns a Float64Point in the
// canvas coordinates system (X,Y is top left) from a given Float64Point
// in the Cartesian coordinates system (X,Y is bottom left)
// by passing the graph origin in the canvas coordinates system.
func CanvasFloat64Point(origin Point, p Float64Point) (r Float64Point) {
	return Float64Point{float64(origin.X) + p.X, float64(origin.Y) - p.Y}
}

var defaultStyle = lipgloss.NewStyle()

// Cell contains a rune and lipgloss Style for rendering
type Cell struct {
	Rune  rune
	Style lipgloss.Style
}

// NewCell returns Cell with given rune and default lipgloss Style.
func NewCell(r rune) Cell {
	return Cell{Rune: r, Style: defaultStyle}
}

// NewCellWithStyle returns Cell with given rune and lipgloss Style.
func NewCellWithStyle(r rune, s lipgloss.Style) Cell {
	return Cell{Rune: r, Style: s}
}

// CellLine is a slice of Cells
type CellLine []Cell

// Model contains state of a canvas
type Model struct {
	Style         lipgloss.Style // default style applied to all cells
	KeyMap        KeyMap         // KeyMap used for keyboard msgs during Update()
	UpdateHandler UpdateHandler  // callback invoked during Update()

	// overall canvas size
	area    image.Rectangle // 0,0 is top left of canvas
	content []CellLine
	focus   bool

	// simulates a viewport width and height
	// to display contents of the canvas
	ViewWidth  int
	ViewHeight int

	// internal coordinates tracking viewport cursor
	// the contents will be displayed from top to bottom
	// and left to right of the cursor
	// 0,0 is top left of canvas
	cursor Point

	// bubblezone Manager used to handler mouse events during Update()
	zoneManager *zone.Manager
	zoneID      string
}

// New returns a canvas Model initialized with given width, height
// and various options.
func New(w, h int, opts ...Option) Model {
	m := Model{
		Style:         defaultStyle,
		KeyMap:        DefaultKeyMap(),
		UpdateHandler: DefaultUpdateHandler(),
		area:          image.Rect(0, 0, w, h),
		content:       make([]CellLine, h),
		ViewWidth:     w,
		ViewHeight:    h,
	}
	for i := range m.content {
		m.content[i] = make(CellLine, w)
	}
	for _, opt := range opts {
		opt(&m)
	}
	return m
}

// Width returns canvas width.
func (m *Model) Width() int {
	return m.area.Dx()
}

// Height returns canvas height.
func (m *Model) Height() int {
	return m.area.Dy()
}

// Cursor returns Point containg (X,Y) coordinates pointing to top left of viewport.
func (m *Model) Cursor() Point {
	return m.cursor
}

// SetCursor sets (X,Y) coordinates of cursor pointing to top left of viewport.
// Coordinates will be bounded by canvas if x, y coordinates are out of bound.
func (m *Model) SetCursor(p Point) {
	m.cursor.X = p.X
	m.cursor.Y = p.Y
	if m.cursor.X < 0 {
		m.cursor.X = 0
	} else if m.cursor.X >= m.area.Dx() {
		m.cursor.X = m.area.Dx() - 1
	}
	if m.cursor.Y < 0 {
		m.cursor.Y = 0
	} else if m.cursor.Y >= m.area.Dy() {
		m.cursor.Y = m.area.Dy() - 1
	}
}

// Resize will resize canvas to new height and width, and resets cursor.
// Will truncate existing content if canvas size shrinks.
// Does not change viewport for displaying contents.
func (m *Model) Resize(w, h int) {
	// create new lines and copy over previous contents
	newLines := make([]CellLine, h)
	for i := range newLines {
		newLines[i] = make(CellLine, w)
		// copy over previous line
		if i < m.area.Dy() {
			for j, r := range m.content[i] {
				if j >= w {
					break
				}
				newLines[i][j] = r
			}
		}
	}
	m.area = image.Rect(0, 0, w, h)
	m.cursor.X = 0
	m.cursor.Y = 0
	m.content = newLines
}

// Clear will reset canvas contents.
func (m *Model) Clear() {
	dx := m.area.Dx()
	for i := range m.content {
		m.content[i] = make(CellLine, dx)
	}
}

// SetLines copies []string into canvas as contents.
// Each string element represents a line in the canvas starting from top to bottom.
// Truncates contents if contents are greater than canvas height and width.
func (m *Model) SetLines(lines []string) bool {
	return m.SetLinesWithStyle(lines, m.Style)
}

// SetLinesWithStyle copies []string into canvas as contents with style applied to all Cells.
// Each string element represents a line in the canvas starting from top to bottom.
// Truncates contents if contents are greater than canvas height and width.
func (m *Model) SetLinesWithStyle(lines []string, s lipgloss.Style) bool {
	for y, l := range lines {
		if y >= m.area.Dy() {
			break
		}
		if !m.SetStringWithStyle(Point{0, y}, l, s) {
			return false // should not happen
		}
	}
	return true
}

// SetString copies string as rune values into canvas CellLine starting at coordinates (X, Y).
// Truncates values execeeding the canvas width.
func (m *Model) SetString(p Point, l string) bool {
	return m.SetStringWithStyle(p, l, m.Style)
}

// SetStringWithStyle copies string as rune values into canvas CellLine starting at coordinates (X, Y).
// Style will be applied to all Cells.
// Truncates values execeeding the canvas width.
func (m *Model) SetStringWithStyle(p Point, l string, s lipgloss.Style) bool {
	return m.SetRunesWithStyle(p, []rune(l), s)
}

// SetRunes copies rune values into canvas CellLine starting at coordinates (X, Y).
// Style will be applied to all Cells.
// Truncates values execeeding the canvas width.
func (m *Model) SetRunes(p Point, l []rune) bool {
	return m.SetRunesWithStyle(p, l, m.Style)
}

// SetRunesWithStyle copies rune values into canvas CellLine starting at coordinates (X, Y).
// Style will be applied to all Cells.
// Truncates values execeeding the canvas width.
func (m *Model) SetRunesWithStyle(p Point, l []rune, s lipgloss.Style) bool {
	if !m.insideYBounds(p.Y) {
		return false
	}
	xIdx := p.X
	for _, r := range l {
		if m.insideXBounds(xIdx) {
			m.content[p.Y][xIdx] = NewCellWithStyle(r, s)
		}
		xIdx += 1
	}
	return true
}

// SetCell sets a Cell using (X,Y) coordinates of canvas.
func (m *Model) SetCell(p Point, c Cell) bool {
	if !p.In(m.area) {
		return false
	}
	m.content[p.Y][p.X] = c
	return true
}

// SetCellStyle sets Cell.Style using (X,Y) coordinates of canvas.
func (m *Model) SetCellStyle(p Point, s lipgloss.Style) bool {
	if !p.In(m.area) {
		return false
	}
	m.content[p.Y][p.X].Style = s
	return true
}

// GetCellStyle gets the Style at (X,Y) coordinates of canvas.
// Returns nil if no style is found.
func (m *Model) GetCellStyle(p Point) *lipgloss.Style {
	if !p.In(m.area) {
		return nil
	}
	copyStyle := m.content[p.Y][p.X].Style
	return &copyStyle
}

// SetRune sets Cell.Rune using (X,Y) coordinates of canvas using the default style.
func (m *Model) SetRune(p Point, r rune) bool {
	if !p.In(m.area) {
		return false
	}
	m.content[p.Y][p.X] = NewCellWithStyle(r, m.Style)
	return true
}

// SetRuneWithStyle sets Cell.Rune using (X,Y) coordinates of canvas using the given style.
func (m *Model) SetRuneWithStyle(p Point, r rune, style lipgloss.Style) bool {
	if !p.In(m.area) {
		return false
	}
	m.content[p.Y][p.X] = NewCellWithStyle(r, style)
	return true
}

// Cell returns Cell located at (X,Y) coordinates of canvas.
// Returns default Cell if coorindates are out of bounds.
func (m *Model) Cell(p Point) (c Cell) {
	if !p.In(m.area) {
		return
	}
	c = m.content[p.Y][p.X]
	return
}

// Fill sets all content in canvas to Cell.
func (m *Model) Fill(c Cell) {
	for i := range m.content {
		for j := range m.content[i] {
			m.content[i][j] = c
		}
	}
}

// FillLine sets all Cells in a CellLine y away
// from origin to given Cell.
func (m *Model) FillLine(y int, c Cell) {
	if !m.insideYBounds(y) {
		return
	}
	for j := range m.content[y] {
		m.content[y][j] = c
	}
}

// SetStyle applies a lipgloss.Style to all Cells to change
// visual elements of each rune in the canvas.
func (m *Model) SetStyle(s lipgloss.Style) {
	for i := range m.content {
		for j := range m.content[i] {
			m.content[i][j].Style = s
		}
	}
}

// SetZoneManager enables mouse functionality
// by setting a bubblezone.Manager to the canvas.
// The bubblezone.Manager can check bubbletea mouse event Msgs
// passed to the UpdateHandler handler during an Update().
// The root bubbletea model must wrap the View() string with
// bubblezone.Manager.Scan() to enable mouse functionality.
// To disable mouse functionality after enabling, call SetZoneManager on nil.
func (m *Model) SetZoneManager(zm *zone.Manager) {
	m.zoneManager = zm
	if (zm != nil) && (m.zoneID == "") {
		m.zoneID = zm.NewPrefix()
	}
}

// ZoneManager will return canvas zone Manager.
func (m *Model) ZoneManager() *zone.Manager {
	return m.zoneManager
}

// ZoneID will return canvas zone ID used by zone Manager.
func (m *Model) ZoneID() string {
	return m.zoneID
}

// ShiftUp moves all Cells up once.
// Last CellLine will be set to a new CellLine.
func (m *Model) ShiftUp() {
	c := m.content
	copy(c, c[1:])
	c[len(c)-1] = make(CellLine, m.area.Dx())
}

// ShiftDown moves all Cells down once.
// First CellLine will be set to a new CellLine.
func (m *Model) ShiftDown() {
	c := m.content
	copy(c[1:], c)
	c[0] = make(CellLine, m.area.Dx())
}

// ShiftLeft moves all Cells left once.
// Last cell in each CellLine will be a new default Cell.
func (m *Model) ShiftLeft() {
	for i := range m.content {
		cl := m.content[i]
		copy(cl, cl[1:])
		cl[len(cl)-1] = Cell{}
	}
}

// ShiftRight moves all Cells right once.
// First cell in each CellLine will be a new default Cell.
func (m *Model) ShiftRight() {
	for i := range m.content {
		cl := m.content[i]
		copy(cl[1:], cl)
		cl[0] = Cell{}
	}
}

// Focused returns whether canvas is being focused.
func (m *Model) Focused() bool {
	return m.focus
}

// Focus enables Update events processing.
func (m *Model) Focus() {
	m.focus = true
}

// Blur disables Update events processing.
func (m *Model) Blur() {
	m.focus = false
}

// Init initializes the canvas.
func (m Model) Init() tea.Cmd {
	return nil
}

// Update processes bubbletea Msg to by invoking
// UpdateHandler callback if canvas is focused.
func (m Model) Update(msg tea.Msg) (Model, tea.Cmd) {
	if !m.focus {
		return m, nil
	}
	m.UpdateHandler(&m, msg)
	return m, nil
}

// View returns a string used by the bubbletea framework to display the canvas.
func (m Model) View() (r string) {
	var sb strings.Builder
	sb.Grow(m.area.Dx() * m.area.Dy())

	endY := m.cursor.Y + m.ViewHeight - 1
	endX := m.cursor.X + m.ViewWidth - 1
	for i := m.cursor.Y; i <= endY; i++ {
		if i >= m.area.Dy() {
			break
		}
		for j := m.cursor.X; j <= endX; j++ {
			if j >= m.area.Dx() {
				break
			}
			cell := m.content[i][j]
			if cell.Rune == 0 {
				sb.WriteString(cell.Style.Render(" "))
			} else {
				sb.WriteString(cell.Style.Render(string(cell.Rune)))
			}
		}
		if i != endY {
			sb.WriteRune('\n')
		}
	}
	r = sb.String()
	if m.zoneManager != nil {
		r = m.zoneManager.Mark(m.zoneID, r)
	}
	return
}

// insideXBounds returns whether X coordinate is within canvas bounds.
func (m *Model) insideXBounds(x int) bool {
	if (x < 0) || (x >= m.area.Dx()) {
		return false
	}
	return true
}

// insideYBounds returns whether Y coordinate is within canvas bounds.
func (m *Model) insideYBounds(y int) bool {
	if (y < 0) || (y >= m.area.Dy()) {
		return false
	}
	return true
}
