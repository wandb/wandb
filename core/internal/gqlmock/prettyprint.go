package gqlmock

import (
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"
)

// indent returns the string with each line indented by the given amount.
//
// Each indent is two spaces.
func indent(n int, s string) string {
	return prefixLines(strings.Repeat("  ", n), s)
}

// prefixLines returns the given string with a prefix appended to each line.
//
// If the string is the empty string, an empty string is returned.
func prefixLines(prefix, s string) string {
	if s == "" {
		return ""
	}

	result := strings.Builder{}

	found := true
	for found {
		var before, after string
		before, after, found = strings.Cut(s, "\n")

		result.WriteString(prefix)
		result.WriteString(before)
		if found {
			result.WriteString("\n")
		}

		s = after
	}

	return result.String()
}

// prettyPrintVariables returns a string with the given GQL request's variables.
func prettyPrintVariables(req *graphql.Request) string {
	result := strings.Builder{}

	varMap := jsonMarshallToMap(req.Variables)

	nWritten := 0
	for key, value := range varMap {
		result.WriteString(key)
		result.WriteString(": ")
		_, _ = fmt.Fprintf(&result, "%#v", value)

		if nWritten < len(varMap) {
			result.WriteString("\n")
		}

		nWritten++
	}

	return result.String()
}
