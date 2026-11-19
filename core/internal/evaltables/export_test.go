package evaltables

import (
	"bytes"
	"testing"

	"github.com/stretchr/testify/require"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ColumnsJSON returns the body of the table's column request, without its
// scope ID.
func (t *EncodedTable) ColumnsJSON(tb testing.TB) string {
	tb.Helper()
	body, err := t.columns.MarshalJSON()
	require.NoError(tb, err)
	return string(body)
}

// CESRowsJSON returns the table's CES rows as a JSON array.
func (t *EncodedTable) CESRowsJSON(tb testing.TB) string {
	tb.Helper()
	var rows [][]byte
	for row, err := range t.rows() {
		require.NoError(tb, err)
		rows = append(rows, row)
	}
	return "[" + string(bytes.Join(rows, []byte(","))) + "]"
}

// OversizedMediaCells returns the media cells encoded as null because
// their CES extension value was too large.
func (t *EncodedTable) OversizedMediaCells() []*spb.EvalTableOversizedMediaCell {
	return t.oversizedMedia
}
