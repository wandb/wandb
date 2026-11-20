// Package historycodec encodes normalized RunHistory values for the
// filestream MetricsBatch wire schema. Each top-level key is one cell;
// a nested subtree is one JSON cell, not a set of flattened keys.
//
// Supported values are nil, bool, int64, float64, string, []any and
// map[string]any. Extended JSON preserves float kinds at every depth,
// sorts map keys, and replaces each invalid UTF-8 byte with U+FFFD.
package historycodec

import (
	"fmt"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

// Kind returns the wire kind for a normalized value. Containers map to
// KIND_JSON; their contents are checked recursively by AppendJSON.
// Unsupported types return KIND_UNSPECIFIED and an error.
func Kind(v any) (filestreamv1.MetricsBatch_Kind, error) {
	switch v.(type) {
	case nil:
		return filestreamv1.MetricsBatch_KIND_NULL, nil
	case bool:
		return filestreamv1.MetricsBatch_KIND_BOOL, nil
	case int64:
		return filestreamv1.MetricsBatch_KIND_INT, nil
	case float64:
		return filestreamv1.MetricsBatch_KIND_FLOAT, nil
	case string:
		return filestreamv1.MetricsBatch_KIND_STRING, nil
	case []any, map[string]any:
		return filestreamv1.MetricsBatch_KIND_JSON, nil
	default:
		return filestreamv1.MetricsBatch_KIND_UNSPECIFIED,
			fmt.Errorf("historycodec: unsupported value type %T", v)
	}
}
