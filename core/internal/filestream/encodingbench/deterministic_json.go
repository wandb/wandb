package encodingbench

import (
	"bytes"
	"fmt"
	"math"
	"slices"
	"strconv"

	"github.com/wandb/simplejsonext"
)

func marshalSortedJSON(value any) ([]byte, error) {
	var buf bytes.Buffer
	if err := writeSortedJSON(&buf, value); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func writeSortedJSON(buf *bytes.Buffer, value any) error {
	switch value := value.(type) {
	case nil:
		buf.WriteString("null")
	case bool:
		if value {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case string:
		encoded, err := simplejsonext.Marshal(value)
		if err != nil {
			return err
		}
		buf.Write(encoded)
	case float64:
		switch {
		case math.IsNaN(value):
			buf.WriteString("NaN")
		case math.IsInf(value, 1):
			buf.WriteString("Infinity")
		case math.IsInf(value, -1):
			buf.WriteString("-Infinity")
		default:
			buf.WriteString(strconv.FormatFloat(value, 'g', -1, 64))
		}
	case int:
		buf.WriteString(strconv.Itoa(value))
	case int64:
		buf.WriteString(strconv.FormatInt(value, 10))
	case []any:
		buf.WriteByte('[')
		for index, element := range value {
			if index > 0 {
				buf.WriteByte(',')
			}
			if err := writeSortedJSON(buf, element); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case []string:
		buf.WriteByte('[')
		for index, element := range value {
			if index > 0 {
				buf.WriteByte(',')
			}
			encoded, err := simplejsonext.Marshal(element)
			if err != nil {
				return err
			}
			buf.Write(encoded)
		}
		buf.WriteByte(']')
	case map[string]any:
		keys := sortedMapKeys(value)
		buf.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				buf.WriteByte(',')
			}
			keyJSON, err := simplejsonext.Marshal(key)
			if err != nil {
				return err
			}
			buf.Write(keyJSON)
			buf.WriteByte(':')
			if err := writeSortedJSON(buf, value[key]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		encoded, err := simplejsonext.Marshal(value)
		if err != nil {
			return fmt.Errorf("marshal %T: %w", value, err)
		}
		buf.Write(encoded)
	}
	return nil
}

func sortedMapKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	return keys
}
