// ntcharts - Copyright (c) 2024 Neomantra Corp.

// Package runes contains commonly used runes and functions to obtain runes.
package runes

// https://en.wikipedia.org/wiki/Box-drawing_character
// https://en.wikipedia.org/wiki/Braille_Patterns

const (
	Null = '\u0000'

	LineHorizontal         = '\u2500' // ─
	LineVertical           = '\u2502' // │
	LineVerticalHeavy      = '\u2503' // ┃
	LineDownRight          = '\u250C' // ┌
	LineDownLeft           = '\u2510' // ┐
	LineUpRight            = '\u2514' // └
	LineUpLeft             = '\u2518' // ┘
	LineVerticalRight      = '\u251C' // ├
	LineVerticalLeft       = '\u2524' // ┤
	LineHorizontalUp       = '\u2534' // ┴
	LineHorizontalDown     = '\u252C' // ┬
	LineHorizontalVertical = '\u253C' // ┼
	LineLeft               = '\u2574' // ╴
	LineUp                 = '\u2575' // ╵
	LineRight              = '\u2576' // ╶
	LineDown               = '\u2577' // ╷
	LineUpHeavy            = '\u2579' // ╹
	LineDownHeavy          = '\u257B' // ╻
	LineUpDownHeavy        = '\u257D' // ╽
	LineUpHeavyDown        = '\u257F' // ╿

	ArcDownRight = '\u256D' // ╭
	ArcDownLeft  = '\u256E' // ╮
	ArcUpLeft    = '\u256F' // ╯
	ArcUpRight   = '\u2570' // ╰

	LowerBlockOne   = '\u2581' // ▁
	LowerBlockTwo   = '\u2582' // ▂
	LowerBlockThree = '\u2583' // ▃
	LowerBlockFour  = '\u2584' // ▄
	LowerBlockFive  = '\u2585' // ▅
	LowerBlockSix   = '\u2586' // ▆
	LowerBlockSeven = '\u2587' // ▇
	FullBlock       = '\u2588' // █
	LeftBlockSeven  = '\u2589' // ▉
	LeftBlockSix    = '\u258A' // ▊
	LeftBlockFive   = '\u258B' // ▋
	LeftBlockFour   = '\u258C' // ▌
	LeftBlockThree  = '\u258D' // ▍
	LeftBlockTwo    = '\u258E' // ▎
	LeftBlockOne    = '\u258F' // ▏
)

/*
Braille dot number offsets

Unicode Braille Patterns can be computed by
adding hex values to the beginning block offset

[0][3] = [0x0001][0x0008]
[1][4]   [0x0002][0x0010]
[2][5]   [0x0004][0x0020]
[6][7]   [0x0040][0x0080]
*/

const BrailleBlockOffset = 0x2800 // beginning of Unicode Braille Patterns (empty Braille Pattern)

var brailleDotNumberOffsets = [8]int32{0x0001, 0x0002, 0x0004, 0x0008, 0x00010, 0x0020, 0x0040, 0x0080}

// PatternDots indicates whether a dot in a Braille Pattern is displayed.
type PatternDots [8]bool

// PatternDotsGrid is a 2D array where each row and column indicates whether
// a dot in a sequence of Braille Patterns runes should be displayed.
// Example:
//
//	 width = 4, height = 4 will give 2 Braille Pattern runes
//	 [0][3][0][3]
//	 [1][4][1][4]
//	 [2][5][2][5]
//	 [6][7][6][7]
//
//	setting (0,0) will set Dot 0 of first braille rune
//	setting (0,3) will set Dot 6 of first braille rune
//	setting (3,0) will set Dot 3 of second braille rune
//	setting (3,3) will set Dot 7 of second braille rune
type PatternDotsGrid struct {
	w int      // grid width
	h int      // grid height
	g [][]bool // each index indicates whether to display Braille Pattern dot
}

// NewPatternDotsGrid returns new initialized *PatternDotsGrid
func NewPatternDotsGrid(w, h int) *PatternDotsGrid {
	g := PatternDotsGrid{
		w: w,
		h: h,
	}
	g.Reset()
	return &g
}

// Reset will reset the internal grid
func (g *PatternDotsGrid) Reset() {
	g.g = make([][]bool, g.h, g.h)
	for i := range g.g {
		g.g[i] = make([]bool, g.w)
	}
}

// Set will set value in grid at given column and row
func (g *PatternDotsGrid) Set(x int, y int) {
	if (x < 0) || (x >= g.w) || (y < 0) || (y >= g.h) {
		return
	}
	g.g[y][x] = true
}

// Unset will unset value in grid at given column and row
func (g *PatternDotsGrid) Unset(x int, y int) {
	if (x < 0) || (x >= g.w) || (y < 0) || (y >= g.h) {
		return
	}
	g.g[y][x] = false
}

// BraillePatterns returns a [][]rune containing Braille Pattern
// runes based on internal grid values.
func (g *PatternDotsGrid) BraillePatterns() (p [][]rune) {
	for y := 0; y < g.h; {
		xb := []rune{}
		for x := 0; x < g.w; {
			xb = append(xb, g.getBraillePattern(x, y))
			x += 2 // each braille pattern rune has a width of 2
		}
		p = append(p, xb)
		y += 4 // each braille pattern rune has a height of 4
	}
	return
}

// getBraillePattern returns Braille Pattern rune
// starting at internal grid column and row.
func (g *PatternDotsGrid) getBraillePattern(x int, y int) (b rune) {
	if (x < 0) || (x >= g.w) || (y < 0) || (y >= g.h) {
		return
	}
	b = BrailleBlockOffset
	// set left side of braille pattern
	if g.g[y][x] {
		b |= brailleDotNumberOffsets[0]
	}
	if (y+1 < g.h) && (g.g[y+1][x]) {
		b |= brailleDotNumberOffsets[1]
	}
	if (y+2 < g.h) && (g.g[y+2][x]) {
		b |= brailleDotNumberOffsets[2]
	}
	if (y+3 < g.h) && (g.g[y+3][x]) {
		b |= brailleDotNumberOffsets[6]
	}
	// set right side of braille pattern
	if (x+1 < g.w) && (g.g[y][x+1]) {
		b |= brailleDotNumberOffsets[3]
	}
	if (y+1 < g.h) && (x+1 < g.w) && (g.g[y+1][x+1]) {
		b |= brailleDotNumberOffsets[4]
	}
	if (y+2 < g.h) && (x+1 < g.w) && (g.g[y+2][x+1]) {
		b |= brailleDotNumberOffsets[5]
	}
	if (y+3 < g.h) && (x+1 < g.w) && (g.g[y+3][x+1]) {
		b |= brailleDotNumberOffsets[7]
	}
	return
}

// IsBraillePattern returns whether a given rune is
// considered a Braile Pattern rune.
func IsBraillePattern(r rune) bool {
	if r >= 0x2800 && r <= 0x28FF {
		return true
	}
	return false
}

// BraillePatternFromPatternDots returns a Braille Pattern rune using given PatternDots.
// Each index in PatternDots corresponds to Braille dot number
// and whether the dot should be displayed.
func BraillePatternFromPatternDots(p PatternDots) (r rune) {
	r = BrailleBlockOffset
	for i, b := range p {
		if b {
			r |= brailleDotNumberOffsets[i]
		}
	}
	return
}

// SetPatternDots sets given PatternDots dots based on given rune.
func SetPatternDots(r rune, p *PatternDots) {
	if !IsBraillePattern(r) {
		return
	}
	for i, b := range brailleDotNumberOffsets {
		if (b & r) != Null {
			p[i] = true
		}
	}
	return
}

// CombineBraillePatterns returns a rune
// that is a combination of two braille pattern runes.
// Any invalid braille pattern rune combinations will return r2.
func CombineBraillePatterns(r1 rune, r2 rune) rune {
	if !IsBraillePattern(r1) || !IsBraillePattern(r2) {
		return r2
	}
	return (r1 | r2)
}

var lowerBlockElements = [9]rune{
	Null,
	LowerBlockOne,
	LowerBlockTwo,
	LowerBlockThree,
	LowerBlockFour,
	LowerBlockFive,
	LowerBlockSix,
	LowerBlockSeven,
	FullBlock,
}

// IsLowerBlockElement returns whether a given rune is
// considered a lower block or full block element.
func IsLowerBlockElement(r rune) bool {
	if r >= 0x2581 && r <= 0x2588 {
		return true
	}
	return false
}

// LowerBlockElementFromFloat64 returns either an empty rune
// or a lower Block Element rune using given float64.
// A float64 < 1.0 will return the nearest one eights lower block element
// corresponding to the float value. An empty rune will be returned if
// float64 does not round to lowest 1/8 lower block.
func LowerBlockElementFromFloat64(f float64) rune {
	if f >= 1 {
		return lowerBlockElements[8]
	} else if f <= 0 {
		return lowerBlockElements[0]
	}
	e := int(f / .125) // number of 1/8s blocks to show
	// round remaining fraction smaller than 1/8 to nearest 1/16
	if n := f - (float64(e) * .125); n >= 0.0625 {
		e++
	}
	return lowerBlockElements[e]
}

var leftBlockElements = [9]rune{
	Null,
	LeftBlockOne,
	LeftBlockTwo,
	LeftBlockThree,
	LeftBlockFour,
	LeftBlockFive,
	LeftBlockSix,
	LeftBlockSeven,
	FullBlock,
}

// IsLeftBlockElement returns whether a given rune is
// considered a left block or full block element.
func IsLeftBlockElement(r rune) bool {
	if r >= 0x2588 && r <= 0x258F {
		return true
	}
	return false
}

// LeftBlockElementFromFloat64 returns either an empty rune
// or a left Block Element rune using given float64.
// A float64 < 1.0 will return the nearest one eights left block element
// corresponding to the float value. An empty rune will be returned if
// float64 does not round to lowest 1/8 left block.
func LeftBlockElementFromFloat64(f float64) rune {
	if f >= 1 {
		return leftBlockElements[8]
	} else if f <= 0 {
		return leftBlockElements[0]
	}
	e := int(f / .125) // number of 1/8s blocks to show
	// round remaining fraction smaller than 1/8 to nearest 1/16
	if n := f - (float64(e) * .125); n >= 0.0625 {
		e++
	}
	return leftBlockElements[e]
}

// LineStyle enumerates the different style of line runes to display.
type LineStyle int

const (
	ThinLineStyle LineStyle = iota
	ArcLineStyle
)

// LineSegments indicates whether a line segment
// going up, down, left, or right is displayed.
type LineSegments struct {
	Up    bool
	Down  bool
	Left  bool
	Right bool
}

var arcLineSegmentsMap = map[LineSegments]rune{
	{false, false, false, false}: Null,
	{false, false, false, true}:  LineRight,
	{false, false, true, false}:  LineLeft,
	{false, false, true, true}:   LineHorizontal,
	{false, true, false, false}:  LineDown,
	{false, true, false, true}:   ArcDownRight,
	{false, true, true, false}:   ArcDownLeft,
	{false, true, true, true}:    LineHorizontalDown,
	{true, false, false, false}:  LineUp,
	{true, false, false, true}:   ArcUpRight,
	{true, false, true, false}:   ArcUpLeft,
	{true, false, true, true}:    LineHorizontalUp,
	{true, true, false, false}:   LineVertical,
	{true, true, false, true}:    LineVerticalRight,
	{true, true, true, false}:    LineVerticalLeft,
	{true, true, true, true}:     LineHorizontalVertical,
}

var thinLineSegmentsMap = map[LineSegments]rune{
	{false, false, false, false}: Null,
	{false, false, false, true}:  LineRight,
	{false, false, true, false}:  LineLeft,
	{false, false, true, true}:   LineHorizontal,
	{false, true, false, false}:  LineDown,
	{false, true, false, true}:   LineDownRight,
	{false, true, true, false}:   LineDownLeft,
	{false, true, true, true}:    LineHorizontalDown,
	{true, false, false, false}:  LineUp,
	{true, false, false, true}:   LineUpRight,
	{true, false, true, false}:   LineUpLeft,
	{true, false, true, true}:    LineHorizontalUp,
	{true, true, false, false}:   LineVertical,
	{true, true, false, true}:    LineVerticalRight,
	{true, true, true, false}:    LineVerticalLeft,
	{true, true, true, true}:     LineHorizontalVertical,
}

// SetLineSegments sets given LineSegments directions based on given rune.
func SetLineSegments(r rune, l *LineSegments) {
	switch r {
	case ArcDownRight, LineDownRight:
		l.Down = true
		l.Right = true
	case ArcDownLeft, LineDownLeft:
		l.Down = true
		l.Left = true
	case ArcUpLeft, LineUpLeft:
		l.Up = true
		l.Left = true
	case ArcUpRight, LineUpRight:
		l.Up = true
		l.Right = true
	case LineHorizontal:
		l.Left = true
		l.Right = true
	case LineVertical:
		l.Up = true
		l.Down = true
	case LineHorizontalUp:
		l.Up = true
		l.Left = true
		l.Right = true
	case LineHorizontalDown:
		l.Down = true
		l.Left = true
		l.Right = true
	case LineVerticalRight:
		l.Up = true
		l.Down = true
		l.Right = true
	case LineVerticalLeft:
		l.Up = true
		l.Down = true
		l.Left = true
	case LineHorizontalVertical:
		l.Up = true
		l.Down = true
		l.Left = true
		l.Right = true
	case LineUp:
		l.Up = true
	case LineDown:
		l.Down = true
	case LineLeft:
		l.Left = true
	case LineRight:
		l.Right = true
	}
	return
}

// IsLine returns whether a given rune is considered a line rune used for drawing lines.
func IsLine(r rune) bool {
	if (r >= 0x2500 && r <= 0x253C) || (r >= 0x256D && r <= 0x2570) || (r >= 0x2574 && r <= 0x2577) {
		return true
	}
	return false
}

// ArcLineFromLineSegments returns either an empty rune
// or a line rune using given LineSegments.
// LineSegments contain whether or not the returned rune
// should display arc lines going up, down, left or right.
func ArcLineFromLineSegments(l LineSegments) rune {
	return arcLineSegmentsMap[l]
}

// ThinLineFromLineSegments returns either an empty rune
// or a line rune using given LineSegments.
// LineSegments contain whether or not the returned rune
// should display thin lines going up, down, left or right.
func ThinLineFromLineSegments(l LineSegments) rune {
	return thinLineSegmentsMap[l]
}

// CombineLines returns a rune that is a combination of two line runes.
// Invalid line rune combinations or invalid LineStyle will return r2.
// The Linestyle determines the output line rune, even if
// the two input line runes are not of that style.
func CombineLines(r1 rune, r2 rune, ls LineStyle) (r rune) {
	r = r2
	r1ok := IsLine(r1)
	r2ok := IsLine(r2)
	if !r1ok && !r2ok {
		return
	}
	var l LineSegments
	if r1ok {
		SetLineSegments(r1, &l)
	}
	if r2ok {
		SetLineSegments(r2, &l)
	}
	switch ls {
	case ThinLineStyle:
		r = ThinLineFromLineSegments(l)
	case ArcLineStyle:
		r = ArcLineFromLineSegments(l)
	}
	return
}

// CandlestickSegments indicates whether a candlestick segment
// going up and down with thin or heavy lines is displayed.
type CandlestickSegments struct {
	Up        bool
	Down      bool
	UpHeavy   bool
	DownHeavy bool
}

var candlestickSegmentsMap = map[CandlestickSegments]rune{
	{false, false, false, false}: Null,
	{false, false, false, true}:  LineDownHeavy,
	{false, false, true, false}:  LineUpHeavy,
	{false, false, true, true}:   LineVerticalHeavy,
	{false, true, false, false}:  LineDown,
	{false, true, false, true}:   LineDownHeavy,
	{false, true, true, false}:   LineUpHeavyDown,
	{false, true, true, true}:    LineVerticalHeavy,
	{true, false, false, false}:  LineUp,
	{true, false, false, true}:   LineUpDownHeavy,
	{true, false, true, false}:   LineUpHeavy,
	{true, false, true, true}:    LineVerticalHeavy,
	{true, true, false, false}:   LineVertical,
	{true, true, false, true}:    LineUpDownHeavy,
	{true, true, true, false}:    LineUpHeavyDown,
	{true, true, true, true}:     LineVerticalHeavy,
}

// CandlestickFromCandlestickSegments returns either an empty rune
// or a candlestick rune using given CandlestickSegments.
// CandlestickSegments contain whether or not the returned rune
// should display thin or heavy lines going up or down.
func CandlestickFromCandlestickSegments(c CandlestickSegments) rune {
	return candlestickSegmentsMap[c]
}

// SetCandlestickSegments sets given CandlestickSegments segments based on given rune.
func SetCandlestickSegments(r rune, c *CandlestickSegments) {
	switch r {
	case LineVertical:
		c.Up = true
		c.Down = true
	case LineVerticalHeavy:
		c.UpHeavy = true
		c.DownHeavy = true
	case LineUp:
		c.Up = true
	case LineDown:
		c.Down = true
	case LineUpHeavy:
		c.UpHeavy = true
	case LineDownHeavy:
		c.DownHeavy = true
	case LineUpDownHeavy:
		c.Up = true
		c.DownHeavy = true
	case LineUpHeavyDown:
		c.UpHeavy = true
		c.Down = true
	}
	return
}

// IsCandlestick returns whether a given rune is considered
// a candlestick rune used for drawing candlesticks.
func IsCandlestick(r rune) bool {
	switch r {
	case 0x2502:
		return true
	case 0x2503:
		return true
	case 0x2575:
		return true
	case 0x2577:
		return true
	case 0x2579:
		return true
	case 0x257B:
		return true
	case 0x257D:
		return true
	case 0x257F:
		return true
	}
	return false
}

// CombineCandlesticks returns a rune that is a combination of two candlestick runes.
// Invalid candlestick rune combinations will return r2.
func CombineCandlesticks(r1 rune, r2 rune) (r rune) {
	r = r2
	r1ok := IsCandlestick(r1)
	r2ok := IsCandlestick(r2)
	if !r1ok && !r2ok {
		return
	}
	var c CandlestickSegments
	if r1ok {
		SetCandlestickSegments(r1, &c)
	}
	if r2ok {
		SetCandlestickSegments(r2, &c)
	}
	r = CandlestickFromCandlestickSegments(c)
	return
}
