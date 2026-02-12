package leet

import (
	"reflect"
	"strconv"
	"strings"
	"sync"
	"unicode"
)

var (
	configEditorFieldsOnce   sync.Once
	configEditorFieldsCached []configField
)

// buildConfigEditorFields returns the config editor schema.
//
// The schema is derived from the [Config] struct (and nested structs) by
// inspecting `json` and `leet` struct tags. Results are computed once and
// cached; callers receive a defensive copy.
//
// # Tag grammar
//
// The `leet` tag supports the following comma-separated directives:
//
//   - `-`               Skip this field entirely.
//   - `label=<text>`    Override the auto-generated display label.
//   - `desc=<text>`     Description shown in the editor footer when
//     the field is selected.
//   - `min=<int>`       Minimum value for int fields (default 0).
//   - `max=<int>`       Maximum value for int fields (0 means no upper
//     bound).
//   - `options=<name>`  Marks a string field as an enum and names the
//     options provider function. Only providers registered in
//     [buildConfigEditorFieldsFromType] are recognized.
//
// # Field resolution rules
//
//   - Only exported fields with a non-empty `json` tag name are considered.
//   - Struct fields are traversed recursively. A struct field's
//     `leet:"desc=..."` is treated as a group description for its
//     children, enabling nice auto-descriptions for shared leaf types
//     (e.g. [GridConfig] rows/cols become "Rows in the main metrics grid.").
//   - String fields without an `options` provider are skipped to avoid
//     exposing free-text editing in the TUI.
//   - Unknown `leet` tag keys are silently ignored for forward compatibility.
func buildConfigEditorFields() []configField {
	configEditorFieldsOnce.Do(func() {
		configEditorFieldsCached = buildConfigEditorFieldsFromType(reflect.TypeOf(Config{}))
	})

	// Defensively copy so callers can't mutate the cached slice.
	out := make([]configField, len(configEditorFieldsCached))
	copy(out, configEditorFieldsCached)
	return out
}

// leetTag holds the parsed result of a `leet:"..."` struct tag.
type leetTag struct {
	skip bool

	label   string
	desc    string
	options string

	min    int
	hasMin bool
	max    int
	hasMax bool
}

// parseLeetTag parses a raw `leet` struct tag value into a [leetTag].
//
// Examples:
//
//	""                          → zero leetTag
//	"-"                         → leetTag{skip: true}
//	"label=Foo,desc=Bar,min=1"  → leetTag{label:"Foo", desc:"Bar", min:1, hasMin:true}
func parseLeetTag(raw string) leetTag {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return leetTag{}
	}
	if raw == "-" {
		return leetTag{skip: true}
	}

	var t leetTag
	for part := range strings.SplitSeq(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		key, val, ok := strings.Cut(part, "=")
		if !ok {
			// Reserved for future boolean flags, e.g. "readonly".
			continue
		}
		key = strings.TrimSpace(key)
		val = strings.TrimSpace(val)

		switch key {
		case "label":
			t.label = val
		case "desc":
			t.desc = val
		case "options":
			t.options = val
		case "min":
			if n, err := strconv.Atoi(val); err == nil {
				t.min = n
				t.hasMin = true
			}
		case "max":
			if n, err := strconv.Atoi(val); err == nil {
				t.max = n
				t.hasMax = true
			}
		default:
			// Unknown keys are ignored (forward-compatible).
		}
	}
	return t
}

// buildConfigEditorFieldsFromType reflects over a struct type and produces
// a flat list of [configField] values for every editable leaf.
//
// Enum providers map provider names (from `leet:"options=<name>"`) to
// functions that return the allowed values.
func buildConfigEditorFieldsFromType(t reflect.Type) []configField {
	enumProviders := map[string]func() []string{
		"colorSchemes": availableColorSchemes,
		"colorModes": func() []string {
			return []string{ColorModePerSeries, ColorModePerPlot}
		},
		"startupModes": func() []string {
			return []string{StartupModeWorkspaceLatest, StartupModeSingleRunLatest}
		},
	}

	var out []configField
	walkConfigFields(t, nil, nil, nil, "", enumProviders, &out)
	return out
}

// walkConfigFields recursively traverses struct fields to build [configField]
// entries for every editable leaf.
//
// Parameters accumulate state as we recurse into nested structs:
//   - indexPath tracks the [reflect.StructField.Index] chain for FieldByIndex.
//   - jsonPath tracks the dot-joined JSON key (e.g. "metrics_grid.rows").
//   - labelSegments accumulate humanized path segments for the display label.
//   - groupDesc propagates a parent struct's `leet:"desc=..."` to children.
func walkConfigFields(
	t reflect.Type,
	indexPath []int,
	jsonPath []string,
	labelSegments []string,
	groupDesc string,
	enumProviders map[string]func() []string,
	out *[]configField,
) {
	// Only structs can be walked.
	if t.Kind() != reflect.Struct {
		return
	}

	for i := 0; i < t.NumField(); i++ {
		sf := t.Field(i)
		if !sf.IsExported() {
			continue
		}

		jsonName, ok := jsonTagName(sf)
		if !ok {
			continue
		}

		tag := parseLeetTag(sf.Tag.Get("leet"))
		if tag.skip {
			continue
		}

		fieldIndex := appendIndex(indexPath, sf.Index)
		fieldJSONPath := appendString(jsonPath, jsonName)
		fieldLabelSegs := appendString(labelSegments, humanizeSegment(jsonName))

		// If this field is a struct, recurse into it.
		//
		// We treat a struct field's `leet:"desc=..."` as a *group description*
		// for children (e.g. metrics_grid.*) to allow nice auto-descriptions for
		// shared leaf types like GridConfig.
		if sf.Type.Kind() == reflect.Struct {
			childGroupDesc := groupDesc
			if tag.desc != "" {
				childGroupDesc = tag.desc
			}
			walkConfigFields(
				sf.Type,
				fieldIndex,
				fieldJSONPath,
				fieldLabelSegs,
				childGroupDesc,
				enumProviders,
				out,
			)
			continue
		}

		label := buildLabel(fieldLabelSegs, tag.label)
		key := strings.Join(fieldJSONPath, ".")

		switch sf.Type.Kind() {
		case reflect.Bool:
			desc := tag.desc
			if desc == "" {
				desc = defaultDescription(fieldJSONPath, groupDesc, label)
			}
			idx := cloneIndex(fieldIndex)

			*out = append(*out, configField{
				Label:       label,
				JSONKey:     key,
				Description: desc,
				Kind:        fieldBool,
				getBool: func(c Config) bool {
					return reflect.ValueOf(c).FieldByIndex(idx).Bool()
				},
				setBool: func(c *Config, v bool) {
					reflect.ValueOf(c).Elem().FieldByIndex(idx).SetBool(v)
				},
			})

		case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
			desc := tag.desc
			if desc == "" {
				desc = defaultDescription(fieldJSONPath, groupDesc, label)
			}

			minimum := 0
			if tag.hasMin {
				minimum = tag.min
			}
			maximum := 0
			if tag.hasMax {
				maximum = tag.max
			}
			idx := cloneIndex(fieldIndex)

			*out = append(*out, configField{
				Label:       label,
				JSONKey:     key,
				Description: desc,
				Kind:        fieldInt,
				getInt: func(c Config) int {
					return int(reflect.ValueOf(c).FieldByIndex(idx).Int())
				},
				setInt: func(c *Config, v int) {
					reflect.ValueOf(c).Elem().FieldByIndex(idx).SetInt(int64(v))
				},
				min: minimum,
				max: maximum,
			})

		case reflect.String:
			// Only string fields with an options provider are treated as editable enums.
			// (Keeps behavior explicit and avoids introducing free-text editing in the UI.)
			if tag.options == "" {
				continue
			}
			provider := enumProviders[tag.options]
			if provider == nil {
				// Unknown options provider. Skip rather than silently producing a broken field.
				continue
			}
			opts := provider()
			if len(opts) == 0 {
				continue
			}
			desc := tag.desc
			if desc == "" {
				desc = defaultDescription(fieldJSONPath, groupDesc, label)
			}
			idx := cloneIndex(fieldIndex)

			*out = append(*out, configField{
				Label:       label,
				JSONKey:     key,
				Description: desc,
				Kind:        fieldEnum,
				options:     opts,
				getEnum: func(c Config) string {
					return reflect.ValueOf(c).FieldByIndex(idx).String()
				},
				setEnum: func(c *Config, v string) {
					reflect.ValueOf(c).Elem().FieldByIndex(idx).SetString(v)
				},
			})

		default:
			// Unsupported type: skip.
			continue
		}
	}
}

// jsonTagName extracts the field name from a `json` struct tag.
// Returns ("", false) for empty tags and the explicit skip marker "-".
func jsonTagName(sf reflect.StructField) (string, bool) {
	raw := sf.Tag.Get("json")
	if raw == "" {
		return "", false
	}
	name, _, _ := strings.Cut(raw, ",")
	name = strings.TrimSpace(name)
	if name == "" || name == "-" {
		return "", false
	}
	return name, true
}

// humanizeSegment converts a JSON key segment (e.g. "heartbeat_interval")
// into a space-separated lowercase form ("heartbeat interval").
func humanizeSegment(seg string) string {
	seg = strings.ReplaceAll(seg, "_", " ")
	seg = strings.ReplaceAll(seg, "-", " ")
	return strings.ToLower(seg)
}

// buildLabel returns the display label for a field, using the tag override
// if provided or joining the humanized path segments with sentence casing.
func buildLabel(labelSegments []string, override string) string {
	if override != "" {
		return override
	}
	return sentenceCase(strings.Join(labelSegments, " "))
}

// sentenceCase upper-cases the first rune of s.
func sentenceCase(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	r := []rune(s)
	r[0] = unicode.ToUpper(r[0])
	return string(r)
}

// lowerFirst lower-cases the first rune of s.
func lowerFirst(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	r := []rune(s)
	r[0] = unicode.ToLower(r[0])
	return string(r)
}

// defaultDescription generates a fallback description when none is specified
// via `leet:"desc=..."`.
//
// Grid leaf fields (rows/cols) get contextual descriptions like "Rows in the
// main metrics grid." using the parent's groupDesc. Everything else falls back
// to "Set <label>."
func defaultDescription(jsonPath []string, groupDesc, label string) string {
	// Special case for grid configs: infer nice descriptions automatically.
	if len(jsonPath) >= 2 {
		leaf := jsonPath[len(jsonPath)-1]
		if leaf == "rows" || leaf == "cols" {
			target := strings.TrimSpace(groupDesc)
			if target == "" {
				target = humanizeSegment(jsonPath[len(jsonPath)-2])
			}

			if leaf == "rows" {
				return "Rows in the " + target + "."
			}
			return "Columns in the " + target + "."
		}
	}

	// Generic fallback: good enough for new fields until you add a `leet:"desc=..."`.
	if label != "" {
		return "Set " + lowerFirst(label) + "."
	}

	return ""
}

// appendIndex returns a new slice containing prefix followed by suffix.
func appendIndex(prefix, suffix []int) []int {
	out := make([]int, 0, len(prefix)+len(suffix))
	out = append(out, prefix...)
	out = append(out, suffix...)
	return out
}

// cloneIndex returns an independent copy of in.
func cloneIndex(in []int) []int {
	out := make([]int, len(in))
	copy(out, in)
	return out
}

// appendString returns a new slice containing prefix followed by elem.
func appendString(prefix []string, elem string) []string {
	out := make([]string, 0, len(prefix)+1)
	out = append(out, prefix...)
	out = append(out, elem)
	return out
}
