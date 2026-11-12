package evaltables

import (
	"bytes"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

// SetRetryWaitMinForTest sets the minimum wait before retrying a CES
// request until the test ends.
func SetRetryWaitMinForTest(t *testing.T, d time.Duration) {
	t.Helper()
	original := retryWaitMin
	retryWaitMin = d
	t.Cleanup(func() { retryWaitMin = original })
}

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
	var rows [][]byte
	for row, err := range t.rows() {
		require.NoError(tb, err)
		rows = append(rows, row)
	}
	return "[" + string(bytes.Join(rows, []byte(","))) + "]"
}
