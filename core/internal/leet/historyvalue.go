package leet

import (
	"math"
	"strconv"
	"strings"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// typedHistoryValue returns the typed value or nil otherwise.
func typedHistoryValue(item *spb.HistoryItem) (*spb.HistoryValue, bool) {
	v := item.GetValue()
	if v == nil || v.GetValue() == nil {
		return nil, false
	}
	return v, true
}

// historyItemFloat returns the item's value as a chart point.
// The boolean return value is false if the value is not a number.
func historyItemFloat(item *spb.HistoryItem) (float64, bool) {
	if v, ok := typedHistoryValue(item); ok {
		switch value := v.GetValue().(type) {
		case *spb.HistoryValue_Number:
			return value.Number, true
		case *spb.HistoryValue_Integer:
			// Above 2^53 this rounds. The JSON path rounds the same way.
			return float64(value.Integer), true
		case *spb.HistoryValue_Text:
			// A logged string that holds a number plots today, because the
			// JSON path unquotes the text before it parses.
			f, err := strconv.ParseFloat(value.Text, 64)
			return f, err == nil
		case *spb.HistoryValue_Json:
			f, err := strconv.ParseFloat(trimJSONString(value.Json), 64)
			return f, err == nil
		case *spb.HistoryValue_None, *spb.HistoryValue_Boolean:
			return 0, false
		}
	}

	f, err := strconv.ParseFloat(trimJSONString(item.GetValueJson()), 64)
	return f, err == nil
}

// historyItemString returns the item's value as display text.
func historyItemString(item *spb.HistoryItem) string {
	if v, ok := typedHistoryValue(item); ok {
		switch value := v.GetValue().(type) {
		case *spb.HistoryValue_None:
			// value_json holds the text "null", so the typed form matches it.
			return "null"
		case *spb.HistoryValue_Number:
			return formatJSONFloat(value.Number)
		case *spb.HistoryValue_Integer:
			return strconv.FormatInt(value.Integer, 10)
		case *spb.HistoryValue_Boolean:
			return strconv.FormatBool(value.Boolean)
		case *spb.HistoryValue_Text:
			return value.Text
		case *spb.HistoryValue_Json:
			return trimJSONString(value.Json)
		}
	}

	return trimJSONString(item.GetValueJson())
}

// historyItemStep returns the item's value as a step number.
func historyItemStep(item *spb.HistoryItem) (int64, bool) {
	if v, ok := typedHistoryValue(item); ok {
		switch value := v.GetValue().(type) {
		case *spb.HistoryValue_Integer:
			return value.Integer, true
		case *spb.HistoryValue_Json:
			n, err := strconv.ParseInt(strings.TrimSpace(value.Json), 10, 64)
			return n, err == nil
		case *spb.HistoryValue_None,
			*spb.HistoryValue_Boolean,
			*spb.HistoryValue_Number,
			*spb.HistoryValue_Text:
			return 0, false
		}
	}

	n, err := strconv.ParseInt(strings.TrimSpace(item.GetValueJson()), 10, 64)
	return n, err == nil
}

// formatJSONFloat renders a float the way the JSON writer does, so typed
// and JSON reads of one value produce the same text.
func formatJSONFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return "NaN"
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	}

	s := strconv.FormatFloat(f, 'g', -1, 64)
	if !strings.ContainsAny(s, ".e") {
		// Go prints a whole float as "1" and Python prints "1.0"
		// Ensure that both readers get the same text.
		s += ".0"
	}
	return s
}
