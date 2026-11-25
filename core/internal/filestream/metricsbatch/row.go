// Package metricsbatch builds filestream MetricsBatch messages from
// RunHistory rows.
//
// Each top-level key is one cell. A nested subtree or an array is one
// KIND_JSON cell holding its simplejsonext encoding, so a nested 1.0
// becomes 1. The top-level _step goes to the sequence column.
package metricsbatch

import (
	"errors"
	"unicode/utf8"

	"github.com/wandb/simplejsonext"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/runhistory"
)

// seqKey is the key whose value goes to the sequence column.
const seqKey = "_step"

// Row is one encoded history row. It is immutable and can be appended
// to several builders.
type Row struct {
	cells   []cell
	step    int64
	hasStep bool
}

// cell is one encoded top-level value. text holds a string or JSON payload.
type cell struct {
	key   string
	kind  filestreamv1.MetricsBatch_Kind
	bool  bool
	int   int64
	float float64
	text  string
}

// Prepare encodes one row. It drops each malformed cell and returns the
// joined errors. The Row is valid also when the error is not nil.
// The Row keeps no RunHistory containers.
//
// Error messages contain no metric keys or values.
func Prepare(rh *runhistory.RunHistory) (*Row, error) {
	row := &Row{}
	var errs []error
	rh.ForEachTopLevel(func(key string, value any) {
		if key == seqKey {
			if row.step, row.hasStep = value.(int64); !row.hasStep {
				errs = append(errs, errors.New("metricsbatch: sequence must be int64"))
			}
			return
		}
		c, err := encodeCell(key, value)
		if err != nil {
			errs = append(errs, err)
			return
		}
		row.cells = append(row.cells, c)
	})
	return row, errors.Join(errs...)
}

func encodeCell(key string, value any) (cell, error) {
	if key == "" {
		return cell{}, errors.New("metricsbatch: empty key")
	}
	c := cell{key: key}
	switch v := value.(type) {
	case nil:
		c.kind = filestreamv1.MetricsBatch_KIND_NULL
	case bool:
		c.kind, c.bool = filestreamv1.MetricsBatch_KIND_BOOL, v
	case int64:
		c.kind, c.int = filestreamv1.MetricsBatch_KIND_INT, v
	case float64:
		c.kind, c.float = filestreamv1.MetricsBatch_KIND_FLOAT, v
	case string:
		c.kind, c.text = filestreamv1.MetricsBatch_KIND_STRING, v
	case []any, map[string]any:
		text, err := simplejsonext.MarshalToString(v)
		if err != nil {
			return cell{}, errors.New("metricsbatch: JSON encoding failed")
		}
		c.kind, c.text = filestreamv1.MetricsBatch_KIND_JSON, text
	default:
		return cell{}, errors.New("metricsbatch: unsupported value type")
	}
	// simplejsonext copies string bytes unchanged, so checking the JSON
	// text also checks each nested key and string.
	if !utf8.ValidString(key) || !utf8.ValidString(c.text) {
		return cell{}, errors.New("metricsbatch: invalid UTF-8")
	}
	return c, nil
}
