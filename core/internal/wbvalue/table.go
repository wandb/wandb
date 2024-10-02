package wbvalue

import (
	"encoding/json"
	"path/filepath"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/paths"
)

// Table is tabular data logged to a run.
//
// Tables are saved as run files and their metadata is stored in
// the run history.
type Table struct {
	// Rows is the table's data represented as a list of rows,
	// each of which is an ordered list of column values corresponding to
	// the labels in the ColumnLabels field.
	//
	// Values must be marshallable by simplejsonext.
	Rows [][]any

	// ColumnLabels are the names of the table's columns.
	ColumnLabels []string
}

// FileContent is the data to write to the table's file.
func (t Table) FileContent() ([]byte, error) {
	// We use simplejsonext to encode NaN and ±Infinity values.
	return simplejsonext.Marshal(map[string]any{
		"columns": t.ColumnLabels,
		"data":    t.Rows,
	})
}

// HistoryValueJSON is the table metadata to keep in the run history.
//
// The arguments are the hash and size of `FileContent`
// and the run file path it was saved to.
func (t Table) HistoryValueJSON(
	filePath paths.RelativePath,
	fileSHA256 string,
	fileSizeBytes int,
) (string, error) {
	bytes, err := json.Marshal(map[string]any{
		"_type":  "table-file",
		"ncols":  len(t.ColumnLabels),
		"nrows":  len(t.Rows),
		"sha256": fileSHA256,
		"size":   fileSizeBytes,
		"path":   filepath.ToSlash(string(filePath)),
	})

	if err != nil {
		return "", err
	}

	return string(bytes), err
}
