package runreader

import (
	"context"
	"errors"
	"io"
	"sort"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// indexStride is the number of history records between index entries.
const indexStride = 100

type indexEntry struct {
	step   int64
	offset int64
}

// HistoryQuery selects history rows.
type HistoryQuery struct {
	// Keys restricts each row to these keys, plus _step. Rows with none of
	// the keys are skipped. Empty means all keys.
	Keys []string

	// MinStep and MaxStep bound the rows' steps, inclusive, when non-nil.
	MinStep, MaxStep *int64

	// Last, when positive, returns only the last N matching rows, in a
	// single page.
	Last int

	// Offset continues a scan from a previous page's NextOffset.
	Offset int64

	// Limit, when positive, is the most rows in a page.
	Limit int

	// SystemMetrics selects the run's system metrics, keyed by _timestamp,
	// instead of its history. MinStep and MaxStep then do not apply.
	SystemMetrics bool
}

// HistoryPage is one page of matching rows.
type HistoryPage struct {
	// Chunks hold the page's rows in order, each a run of consecutive rows
	// stored by column. Nested keys are joined with dots and system metrics
	// are prefixed with "system.", as the W&B UI names them.
	Chunks []*Chunk

	// NextOffset is the Offset for the next page, or 0 when the scan is
	// complete.
	NextOffset int64
}

// History scans the transaction log for rows matching the query.
//
// The index built by Update tells the scan where to start; rows appended
// since the last Update are still read, as every scan runs to the end of
// the file.
func (r *Run) History(ctx context.Context, query HistoryQuery) (HistoryPage, error) {
	cursor, err := OpenCursor(r.path, r.logger)
	if err != nil {
		return HistoryPage{}, err
	}
	defer cursor.Close()

	scan := &historyScan{ctx: ctx, cursor: cursor, query: query}
	if len(query.Keys) > 0 {
		scan.keys = make(map[string]struct{}, len(query.Keys))
		for _, key := range query.Keys {
			scan.keys[key] = struct{}{}
		}
	}

	if query.Last > 0 {
		if query.SystemMetrics {
			return scan.last(r.statsIndex)
		}
		return scan.last(r.index)
	}

	start := query.Offset
	if start == 0 && query.MinStep != nil && !query.SystemMetrics {
		start = r.offsetForStep(*query.MinStep)
	}
	if start > 0 {
		if err := cursor.SeekRecord(start); err != nil {
			return HistoryPage{}, err
		}
	}
	chunk, next, err := scan.read(query.Limit, 0)
	if err != nil {
		return HistoryPage{}, err
	}
	page := HistoryPage{NextOffset: next}
	if chunk.Rows > 0 {
		page.Chunks = []*Chunk{chunk}
	}
	return page, nil
}

// offsetForStep returns the offset of the last index entry at or before
// step, or 0 to scan from the start.
func (r *Run) offsetForStep(step int64) int64 {
	i := sort.Search(len(r.index), func(i int) bool { return r.index[i].step > step })
	if i == 0 {
		return 0
	}
	return r.index[i-1].offset
}

type historyScan struct {
	ctx    context.Context
	cursor *Cursor
	query  HistoryQuery
	keys   map[string]struct{}
}

// read decodes matching rows into a chunk until the record at offset end
// (when positive), the end of the file, a step past MaxStep, or limit rows
// (when positive). It returns the chunk and the offset to continue from,
// which is 0 once the scan is complete.
func (s *historyScan) read(limit int, end int64) (*Chunk, int64, error) {
	chunk := &Chunk{}
	for {
		if err := s.ctx.Err(); err != nil {
			return nil, 0, err
		}
		if limit > 0 && chunk.Rows == limit || end > 0 && s.cursor.Offset() >= end {
			chunk.finish()
			return chunk, s.cursor.Offset(), nil
		}
		record, _, err := s.cursor.Next()
		if errors.Is(err, io.EOF) {
			chunk.finish()
			return chunk, 0, nil
		}
		if err != nil {
			return nil, 0, err
		}
		if s.query.SystemMetrics {
			if stats := record.GetStats(); stats != nil {
				s.addStatsRow(chunk, stats)
			}
			continue
		}
		history := record.GetHistory()
		if history == nil {
			continue
		}
		step := HistoryStep(history)
		if s.query.MinStep != nil && step < *s.query.MinStep {
			continue
		}
		if s.query.MaxStep != nil && step > *s.query.MaxStep {
			chunk.finish()
			return chunk, 0, nil
		}
		s.addHistoryRow(chunk, history, step)
	}
}

// addHistoryRow adds the record's items as a row, with _step from the
// record's step when it has one. Under a keys filter only those keys and
// _step are kept, and a row with none of the keys is skipped.
func (s *historyScan) addHistoryRow(chunk *Chunk, history *spb.HistoryRecord, step int64) {
	items := history.GetItem()
	if s.keys != nil && !anyKey(s.keys, items, HistoryItemKey) {
		return
	}
	row := chunk.Rows
	if history.Step != nil {
		chunk.addInt(row, "_step", step)
	}
	for _, item := range items {
		key := HistoryItemKey(item)
		if key == "_step" && history.Step != nil {
			continue
		}
		if _, wanted := s.keys[key]; s.keys != nil && !wanted && key != "_step" {
			continue
		}
		chunk.add(row, key, item.GetValueJson())
	}
	chunk.Rows = row + 1
}

// addStatsRow adds the record's metrics as a row with _timestamp in seconds
// and each metric under "system.". A keys filter works as for history rows.
func (s *historyScan) addStatsRow(chunk *Chunk, stats *spb.StatsRecord) {
	items := stats.GetItem()
	if s.keys != nil && !anyKey(s.keys, items, statsItemKey) {
		return
	}
	row := chunk.Rows
	if ts := stats.GetTimestamp(); ts != nil {
		chunk.addFloat(row, "_timestamp", float64(ts.GetSeconds())+float64(ts.GetNanos())/1e9)
	}
	for _, item := range items {
		key := statsItemKey(item)
		if _, wanted := s.keys[key]; s.keys != nil && !wanted {
			continue
		}
		chunk.add(row, key, item.GetValueJson())
	}
	chunk.Rows = row + 1
}

func anyKey[T any](keys map[string]struct{}, items []T, key func(T) string) bool {
	for _, item := range items {
		if _, ok := keys[key(item)]; ok {
			return true
		}
	}
	return false
}

func statsItemKey(item *spb.StatsItem) string {
	return "system." + item.GetKey()
}

// last returns the last query.Last matching rows by scanning the file
// backwards one index granule at a time.
func (s *historyScan) last(index []indexEntry) (HistoryPage, error) {
	var chunks []*Chunk
	count := 0
	for g := len(index) - 1; g >= 0 && count < s.query.Last; g-- {
		if err := s.cursor.SeekRecord(index[g].offset); err != nil {
			return HistoryPage{}, err
		}
		var end int64
		if g+1 < len(index) {
			end = index[g+1].offset
		}
		chunk, _, err := s.read(0, end)
		if err != nil {
			return HistoryPage{}, err
		}
		if chunk.Rows > 0 {
			chunks = append([]*Chunk{chunk}, chunks...)
			count += chunk.Rows
		}
		if s.query.MinStep != nil && index[g].step < *s.query.MinStep {
			break
		}
	}
	for excess := count - s.query.Last; excess > 0; {
		if chunks[0].Rows <= excess {
			excess -= chunks[0].Rows
			chunks = chunks[1:]
			continue
		}
		chunks[0].dropFront(excess)
		excess = 0
	}
	return HistoryPage{Chunks: chunks}, nil
}
