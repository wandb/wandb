package terminalemulator

import "slices"

// LineSupplier returns lines for a terminal emulator to use.
type LineSupplier interface {
	// NextLine returns a new line below the previous ones.
	NextLine() Line
}

// Line is a line of text that a terminal emulator modifies.
type Line interface {
	// PutChar modifies the line's contents.
	PutChar(c rune, offset int)
}

// LineContent is a mutable string with a bound on its length.
//
// This may be used to back a Line implementation.
type LineContent struct {
	// MaxLength is the maximum number of runes in the line.
	MaxLength int

	// Content is the text on the line.
	Content []rune
}

// PutChar updates the line and returns whether it was modified.
func (l *LineContent) PutChar(c rune, offset int) bool {
	if offset >= l.MaxLength {
		return false
	}

	for offset >= len(l.Content) {
		l.Content = append(l.Content, ' ')
	}

	if l.Content[offset] == c {
		return false
	}

	l.Content[offset] = c
	return true
}

// Clone returns a deep copy of the line content.
func (l LineContent) Clone() LineContent {
	return LineContent{
		MaxLength: l.MaxLength,
		Content:   slices.Clone(l.Content),
	}
}
