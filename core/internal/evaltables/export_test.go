package evaltables

import (
	"bytes"
	"testing"

	"github.com/stretchr/testify/require"
)

// ColumnsJSON returns the body of the table's column request, without its
// scope ID.
func (t *EncodedTable) ColumnsJSON(tb testing.TB) string {
	tb.Helper()
	body, err := t.columns.MarshalJSON()
	require.NoError(tb, err)
	return string(body)
}

// RowsJSON returns the table's CES rows as a JSON array.
func (t *EncodedTable) RowsJSON(tb testing.TB) string {
	tb.Helper()
	return "[" + string(bytes.Join(t.rowsJSON, []byte(","))) + "]"
}
