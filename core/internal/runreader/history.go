package runreader

import (
	"context"
	"errors"
	"io"
	"runtime"
	"sort"
	"sync"

	"google.golang.org/protobuf/proto"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// indexStride is the number of history records between index entries.
const indexStride = 100

// decodeBatchBytes is how many bytes of records a worker decodes at a time.
const decodeBatchBytes = 1 << 20

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
	return scan.readForward(query.Limit)
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

// readForward reads from the cursor to the end of the file, a step past
// MaxStep, or limit matching rows (when positive), decoding records on
// every CPU. Records are read in byte-bounded batches, each decoded into
// one chunk, so a page's chunks are the batches its rows came from.
func (s *historyScan) readForward(limit int) (HistoryPage, error) {
	var page HistoryPage
	workers := min(runtime.GOMAXPROCS(0), 8)
	rows := 0
	for {
		// A record holds at most one row, so a page short of its limit
		// needs at most that many more records this round.
		wanted := 0
		if limit > 0 {
			wanted = limit - rows
		}
		batches := make([]batch, 0, workers)
		atEnd := false
		for len(batches) < workers && !atEnd && (limit == 0 || wanted > 0) {
			var b batch
			var err error
			b, atEnd, err = s.readBatch(wanted)
			if err != nil {
				return HistoryPage{}, err
			}
			if len(b.ends) > 0 {
				batches = append(batches, b)
				wanted -= len(b.ends)
			}
		}

		results := make([]decoded, len(batches))
		var wg sync.WaitGroup
		for i := range batches {
			wg.Add(1)
			go func() {
				defer wg.Done()
				results[i] = s.decodeBatch(batches[i])
			}()
		}
		wg.Wait()

		for _, res := range results {
			if limit > 0 && rows == limit {
				page.NextOffset = res.start
				return page, nil
			}
			if res.chunk.Rows > 0 {
				if limit > 0 && rows+res.chunk.Rows > limit {
					keep := limit - rows
					page.NextOffset = res.rowOffsets[keep]
					res.chunk.truncate(keep)
					page.Chunks = append(page.Chunks, res.chunk)
					return page, nil
				}
				page.Chunks = append(page.Chunks, res.chunk)
				rows += res.chunk.Rows
			}
			if res.stopped {
				return page, nil
			}
		}
		if atEnd {
			return page, nil
		}
		if limit > 0 && rows == limit {
			page.NextOffset = s.cursor.Offset()
			return page, nil
		}
	}
}

// batch is a run of consecutive records' bytes, back to back in data and
// ending at ends, with the file offset of each.
type batch struct {
	data    []byte
	ends    []int
	offsets []int64
}

// readBatch reads records until the batch holds decodeBatchBytes, or
// maxRecords records when positive, or the file ends, reporting the latter.
func (s *historyScan) readBatch(maxRecords int) (batch, bool, error) {
	var b batch
	for len(b.data) < decodeBatchBytes && (maxRecords <= 0 || len(b.ends) < maxRecords) {
		if err := s.ctx.Err(); err != nil {
			return batch{}, false, err
		}
		data, offset, err := s.cursor.NextRaw(b.data)
		if errors.Is(err, io.EOF) {
			return b, true, nil
		}
		if err != nil {
			return batch{}, false, err
		}
		b.data = data
		b.ends = append(b.ends, len(data))
		b.offsets = append(b.offsets, offset)
	}
	return b, false, nil
}

// decoded is a batch's matching rows.
type decoded struct {
	chunk *Chunk
	// start is the offset of the batch's first record; rowOffsets holds the
	// offset of each row's record, so a page cut short can say where the
	// next one starts.
	start      int64
	rowOffsets []int64
	// stopped is true if a step past MaxStep was seen.
	stopped bool
}

func (s *historyScan) decodeBatch(b batch) decoded {
	res := decoded{chunk: &Chunk{}, start: b.offsets[0]}
	start := 0
	for i, end := range b.ends {
		record := &spb.Record{}
		if err := proto.Unmarshal(b.data[start:end], record); err == nil {
			rows := res.chunk.Rows
			if !s.addRecord(res.chunk, record) {
				res.stopped = true
				break
			}
			if res.chunk.Rows > rows {
				res.rowOffsets = append(res.rowOffsets, b.offsets[i])
			}
		}
		start = end
	}
	res.chunk.finish()
	return res
}

// read decodes matching rows into a chunk until the record at offset end
// (when positive), the end of the file, or a step past MaxStep.
func (s *historyScan) read(end int64) (*Chunk, error) {
	chunk := &Chunk{}
	for {
		if err := s.ctx.Err(); err != nil {
			return nil, err
		}
		if end > 0 && s.cursor.Offset() >= end {
			break
		}
		record, _, err := s.cursor.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, err
		}
		if !s.addRecord(chunk, record) {
			break
		}
	}
	chunk.finish()
	return chunk, nil
}

// addRecord adds the record's row to the chunk if it matches the query. It
// returns false once a step past MaxStep is seen.
func (s *historyScan) addRecord(chunk *Chunk, record *spb.Record) bool {
	if s.query.SystemMetrics {
		if stats := record.GetStats(); stats != nil {
			s.addStatsRow(chunk, stats)
		}
		return true
	}
	history := record.GetHistory()
	if history == nil {
		return true
	}
	step := HistoryStep(history)
	if s.query.MinStep != nil && step < *s.query.MinStep {
		return true
	}
	if s.query.MaxStep != nil && step > *s.query.MaxStep {
		return false
	}
	s.addHistoryRow(chunk, history, step)
	return true
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
		chunk, err := s.read(end)
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
