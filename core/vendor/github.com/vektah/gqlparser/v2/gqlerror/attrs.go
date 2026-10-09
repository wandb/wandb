package gqlerror

import (
	"log/slog"
	"slices"

	"github.com/vektah/gqlparser/v2/ast"
)

// Attrs reports the error's own fields as a single slog group named "gql": message, path,
// locations, extensions and rule, each left out when empty. The result is nil when every field
// is empty, or for a nil *Error.
//
// The group keeps these keys from colliding with a cause's: gqlgen's InvalidNullError, for one,
// reports a path of its own.
//
// Err is not reported. Attrs means an error's own attributes, never its cause's, so a walk that
// collects Attrs from every error in a chain visits the cause exactly once. CollectAttrs is that
// walk, and it merges a cause's "gql" group into this one.
func (err *Error) Attrs() []slog.Attr {
	if err == nil {
		return nil
	}
	var locations slog.Attr
	if len(err.Locations) > 0 {
		locations = slog.Any("locations", err.Locations)
	}
	return gqlAttrs(err.Message, err.Path, locations, err.Extensions, err.Rule)
}

// Attrs reports the error's own fields as Error.Attrs does, in the same "gql" group under the
// same keys. Each location also names its source document, when it has one: in JSON as a
// "source" field beside "line" and "column", and in text as name:line:column.
//
// The *ast.Source itself is not logged. It would print as a pointer, and it holds the whole
// document.
func (err *ErrorWithSources) Attrs() []slog.Attr {
	if err == nil {
		return nil
	}
	var locations slog.Attr
	if len(err.Locations) > 0 {
		logged := make([]loggedLocation, len(err.Locations))
		for i, location := range err.Locations {
			logged[i] = loggedLocation{Line: location.Line, Column: location.Column}
			if location.Source != nil {
				logged[i].Source = location.Source.Name
			}
		}
		locations = slog.Any("locations", logged)
	}
	return gqlAttrs(err.Message, err.Path, locations, err.Extensions, err.Rule)
}

// loggedLocation is a SourceLocation as it is logged: the source document by name only.
type loggedLocation struct {
	Line   int    `json:"line,omitempty"`
	Column int    `json:"column,omitempty"`
	Source string `json:"source,omitempty"`
}

// String writes the location as Location.String does, prefixed with the source name when there
// is one, so that a text handler prints both error types' locations alike.
func (l loggedLocation) String() string {
	position := Location{Line: l.Line, Column: l.Column}.String()
	if l.Source == "" {
		return position
	}
	return l.Source + ":" + position
}

// gqlAttrs builds the "gql" group that both error types report, so the group's name, its keys,
// their order and the rule that an empty field is left out are decided in one place. locations
// is the zero Attr when there are none, because only the caller knows how its type logs them.
func gqlAttrs(
	message string,
	path ast.Path,
	locations slog.Attr,
	extensions map[string]any,
	rule string,
) []slog.Attr {
	// Sized for every field, so building the group costs one allocation rather than a regrowth
	// per field.
	fields := make([]slog.Attr, 0, 5)
	if message != "" {
		fields = append(fields, slog.String("message", message))
	}
	if len(path) > 0 {
		fields = append(fields, slog.String("path", path.String()))
	}
	if locations.Key != "" {
		fields = append(fields, locations)
	}
	if len(extensions) > 0 {
		fields = append(fields, slog.Any("extensions", extensions))
	}
	if rule != "" {
		fields = append(fields, slog.String("rule", rule))
	}
	if len(fields) == 0 {
		return nil
	}
	return []slog.Attr{{Key: "gql", Value: slog.GroupValue(fields...)}}
}

// CollectAttrs reports the attributes of every error in err's tree, merged so that no key appears
// twice at any level. It is what logging middleware should pass to slog for a GraphQL error.
//
// It visits err and then what Unwrap returns, depth first and, for Unwrap() []error, left to
// right, taking Attrs() []slog.Attr from each error that has the method. Groups with the same key
// are merged, so a cause reporting a "gql" group of its own adds keys to this package's group
// rather than repeating it, which JSON readers would resolve by dropping one of the two. For any
// other key reported twice, the first value found wins: the outermost error's, which is normally
// the *Error the GraphQL response carried.
//
// Attributes follow slog's rules: values are resolved, a group with an empty key is inlined, and
// a zero Attr or an empty group is dropped. Keys keep the order they first appear in. The result
// is nil when nothing is reported. No error's attributes are modified.
//
// A cause reporting into the "gql" group should not reuse the keys Error.Attrs reports for its
// own meaning: message, path, locations, extensions and rule.
//
// Like errors.Is, CollectAttrs does not guard against an Unwrap cycle.
func CollectAttrs(err error) []slog.Attr {
	return collectAttrs(nil, err)
}

// attrser is what CollectAttrs looks for in each error: the error's own attributes.
type attrser interface {
	Attrs() []slog.Attr
}

// collectAttrs merges the attributes of err's tree into collected, err's own before its causes'.
func collectAttrs(collected []slog.Attr, err error) []slog.Attr {
	if e, ok := err.(attrser); ok {
		collected = mergeAttrs(collected, e.Attrs())
	}
	switch e := err.(type) {
	case interface{ Unwrap() error }:
		collected = collectAttrs(collected, e.Unwrap())
	case interface{ Unwrap() []error }:
		for _, cause := range e.Unwrap() {
			collected = collectAttrs(collected, cause)
		}
	}
	return collected
}

// mergeAttrs adds src to dst, which holds no key twice. A group merges into dst's group of the
// same key; any other key already in dst keeps its value. A revisited error therefore adds
// nothing, which is why CollectAttrs keeps no record of the errors it has seen.
//
// Every group mergeAttrs adds is rebuilt from a slice of its own, so the in-place writes that
// merging makes never reach a group belonging to the error that reported it.
func mergeAttrs(dst, src []slog.Attr) []slog.Attr {
	for _, a := range src {
		a.Value = a.Value.Resolve()
		isGroup := a.Value.Kind() == slog.KindGroup

		// Inline and drop what slog would, so that neither takes up a key.
		if isGroup {
			fields := mergeAttrs(nil, a.Value.Group())
			if len(fields) == 0 {
				continue
			}
			if a.Key == "" {
				dst = mergeAttrs(dst, fields)
				continue
			}
			a.Value = slog.GroupValue(fields...)
		} else if a.Key == "" && a.Value.Any() == nil {
			continue
		}

		i := slices.IndexFunc(dst, func(d slog.Attr) bool { return d.Key == a.Key })
		switch {
		case i < 0:
			dst = append(dst, a)
		case isGroup && dst[i].Value.Kind() == slog.KindGroup:
			dst[i].Value = slog.GroupValue(mergeAttrs(dst[i].Value.Group(), a.Value.Group())...)
		}
	}
	return dst
}
