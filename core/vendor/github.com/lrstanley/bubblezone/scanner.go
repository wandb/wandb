// Copyright (c) Liam Stanley <liam@liam.sh>. All rights reserved. Use of
// this source code is governed by the MIT license that can be found in
// the LICENSE file.

package zone

import (
	"unicode/utf8"

	"github.com/muesli/ansi"
)

const (
	eof = 1
)

type stateFn func(*scanner) stateFn

type scanner struct {
	manager   *Manager
	enabled   bool
	iteration int

	input string // Source input.
	pos   int    // Current position in the input.
	start int    // Start position of the current marker.
	width int    // Width of the current rune.

	// Used for width and height tracking.
	newlines    int
	lastNewline int

	// tracked is the temporary location for starting markers.
	tracked map[string]*ZoneInfo
}

func newScanner(m *Manager, input string, iteration int) *scanner {
	return &scanner{
		manager:   m,
		enabled:   m.Enabled(),
		iteration: iteration,
		input:     input,
		tracked:   make(map[string]*ZoneInfo),
	}
}

// run initializes the scanner and starts the state machine.
func (s *scanner) run() {
	for state := scanMain; state != nil; {
		state = state(s)
	}
}

// emit adds the current marker to the tracked map. If two markers are received,
// it is sent back to the manager.
func (s *scanner) emit() {
	if !s.enabled {
		// If the manager is disabled, we don't need to track anything, just strip
		// the markers from the resulting output.
		s.input = s.input[:s.start] + s.input[s.pos:]
		s.pos = s.start
		return
	}

	rid := s.input[s.start:s.pos]
	if item, ok := s.tracked[rid]; ok {
		// The end should be - 1, because it's the end of the encapsulation of the
		// zone, and isn't actually taking up another space.
		item.EndX = ansi.PrintableRuneWidth(s.input[s.lastNewline:s.start]) - 1
		item.EndY = s.newlines

		s.manager.setChan <- item

		delete(s.tracked, rid)
	} else {
		s.tracked[rid] = &ZoneInfo{
			id:        rid,
			iteration: s.iteration,
			StartX:    ansi.PrintableRuneWidth(s.input[s.lastNewline:s.start]),
			StartY:    s.newlines,
		}
	}

	s.input = s.input[:s.start] + s.input[s.pos:]
	s.pos = s.start
}

// next returns the next rune in the input, incrementing the position.
func (s *scanner) next() (r rune) {
	if s.pos >= len(s.input) {
		s.width = 0
		return eof
	}

	r, s.width = utf8.DecodeRuneInString(s.input[s.pos:])
	s.pos += s.width

	return r
}

// backup steps back one rune. Can only be called once per call of next.
func (s *scanner) backup() {
	s.pos -= s.width
}

// peek steps forward one rune, reads, and backs up again.
func (s *scanner) peek() rune {
	r := s.next()
	s.backup()
	return r
}

// scanMain is the entrypoint into the state machine.
func scanMain(s *scanner) stateFn {
	switch r := s.next(); {
	case r == eof:
		return nil
	case r == '\n':
		s.newlines++
		s.lastNewline = s.pos
		return scanMain
	case r == identStart:
		s.start = s.pos - 1
		return scanID
	default:
		return scanMain
	}
}

// scanID scans forward, matching a marker, otherwise cancelling and returning
// to scanMain if a valid marker isn't found.
func scanID(s *scanner) stateFn {
	if s.peek() != identBracket {
		return scanMain
	}
	s.next()

	if !isNumber(s.peek()) {
		return scanMain
	}

	for isNumber(s.peek()) {
		s.next()
	}

	if s.peek() != identEnd {
		return scanMain
	}
	s.next()

	s.emit()
	return scanMain
}

func isNumber(r rune) bool {
	if r < '0' || r > '9' {
		return false
	}
	return true
}
