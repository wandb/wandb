package generate

import (
	"fmt"
	"go/token"
	"go/types"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// makeIdentifier takes a string and returns a valid go identifier like it.
//
// If the string is an identifier, return the input. Otherwise, munge it to
// make a valid identifier, which at worst (if the input is entirely emoji,
// say) means coming up with one out of whole cloth. This identifier need not
// be particularly unique; the caller may add a suffix.
func makeIdentifier(candidateIdentifier string) string {
	if token.IsIdentifier(candidateIdentifier) {
		return candidateIdentifier
	}

	var goodChars strings.Builder
	for _, c := range candidateIdentifier {
		// modified from token.IsIdentifier
		if unicode.IsLetter(c) || c == '_' ||
			// digits only valid after first char
			goodChars.Len() > 0 && unicode.IsDigit(c) {
			goodChars.WriteRune(c)
		}
	}
	if goodChars.Len() > 0 {
		return goodChars.String()
	}

	return "alias"
}

func (g *generator) addImportFor(pkgPath string) (alias string) {
	pkgName := makeIdentifier(pkgPath[strings.LastIndex(pkgPath, "/")+1:])
	alias = pkgName
	suffix := 2
	for g.usedAliases[alias] {
		alias = pkgName + strconv.Itoa(suffix)
		suffix++
	}

	g.imports[pkgPath] = alias
	g.usedAliases[alias] = true
	return alias
}

var _sliceOrMapPrefixRegexp = regexp.MustCompile(`^(\*|\[\d*\]|map\[string\])*`)

// ref takes a Go fully-qualified name, ensures that any necessary symbols are
// imported, and returns an appropriate reference.
//
// Ideally, we want to allow a reference to basically an arbitrary symbol.
// But that's very hard, because it might be quite complicated, like
//
//	struct{ F []map[mypkg.K]otherpkg.V }
//
// Now in practice, using an unnamed struct is not a great idea, but we do
// want to allow as much as we can that encoding/json knows how to work
// with, since you would reasonably expect us to accept, say,
// map[string][]interface{}.  So we allow:
//   - any named type (mypkg.T)
//   - any predeclared basic type (string, int, etc.)
//   - interface{}
//   - for any allowed type T, *T, []T, [N]T, and map[string]T
//
// which effectively excludes:
//   - unnamed struct types
//   - map[K]V where K is a named type wrapping string
//   - any nonstandard spelling of those (interface {/* hi */},
//     map[  string      ]T)
//
// (This is documented in docs/genqlient.yaml)
func (g *generator) ref(fullyQualifiedName string) (qualifiedName string, err error) {
	errorMsg := `invalid type-name "%v" (%v); expected a builtin, ` +
		`path/to/package.Name, interface{}, or a slice, map, or pointer of those`

	if strings.Contains(fullyQualifiedName, " ") {
		return "", errorf(nil, errorMsg, fullyQualifiedName, "contains spaces")
	}

	prefix := _sliceOrMapPrefixRegexp.FindString(fullyQualifiedName)
	nameToImport := fullyQualifiedName[len(prefix):]

	i := strings.LastIndex(nameToImport, ".")
	if i == -1 {
		if nameToImport != "interface{}" && types.Universe.Lookup(nameToImport) == nil {
			return "", errorf(nil, errorMsg, fullyQualifiedName,
				fmt.Sprintf(`unknown type-name "%v"`, nameToImport))
		}
		return fullyQualifiedName, nil
	}

	pkgPath := nameToImport[:i]
	localName := nameToImport[i+1:]
	if pkgPath == g.Config.pkgPath {
		return prefix + localName, nil
	}
	alias, ok := g.imports[pkgPath]
	if !ok {
		if g.importsLocked {
			return "", errorf(nil,
				`genqlient internal error: imports locked but package "%v" has not been imported`, pkgPath)
		}
		alias = g.addImportFor(pkgPath)
	}
	return prefix + alias + "." + localName, nil
}

// Returns the import-clause to use in the generated code.
func (g *generator) Imports() string {
	g.importsLocked = true
	if len(g.imports) == 0 {
		return ""
	}

	var builder strings.Builder
	builder.WriteString("import (\n")
	for path, alias := range g.imports {
		if path == alias || strings.HasSuffix(path, "/"+alias) {
			builder.WriteString("\t" + strconv.Quote(path) + "\n")
		} else {
			builder.WriteString("\t" + alias + " " + strconv.Quote(path) + "\n")
		}
	}
	builder.WriteString(")\n\n")
	return builder.String()
}
