package runreader

import (
	"context"
	"errors"
	"io"

	"github.com/wandb/wandb/core/internal/observability"
)

// HistoryQuery selects history rows.
type HistoryQuery struct {
	// Keys restricts the items returned to these keys; empty means all.
	// Rows with none of the keys are skipped.
	Keys []string

	// MinStep and MaxStep bound the rows' steps, inclusive, when non-nil.
	MinStep, MaxStep *int64

	// Last, when positive, keeps only the last N matching rows.
	Last int
}

// HistoryItem is one logged value, JSON-encoded as it was logged.
type HistoryItem struct {
	Key       string
	ValueJSON string
}

// HistoryRow is one history step's matching items.
type HistoryRow struct {
	Step  int64
	Items []HistoryItem
}

// ScanHistory reads the rows matching the query from the transaction log at
// path. The log has no index, so this reads the whole file every time.
func ScanHistory(
	ctx context.Context,
	path string,
	query HistoryQuery,
	logger *observability.CoreLogger,
) ([]HistoryRow, error) {
	cursor, err := OpenCursor(path, logger)
	if err != nil {
		return nil, err
	}
	defer cursor.Close()

	var keys map[string]struct{}
	if len(query.Keys) > 0 {
		keys = make(map[string]struct{}, len(query.Keys))
		for _, key := range query.Keys {
			keys[key] = struct{}{}
		}
	}

	var rows []HistoryRow
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		record, err := cursor.Next()
		if errors.Is(err, io.EOF) {
			return rows, nil
		}
		if err != nil {
			return nil, err
		}
		history := record.GetHistory()
		if history == nil {
			continue
		}

		step := historyStep(history)
		if (query.MinStep != nil && step < *query.MinStep) ||
			(query.MaxStep != nil && step > *query.MaxStep) {
			continue
		}

		row := HistoryRow{Step: step}
		for _, item := range history.GetItem() {
			key := historyItemKey(item)
			if _, wanted := keys[key]; keys != nil && !wanted {
				continue
			}
			row.Items = append(row.Items, HistoryItem{Key: key, ValueJSON: item.GetValueJson()})
		}
		if len(row.Items) == 0 {
			continue
		}

		rows = append(rows, row)
		if query.Last > 0 && len(rows) > query.Last {
			rows = rows[1:]
		}
	}
}
