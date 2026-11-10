package filestream

import (
	"unicode/utf8"
)

// jsonStringLen returns the length of s encoded by encoding/json as a JSON
// string, including the quotes.
//
// Filestream lines are themselves JSON, so their quotes are escaped when
// they are embedded in a request, making the request larger than the sum
// of its line lengths.
func jsonStringLen(s string) int {
	n := 2 // quotes

	for i := 0; i < len(s); {
		b := s[i]

		if b < utf8.RuneSelf {
			switch {
			case b == '"', b == '\\', b == '\b', b == '\f', b == '\n', b == '\r', b == '\t':
				n += 2
			case b < 0x20, b == '<', b == '>', b == '&':
				n += 6 // \u00XX
			default:
				n++
			}
			i++
			continue
		}

		r, size := utf8.DecodeRuneInString(s[i:])
		switch {
		case r == utf8.RuneError && size == 1:
			n += utf8.RuneLen(utf8.RuneError) // replaced by U+FFFD
		case r == '\u2028', r == '\u2029':
			n += 6
		default:
			n += size
		}
		i += size
	}

	return n
}
