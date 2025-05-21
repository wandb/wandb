package generate

import (
	"strings"
	"unicode"
	"unicode/utf8"
)

func reverse(slice []string) {
	for left, right := 0, len(slice)-1; left < right; left, right = left+1, right-1 {
		slice[left], slice[right] = slice[right], slice[left]
	}
}

func changeFirst(s string, f func(rune) rune) string {
	c, n := utf8.DecodeRuneInString(s)
	if c == utf8.RuneError { // empty or invalid
		return s
	}
	return string(f(c)) + s[n:]
}

func lowerFirst(s string) string {
	return changeFirst(strings.TrimLeft(s, "_"), unicode.ToLower)
}

func upperFirst(s string) string {
	return changeFirst(strings.TrimLeft(s, "_"), unicode.ToUpper)
}

func snakeToCamel(s string) string {
	var result strings.Builder
	var nextUpper bool

	for _, r := range s {
		if r == '_' {
			nextUpper = true
			continue
		}

		if nextUpper {
			result.WriteRune(unicode.ToUpper(r))
			nextUpper = false
		} else {
			result.WriteRune(r)
		}
	}

	return result.String()
}

func goConstName(s string) string {
	if strings.TrimLeft(s, "_") == "" {
		return s
	}
	var prev rune
	return strings.Map(func(r rune) rune {
		var ret rune
		if r == '_' {
			ret = -1
		} else if prev == '_' || prev == 0 {
			ret = unicode.ToUpper(r)
		} else {
			ret = unicode.ToLower(r)
		}
		prev = r
		return ret
	}, s)
}

// ApplyCasing applies a specific casing algorithm to a string.
// It handles the different casing transformations based on the algorithm.
// The forceUpperFirst flag is used to make the first character uppercase regardless
// of the algorithm.
func ApplyCasing(s string, algo CasingAlgorithm, forceUpperFirst bool) string {
	var result string

	switch algo {
	case CasingAutoCamelCase:
		result = snakeToCamel(s)
	case CasingRaw:
		result = s
	case CasingDefault:
		// Default casing implementation
		result = s
	default:
		// Unknown algorithm - treat as default
		result = s
	}

	if forceUpperFirst {
		result = upperFirst(result)
	}

	return result
}

// https://go.dev/ref/spec#Keywords
var goKeywords = map[string]bool{
	"break":       true,
	"default":     true,
	"func":        true,
	"interface":   true,
	"select":      true,
	"case":        true,
	"defer":       true,
	"go":          true,
	"map":         true,
	"struct":      true,
	"chan":        true,
	"else":        true,
	"goto":        true,
	"package":     true,
	"switch":      true,
	"const":       true,
	"fallthrough": true,
	"if":          true,
	"range":       true,
	"type":        true,
	"continue":    true,
	"for":         true,
	"import":      true,
	"return":      true,
	"var":         true,
}
