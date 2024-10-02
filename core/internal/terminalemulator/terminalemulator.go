// Package terminalemulator implements a virtual terminal that supports common
// ANSI / xterm escape sequences.
//
// For a list of various sequences and their definitions, see
// https://xfree86.org/4.8.0/ctlseqs.html. This isn't a full terminal emulator,
// so most sequences aren't supported, but support can be added for any
// sequence as necessary for W&B. Primarily, we need to support cursor
// operations which are used by `tqdm`-style progress bars.
//
// For a great history and overview of terminals, see
// https://gpanders.com/blog/state-of-the-terminal/
package terminalemulator

import "slices"

// Terminal is a text buffer that processes escape sequences.
//
// This class is not safe for concurrent use and must be externally
// synchronized.
type Terminal struct {
	// lineSupplier creates lines for the terminal to use.
	lineSupplier LineSupplier

	// height is the number of lines in the terminal's view area.
	height int

	// view is the list of lines in the terminal.
	view []Line

	// viewY is the cursor's Y position in the view.
	//
	// It is an index into the view slice. 0 is the top line in the view.
	viewY int

	// viewX is the cursor's X position in the view.
	viewX int

	// escapeSequence is the accumulated escape sequence.
	//
	// This is the empty string if we're not parsing an escape sequence.
	escapeSequence string
}

// NewTerminal returns an empty terminal.
func NewTerminal(
	lineSupplier LineSupplier,
	height int,
) *Terminal {
	return &Terminal{
		lineSupplier: lineSupplier,
		height:       height,
		view:         make([]Line, 0),
	}
}

// Write sends input to the terminal.
func (t *Terminal) Write(input string) {
	for _, char := range input {
		switch {
		case len(t.escapeSequence) == 0:
			switch char {
			default:
				t.putChar(char)
			case '\r':
				t.carriageReturn()
			case '\n':
				t.lineFeed()
			case '\x1b':
				t.escapeSequence = string(char)
			}

		case t.escapeSequence == "\x1b":
			switch char {
			case '[':
				t.escapeSequence = "\x1b["
			default:
				t.printEscapeSequence()
				t.putChar(char)
			}

		case t.escapeSequence == "\x1b[":
			switch char {
			case 'A':
				t.cursorUp()
				t.escapeSequence = ""
			case 'B':
				t.cursorDown()
				t.escapeSequence = ""
			default:
				t.printEscapeSequence()
				t.putChar(char)
			}
		}
	}
}

// printEscapeSequence prints out and resets the accumulated escape sequence.
//
// This is used for unknown escape sequences.
func (t *Terminal) printEscapeSequence() {
	for _, char := range t.escapeSequence {
		t.putChar(char)
	}

	t.escapeSequence = ""
}

// putChar writes a character to the terminal and shifts the cursor.
func (t *Terminal) putChar(char rune) {
	// Create empty lines until we reach the current line.
	for t.viewY >= len(t.view) {
		t.view = append(t.view, t.lineSupplier.NextLine())
	}

	t.view[t.viewY].PutChar(char, t.viewX)
	t.viewX += 1
}

// carriageReturn moves the cursor to the start of the line.
func (t *Terminal) carriageReturn() {
	t.viewX = 0
}

// lineFeed moves the cursor down one line.
//
// NOTE: Also does an implicit '\r'. This is the common behavior, but there's
// no standard that mandates it, and in fact on some systems it is
// configurable. For instance, see the "LF" section of
// https://vt100.net/annarbor/aaa-ug/appendixa.html
func (t *Terminal) lineFeed() {
	t.viewX = 0
	t.viewY += 1

	if t.viewY >= t.height {
		t.scrollDown()
	}
}

// scrollDown shifts the terminal by one line.
func (t *Terminal) scrollDown() {
	if len(t.view) > 0 {
		t.view = slices.Delete(t.view, 0, 1)
	}

	t.viewY -= 1
}

// cursorUp shifts the cursor up by one line.
func (t *Terminal) cursorUp() {
	if t.viewY > 0 {
		t.viewY -= 1
	}
}

// cursorDown shifts the cursor down by one line.
func (t *Terminal) cursorDown() {
	t.viewY += 1

	if t.viewY >= t.height {
		t.scrollDown()
	}
}
