// Package levenshtein is a Go implementation to calculate Levenshtein Distance.
//
// Implementation taken from
// https://gist.github.com/andrei-m/982927#gistcomment-1931258
package levenshtein

import "unicode/utf8"

// minLengthThreshold is the length of the string beyond which
// an allocation will be made. Strings smaller than this will be
// zero alloc.
const minLengthThreshold = 32

// ComputeDistance computes the levenshtein distance between the two
// strings passed as an argument. The return value is the levenshtein distance
//
// Works on runes (Unicode code points) but does not normalize
// the input strings. See https://blog.golang.org/normalization
// and the golang.org/x/text/unicode/norm package.
func ComputeDistance(a, b string) int {
	if len(a) == 0 {
		return utf8.RuneCountInString(b)
	}

	if len(b) == 0 {
		return utf8.RuneCountInString(a)
	}

	if a == b {
		return 0
	}

	// We need to convert to []rune if the strings are non-ASCII.
	// This could be avoided by using utf8.RuneCountInString
	// and then doing some juggling with rune indices,
	// but leads to far more bounds checks. It is a reasonable trade-off.
	s1 := []rune(a)
	s2 := []rune(b)

	// swap to save some memory O(min(a,b)) instead of O(a)
	if len(s1) > len(s2) {
		s1, s2 = s2, s1
	}

	// remove trailing identical runes.
	s1, s2 = trimLongestCommonSuffix(s1, s2)

	// Remove leading identical runes.
	s1, s2 = trimLongestCommonPrefix(s1, s2)

	// A uint16 row holds a distance through 65535. Longer strings use int.
	if len(s2) > 65535 {
		return distance[int](s1, s2)
	}
	return int(distance[uint16](s1, s2))
}

func distance[T uint16 | int](s1, s2 []rune) T {
	lenS1 := len(s1)
	lenS2 := len(s2)

	// Init the row.
	var x []T
	if lenS1+1 > minLengthThreshold {
		x = make([]T, lenS1+1)
	} else {
		// We make a small optimization here for small strings.
		// Because a slice of constant length is effectively an array,
		// it does not allocate. So we can re-slice it to the right length
		// as long as it is below a desired threshold.
		x = make([]T, minLengthThreshold)
		x = x[:lenS1+1]
	}

	// we start from 1 because index 0 is already 0.
	for i := 1; i < len(x); i++ {
		x[i] = T(i)
	}

	// hoist bounds checks out of the loops
	_ = x[lenS1]
	y := x[1:]
	y = y[:lenS1]
	// fill in the rest
	for i := 0; i < lenS2; i++ {
		prev := T(i + 1)
		for j := 0; j < lenS1; j++ {
			current := x[j] // match
			if s2[i] != s1[j] {
				current = min(x[j], prev, y[j]) + 1
			}
			x[j] = prev
			prev = current
		}
		x[lenS1] = prev
	}
	return x[lenS1]
}

func trimLongestCommonSuffix(a, b []rune) ([]rune, []rune) {
	m := min(len(a), len(b))
	a2 := a[len(a)-m:]
	b2 := b[len(b)-m:]
	i := len(a2)
	b2 = b2[:i] // hoist bounds checks out of the loop
	for ; i > 0 && a2[i-1] == b2[i-1]; i-- {
		// deliberately empty body
	}
	return a[:len(a)-len(a2)+i], b[:len(b)-len(b2)+i]
}

func trimLongestCommonPrefix(a, b []rune) ([]rune, []rune) {
	var i int
	for m := min(len(a), len(b)); i < m && a[i] == b[i]; i++ {
		// deliberately empty body
	}
	return a[i:], b[i:]
}
