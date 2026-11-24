package viewport

import (
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

// parseMatches converts the given matches into highlight ranges.
//
// Assumptions:
// - matches are measured in bytes, e.g. what [regex.FindAllStringIndex] would return
// - matches were made against the given content
// - matches are in order
// - matches do not overlap
// - content is line terminated with \n only
//
// We'll then convert the ranges into [highlightInfo]s, which hold the starting
// line and the grapheme positions.
func parseMatches(
	content string,
	matches [][]int,
) []highlightInfo {
	if len(matches) == 0 {
		return nil
	}

	line := 0
	graphemePos := 0
	previousLinesOffset := 0
	bytePos := 0

	highlights := make([]highlightInfo, 0, len(matches))
	rem := content
	var state byte

	next := func() (seq string, width int, n int, ok bool) {
		if len(rem) == 0 {
			return "", 0, 0, false
		}
		var newState byte
		seq, width, n, newState = ansi.DecodeSequence(rem, state, nil)
		state = newState
		rem = rem[n:]
		return seq, width, n, true
	}

	for _, match := range matches {
		byteStart, byteEnd := match[0], match[1]

		// hilight for this match:
		hi := highlightInfo{
			lines: map[int][2]int{},
		}

		// find the beginning of this byte range, setup current line and
		// grapheme position.
		for byteStart > bytePos {
			seq, width, n, ok := next()
			if !ok {
				break
			}
			if seq == "\n" {
				previousLinesOffset = graphemePos + 1
				line++
				graphemePos++
			} else if width > 0 {
				graphemePos += max(1, width)
			}
			bytePos += n
		}

		hi.lineStart = line
		hi.lineEnd = line

		graphemeStart := graphemePos

		// loop until we find the end
		for byteEnd > bytePos {
			seq, width, n, ok := next()
			if !ok {
				break
			}

			// if it ends with a new line, add the range, increase line, and continue
			if seq == "\n" {
				colstart := max(0, graphemeStart-previousLinesOffset)
				colend := max(graphemePos-previousLinesOffset+1, colstart) // +1 its \n itself

				if colend > colstart {
					hi.lines[line] = [2]int{colstart, colend}
					hi.lineEnd = line
				}

				previousLinesOffset = graphemePos + 1
				line++
				graphemePos++
			} else if width > 0 {
				graphemePos += max(1, width)
			}
			bytePos += n
		}

		// we found it!, add highlight and continue
		if bytePos == byteEnd {
			colstart := max(0, graphemeStart-previousLinesOffset)
			colend := max(graphemePos-previousLinesOffset, colstart)

			if colend > colstart {
				hi.lines[line] = [2]int{colstart, colend}
				hi.lineEnd = line
			}
		}

		highlights = append(highlights, hi)
	}

	return highlights
}

type highlightInfo struct {
	// in which line this highlight starts and ends
	lineStart, lineEnd int

	// the grapheme highlight ranges for each of these lines
	lines map[int][2]int
}

// coords returns the line x column of this highlight.
func (hi highlightInfo) coords() (int, int, int) {
	for i := hi.lineStart; i <= hi.lineEnd; i++ {
		hl, ok := hi.lines[i]
		if !ok {
			continue
		}
		return i, hl[0], hl[1]
	}
	return hi.lineStart, 0, 0
}

func makeHighlightRanges(
	highlights []highlightInfo,
	line int,
	style lipgloss.Style,
) []lipgloss.Range {
	result := []lipgloss.Range{}
	for _, hi := range highlights {
		lihi, ok := hi.lines[line]
		if !ok {
			continue
		}
		if lihi == [2]int{} {
			continue
		}
		result = append(result, lipgloss.NewRange(lihi[0], lihi[1], style))
	}
	return result
}
