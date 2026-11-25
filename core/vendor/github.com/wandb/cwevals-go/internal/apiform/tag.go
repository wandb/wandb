package apiform

import (
	"reflect"
	"strings"
)

const apiStructTag = "api"
const jsonStructTag = "json"
const formStructTag = "form"
const formatStructTag = "format"

type parsedStructTag struct {
	name     string
	required bool
	extras   bool
	metadata bool
}

func parseFormStructTag(field reflect.StructField) (tag parsedStructTag, ok bool) {
	raw, ok := field.Tag.Lookup(formStructTag)
	if !ok {
		raw, ok = field.Tag.Lookup(jsonStructTag)
	}
	if !ok {
		return tag, ok
	}
	parts := strings.Split(raw, ",")
	if len(parts) == 0 {
		return tag, false
	}
	tag.name = parts[0]
	for _, part := range parts[1:] {
		switch part {
		case "required":
			tag.required = true
		case "extras":
			tag.extras = true
		case "metadata":
			tag.metadata = true
		}
	}

	// the `api` struct tag is only used alongside `json` for custom behaviour
	parseApiStructTag(field, &tag)
	return tag, ok
}

func parseApiStructTag(field reflect.StructField, tag *parsedStructTag) {
	raw, ok := field.Tag.Lookup(apiStructTag)
	if !ok {
		return
	}
	parts := strings.Split(raw, ",")
	for _, part := range parts {
		switch part {
		case "extrafields":
			tag.extras = true
		case "required":
			tag.required = true
		case "metadata":
			tag.metadata = true
		}
	}
}

func parseFormatStructTag(field reflect.StructField) (format string, ok bool) {
	format, ok = field.Tag.Lookup(formatStructTag)
	return format, ok
}
