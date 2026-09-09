package runreader

import (
	"context"
	"errors"
	"io"
	"sort"
	"strconv"

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
	// Rows holds one JSON object per row, each ending in a newline. Nested
	// keys are joined with dots and system metrics are prefixed with
	// "system.", as the W&B UI names them; values are as logged.
	Rows []byte

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
	rows, _, next, err := scan.read(nil, query.Limit, 0)
	return HistoryPage{Rows: rows, NextOffset: next}, err
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

// read appends matching rows to dst until the record at offset end (when
// positive), the end of the file, a step past MaxStep, or limit rows (when
// positive). It returns the rows, how many were appended, and the offset to
// continue from, which is 0 once the scan is complete.
func (s *historyScan) read(dst []byte, limit int, end int64) ([]byte, int, int64, error) {
	count := 0
	for {
		if err := s.ctx.Err(); err != nil {
			return dst, count, 0, err
		}
		if limit > 0 && count == limit || end > 0 && s.cursor.Offset() >= end {
			return dst, count, s.cursor.Offset(), nil
		}
		record, _, err := s.cursor.Next()
		if errors.Is(err, io.EOF) {
			return dst, count, 0, nil
		}
		if err != nil {
			return dst, count, 0, err
		}
		var ok bool
		if s.query.SystemMetrics {
			stats := record.GetStats()
			if stats == nil {
				continue
			}
			dst, ok = appendStatsRow(dst, stats, s.keys)
		} else {
			history := record.GetHistory()
			if history == nil {
				continue
			}
			step := HistoryStep(history)
			if s.query.MinStep != nil && step < *s.query.MinStep {
				continue
			}
			if s.query.MaxStep != nil && step > *s.query.MaxStep {
				return dst, count, 0, nil
			}
			dst, ok = appendRow(dst, history, s.keys)
		}
		if ok {
			count++
		}
	}
}

// last returns the last query.Last matching rows by scanning the file
// backwards one index granule at a time.
func (s *historyScan) last(index []indexEntry) (HistoryPage, error) {
	var rows []byte
	count := 0
	for g := len(index) - 1; g >= 0 && count < s.query.Last; g-- {
		if err := s.cursor.SeekRecord(index[g].offset); err != nil {
			return HistoryPage{}, err
		}
		var end int64
		if g+1 < len(index) {
			end = index[g+1].offset
		}
		granule, n, _, err := s.read(nil, 0, end)
		if err != nil {
			return HistoryPage{}, err
		}
		rows = append(granule, rows...)
		count += n
		if s.query.MinStep != nil && index[g].step < *s.query.MinStep {
			break
		}
	}
	for ; count > s.query.Last; count-- {
		rows = rows[indexByteAfterNewline(rows):]
	}
	return HistoryPage{Rows: rows}, nil
}

func indexByteAfterNewline(rows []byte) int {
	for i, c := range rows {
		if c == '\n' {
			return i + 1
		}
	}
	return len(rows)
}

// appendRow appends the record's items as a JSON object line, with _step
// from the record's step when it has one. When keys is non-nil, only those
// keys and _step are included, and the row is skipped (dst is returned
// unchanged with false) if none of the keys is present.
func appendRow(dst []byte, history *spb.HistoryRecord, keys map[string]struct{}) ([]byte, bool) {
	start := len(dst)
	dst = append(dst, '{')
	if history.Step != nil {
		dst = append(dst, `"_step":`...)
		dst = strconv.AppendInt(dst, history.Step.GetNum(), 10)
	}
	matched := keys == nil
	for _, item := range history.GetItem() {
		key := HistoryItemKey(item)
		if key == "_step" && history.Step != nil {
			continue
		}
		if keys != nil {
			if _, wanted := keys[key]; wanted {
				matched = true
			} else if key != "_step" {
				continue
			}
		}
		dst = appendField(dst, start, key, item.GetValueJson())
	}
	if !matched {
		return dst[:start], false
	}
	return append(dst, '}', '\n'), true
}

// appendStatsRow appends the record's metrics as a JSON object line with
// _timestamp in seconds and each metric under "system.". When keys is
// non-nil, only those metrics are included, and the row is skipped (dst is
// returned unchanged with false) if none of them is present.
func appendStatsRow(dst []byte, stats *spb.StatsRecord, keys map[string]struct{}) ([]byte, bool) {
	start := len(dst)
	dst = append(dst, '{')
	if ts := stats.GetTimestamp(); ts != nil {
		dst = append(dst, `"_timestamp":`...)
		dst = strconv.AppendFloat(dst,
			float64(ts.GetSeconds())+float64(ts.GetNanos())/1e9, 'f', -1, 64)
	}
	matched := keys == nil
	for _, item := range stats.GetItem() {
		key := "system." + item.GetKey()
		if keys != nil {
			if _, wanted := keys[key]; !wanted {
				continue
			}
			matched = true
		}
		dst = appendField(dst, start, key, item.GetValueJson())
	}
	if !matched {
		return dst[:start], false
	}
	return append(dst, '}', '\n'), true
}

// appendField appends a field to the JSON object that begins at start,
// writing null for an empty value.
func appendField(dst []byte, start int, key, value string) []byte {
	if len(dst) > start+1 {
		dst = append(dst, ',')
	}
	dst = appendJSONString(dst, key)
	dst = append(dst, ':')
	if value == "" {
		return append(dst, "null"...)
	}
	return append(dst, value...)
}

const hexDigits = "0123456789abcdef"

// appendJSONString appends s as a quoted JSON string.
func appendJSONString(dst []byte, s string) []byte {
	dst = append(dst, '"')
	for i := 0; i < len(s); i++ {
		switch c := s[i]; {
		case c == '"' || c == '\\':
			dst = append(dst, '\\', c)
		case c < 0x20:
			dst = append(dst, '\\', 'u', '0', '0', hexDigits[c>>4], hexDigits[c&0xf])
		default:
			dst = append(dst, c)
		}
	}
	return append(dst, '"')
}
