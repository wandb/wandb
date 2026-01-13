package displaywidth

import (
	"unicode/utf8"

	"github.com/clipperhouse/stringish"
	"github.com/clipperhouse/uax29/v2/graphemes"
)

// Options allows you to specify the treatment of ambiguous East Asian
// characters. When EastAsianWidth is false (default), ambiguous East Asian
// characters are treated as width 1. When EastAsianWidth is true, ambiguous
// East Asian characters are treated as width 2.
type Options struct {
	EastAsianWidth bool
}

// DefaultOptions is the default options for the display width
// calculation, which is EastAsianWidth: false.
var DefaultOptions = Options{EastAsianWidth: false}

// String calculates the display width of a string,
// by iterating over grapheme clusters in the string
// and summing their widths.
func String(s string) int {
	return DefaultOptions.String(s)
}

// String calculates the display width of a string, for the given options, by
// iterating over grapheme clusters in the string and summing their widths.
func (options Options) String(s string) int {
	// Optimization: no need to parse grapheme
	switch len(s) {
	case 0:
		return 0
	case 1:
		return asciiWidth(s[0])
	}

	width := 0
	g := graphemes.FromString(s)
	for g.Next() {
		width += graphemeWidth(g.Value(), options)
	}
	return width
}

// Bytes calculates the display width of a []byte,
// by iterating over grapheme clusters in the byte slice
// and summing their widths.
func Bytes(s []byte) int {
	return DefaultOptions.Bytes(s)
}

// Bytes calculates the display width of a []byte, for the given options, by
// iterating over grapheme clusters in the slice and summing their widths.
func (options Options) Bytes(s []byte) int {
	// Optimization: no need to parse grapheme
	switch len(s) {
	case 0:
		return 0
	case 1:
		return asciiWidth(s[0])
	}

	width := 0
	g := graphemes.FromBytes(s)
	for g.Next() {
		width += graphemeWidth(g.Value(), options)
	}
	return width
}

// Rune calculates the display width of a rune. You
// should almost certainly use [String] or [Bytes] for
// most purposes.
//
// The smallest unit of display width is a grapheme
// cluster, not a rune. Iterating over runes to measure
// width is incorrect in many cases.
func Rune(r rune) int {
	return DefaultOptions.Rune(r)
}

// Rune calculates the display width of a rune, for the given options.
//
// You should almost certainly use [String] or [Bytes] for most purposes.
//
// The smallest unit of display width is a grapheme cluster, not a rune.
// Iterating over runes to measure width is incorrect in many cases.
func (options Options) Rune(r rune) int {
	if r < utf8.RuneSelf {
		return asciiWidth(byte(r))
	}

	// Surrogates (U+D800-U+DFFF) are invalid UTF-8.
	if r >= 0xD800 && r <= 0xDFFF {
		return 0
	}

	var buf [4]byte
	n := utf8.EncodeRune(buf[:], r)

	// Skip the grapheme iterator
	return graphemeWidth(buf[:n], options)
}

const _Default property = 0

// graphemeWidth returns the display width of a grapheme cluster.
// The passed string must be a single grapheme cluster.
func graphemeWidth[T stringish.Interface](s T, options Options) int {
	// Optimization: no need to look up properties
	switch len(s) {
	case 0:
		return 0
	case 1:
		return asciiWidth(s[0])
	}

	p, sz := lookup(s)
	prop := property(p)

	// Variation Selector 16 (VS16) requests emoji presentation
	if sz > 0 && len(s) >= sz+3 {
		vs := s[sz : sz+3]
		if isVS16(vs) {
			prop = _Emoji
		}
		// VS15 (0x8E) requests text presentation but does not affect width,
		// in my reading of Unicode TR51. Falls through to return the base
		// character's property.
	}

	/*
		Note: we previously had some regional indicator handling here,
		intending to treat single RI's as width 1 and pairs as width 2.
		We think that's what the Unicode #11 indicates?

		Then we looked at what actual terminals do, and they seem to treat
		single and paired RI's as width 2, regardless. See terminal-test/.
		Looks like VS Code does the same FWIW.
	*/

	if options.EastAsianWidth && prop == _East_Asian_Ambiguous {
		prop = _East_Asian_Wide
	}

	if prop > upperBound {
		prop = _Default
	}

	return propertyWidths[prop]
}

func asciiWidth(b byte) int {
	if b <= 0x1F || b == 0x7F {
		return 0
	}
	return 1
}

// isVS16 checks if the slice matches VS16 (U+FE0F) UTF-8 encoding
// (EF B8 8F). It assumes len(s) >= 3.
func isVS16[T stringish.Interface](s T) bool {
	return s[0] == 0xEF && s[1] == 0xB8 && s[2] == 0x8F
}

// propertyWidths is a jump table of sorts, instead of a switch
var propertyWidths = [6]int{
	_Default:              1,
	_Zero_Width:           0,
	_East_Asian_Wide:      2,
	_East_Asian_Ambiguous: 1,
	_Emoji:                2,
	_Regional_Indicator:   2,
}

const upperBound = property(len(propertyWidths) - 1)
