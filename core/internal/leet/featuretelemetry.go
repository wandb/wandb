package leet

import (
	"maps"
	"reflect"
	"runtime"
	"slices"
	"strings"
	"unicode"

	tea "charm.land/bubbletea/v2"
)

// sessionFeatures records the UI features used during this process.
var sessionFeatures = &usedFeatures{names: map[string]struct{}{}}

type usedFeatures struct {
	names map[string]struct{}
}

func (f *usedFeatures) mark(name string) {
	f.names[name] = struct{}{}
}

// attributes returns the used features as one sorted, comma-joined value.
func (f *usedFeatures) attributes() map[string]string {
	attrs := map[string]string{}
	if len(f.names) > 0 {
		attrs["features_used"] = strings.Join(slices.Sorted(maps.Keys(f.names)), ",")
	}
	return attrs
}

// recordFeatureUsage wraps a key handler to record its use, naming the
// feature after the handler method (run.toggle_metrics_grid).
func recordFeatureUsage[T any](
	handler func(*T, tea.KeyPressMsg) tea.Cmd,
) func(*T, tea.KeyPressMsg) tea.Cmd {
	feature := featureName(handler)
	return func(t *T, msg tea.KeyPressMsg) tea.Cmd {
		sessionFeatures.mark(feature)
		return handler(t, msg)
	}
}

func featureName[T any](handler func(*T, tea.KeyPressMsg) tea.Cmd) string {
	name := runtime.FuncForPC(reflect.ValueOf(handler).Pointer()).Name()
	_, method, _ := strings.Cut(name, ").handle")
	return camelToSnake(reflect.TypeFor[T]().Name()) + "." + camelToSnake(method)
}

func camelToSnake(s string) string {
	var b strings.Builder
	for i, r := range s {
		if unicode.IsUpper(r) {
			if i > 0 {
				b.WriteByte('_')
			}
			r = unicode.ToLower(r)
		}
		b.WriteRune(r)
	}
	return b.String()
}
