package iterator

// This file copies most of its logic from how history parquet files
// are read on the backend.
// See: https://github.com/wandb/core/blob/master/services/gorilla/internal/parquet/row_iterator.go

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"math"
	"slices"

	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/metadata"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/apache/arrow-go/v18/parquet/schema"
)

const (
	StepKey      = "_step"
	TimestampKey = "_timestamp"
)

type HistoryPageParams struct {
	MinStep int64 // Inclusive lower bound of _step
	MaxStep int64 // Exclusive upper bound of _step
	Samples int64 // Number of requested samples
	MaxSize int64 // Maximum number of bytes we try to read (in some impls)
}

type EventsPageParams struct {
	MinTimestamp float64
	MaxTimestamp float64
}

// KeyValuePair is a key-value pair mapping,
// it represents a single metric for a history row.
// Where Key is the metric name and Value is the metric value.
type KeyValuePair struct {
	Key   string
	Value any
}

// KeyValueList is a list of KeyValuePairs which represent a single history row.
type KeyValueList []KeyValuePair

// RowIterator is the primary interface to iterate over history rows
// for a runs history parquet file.
type RowIterator interface {
	Next() (bool, error)
	Value() KeyValueList
	Release()
}

func selectColumns(schema *schema.Schema, columns []string) ([]int, error) {
	if len(columns) == 0 {
		indices := make([]int, schema.NumColumns())
		for i := 0; i < len(indices); i++ {
			indices[i] = i
		}
		return indices, nil
	}

	foundMap := map[string]struct{}{}

	var indices []int
	for i := 0; i < schema.NumColumns(); i++ {
		col := schema.Column(i)
		for _, selected := range columns {
			if col.ColumnPath()[0] == selected {
				indices = append(indices, i)
				foundMap[selected] = struct{}{}
			}
		}
	}

	// Make sure that selected columns were found.
	for _, selected := range columns {
		if _, ok := foundMap[selected]; !ok {
			return nil, fmt.Errorf("column %s selected but not found", selected)
		}
	}

	return indices, nil
}

func selectRowGroups(pf *file.Reader, config IteratorConfig) ([]int, error) {
	indices := []int{}

	// filter row groups that are outside of the requested step range
	metadata := pf.MetaData()
	for i := 0; i < len(metadata.RowGroups); i++ {
		minValue, maxValue, err := getColumnRangeFromStats(pf.MetaData(), i, config.Key)
		if err != nil {
			return nil, err
		}

		if (config.Max == 0 || minValue < config.Max) && (config.Min == math.MaxInt64 || maxValue >= config.Min) {
			indices = append(indices, i)
		}
	}

	return indices, nil
}

// Iterator uses recordIterator
// to iterate over the records batches in the given parquet file
type Iterator struct {
	ctx    context.Context
	reader *pqarrow.FileReader
	keys   []string
	config IteratorConfig

	needPage        bool
	rowGroupIndices []int

	recordReader pqarrow.RecordReader
	current      RowIterator
}

type IteratorConfig struct {
	Key string
	Min float64
	Max float64
}

func (c *IteratorConfig) Apply(opts ...RowIteratorOption) {
	for _, opt := range opts {
		if opt == nil {
			continue
		}
		opt(c)
	}
}

type RowIteratorOption func(*IteratorConfig)

func WithHistoryPageRange(page HistoryPageParams) RowIteratorOption {
	return func(c *IteratorConfig) {
		c.Key = StepKey
		c.Min = float64(page.MinStep)
		c.Max = float64(page.MaxStep)
	}
}

func WithEventsPageRange(page EventsPageParams) RowIteratorOption {
	return func(c *IteratorConfig) {
		c.Key = TimestampKey
		c.Min = page.MinTimestamp
		c.Max = page.MaxTimestamp
	}
}

func NewRowIterator(
	ctx context.Context,
	reader *pqarrow.FileReader,
	keys []string,
	opt RowIteratorOption, // We require atleast one of the history page range or events page range to be passed in
) (*Iterator, error) {
	config := IteratorConfig{
		Key: StepKey, // TODO: make this configurable
		Min: float64(0),
		Max: math.MaxInt64,
	}
	config.Apply(opt)
	if config.Max == 0 {
		// In case the caller code accidentally passes in a config but only explicitly sets the Min,
		// in which case Max defaults to 0. In that sencario, if we don't do this, in Next() we'll skip all rows
		config.Max = math.MaxInt64
	}

	// Check if this file is empty
	if reader.ParquetReader().NumRows() == 0 {
		rgi := &Iterator{
			current: &NoopRowIterator{},
		}
		return rgi, nil
	}

	if reader.Props.BatchSize <= 0 {
		if len(keys) > 0 {
			reader.Props.BatchSize = int64(batchSizeForSchemaSize(len(keys)))
		} else {
			numColumns := reader.ParquetReader().MetaData().Schema.NumColumns()
			reader.Props.BatchSize = int64(batchSizeForSchemaSize(numColumns))
		}
	}

	selectedColumns := keys
	var rowGroupIndices []int

	// if we need pagination, then there's a bit more work to do
	needPage := config.Min != 0 || config.Max != math.MaxInt64
	if needPage {
		// check what row groups are valid
		var err error
		rowGroupIndices, err = selectRowGroups(reader.ParquetReader(), config)
		if err != nil {
			return nil, err
		}

		// and include the index key if we're not selecting it
		if len(keys) > 0 {
			if !slices.Contains(keys, config.Key) {
				selectedColumns = append(selectedColumns, config.Key)
			}
		}
	} else {
		rowGroupIndices = make([]int, reader.ParquetReader().NumRowGroups())
		for i := range rowGroupIndices {
			rowGroupIndices[i] = i
		}
	}

	columnIndices, err := selectColumns(reader.ParquetReader().MetaData().Schema, selectedColumns)
	if err != nil {
		rgi := &Iterator{
			current: &NoopRowIterator{},
		}
		return rgi, nil
	}

	recordReader, err := reader.GetRecordReader(ctx, columnIndices, rowGroupIndices)
	if err != nil {
		return nil, fmt.Errorf("%w", err)
	}

	rgi := &Iterator{
		ctx:    ctx,
		reader: reader,
		// TODO maybe set keys to selectedColumns so we include the index key in the result
		// used to filter in Next below, see note there
		keys:   keys,
		config: config,

		needPage:        needPage,
		rowGroupIndices: rowGroupIndices,

		recordReader: recordReader,
		current:      &NoopRowIterator{},
	}

	return rgi, nil
}

func (r *Iterator) Next() (bool, error) {
	next, err := r.current.Next()
	if next || err != nil {
		return next, err
	}

	if r.recordReader != nil && r.recordReader.Next() {
		// NOTE: in NewRowIterator, we should maybe be setting keys to selectedColumns so we include the index key in the result
		opts := []RecordIteratorOption{
			RecordIteratorWithResultCols(r.keys),
		}
		if r.needPage {
			opts = append(opts, RecordIteratorWithPage(r.config))
		}
		r.current.Release()
		r.current, err = NewRecordIterator(
			r.recordReader.RecordBatch(),
			opts...,
		)
		if err != nil {
			return false, err
		}
		return r.Next()
	}

	r.current.Release()
	r.current = &NoopRowIterator{}
	return false, nil
}

func (r *Iterator) Value() KeyValueList {
	return r.current.Value()
}

func (r *Iterator) Release() {
	r.current.Release()
	if r.recordReader != nil {
		r.recordReader.Release()
	}
}

func (r *Iterator) RowGroupIndices() []int {
	return r.rowGroupIndices
}

type keyIteratorPair struct {
	Key      string
	Iterator columnIterator
}

func batchSizeForSchemaSize(numColumns int) int {
	// builder.Reserve reserves an amount of memory for N rows, which is more efficient since the
	// allocations are batched and the values are contiguous (less work for gc).
	// But remember that how big a row is is determined by the number (and type) of columns. So we
	// use a very unscientific formula. Some example breakpoints:
	// At <=100 columns, reserve 10k rows (max reservation)
	// At 1k columns, reserve 1k rows
	// At >=10k columns, reserve 100 rows
	if numColumns < 1 {
		return 10000
	}

	return int(math.Max(math.Min(10000, float64(1000000/numColumns)), 100))
}

// getColumnRangeFromStats returns the range of values
// for the given column index in the given row group.
func getColumnRangeFromStats(
	meta *metadata.FileMetaData,
	rowGroupIndex int,
	columnName string,
) (minValue float64, maxValue float64, err error) {
	minValue = -1
	maxValue = -1
	if rowGroupIndex < 0 || rowGroupIndex >= len(meta.RowGroups) {
		err = fmt.Errorf("%s row group not found in parquet file", columnName)
		return
	}

	// *parquet.RowGroup is an internal package to arrow, so we cannot reference it directly...
	rowGroup := meta.RowGroups[rowGroupIndex]
	colIndex := meta.Schema.ColumnIndexByName(columnName)
	if colIndex < 0 || colIndex >= len(rowGroup.Columns) {
		err = fmt.Errorf("%s column not found in parquet file", columnName)
		return
	}

	statistics := rowGroup.Columns[colIndex].MetaData.Statistics
	if statistics == nil {
		err = fmt.Errorf("missing statistics for %s column chunk", columnName)
		return
	}

	switch t := meta.Schema.Column(colIndex).PhysicalType(); t {
	case parquet.Types.Int64:
		imin, err := decodeValue[int64](statistics.MinValue)
		if err != nil {
			return -1, -1, fmt.Errorf("%w", err)
		}
		imax, err := decodeValue[int64](statistics.MaxValue)
		if err != nil {
			return -1, -1, fmt.Errorf("%w", err)
		}
		minValue, maxValue = float64(imin), float64(imax)
	case parquet.Types.Double:
		minValue, err = decodeValue[float64](statistics.MinValue)
		if err != nil {
			return -1, -1, fmt.Errorf("%w", err)
		}
		maxValue, err = decodeValue[float64](statistics.MaxValue)
		if err != nil {
			return -1, -1, fmt.Errorf("%w", err)
		}
	default:
		return -1, -1, fmt.Errorf("unsupported type %v", t)
	}
	return
}

func decodeValue[T any](data []byte) (T, error) {
	var v T
	err := binary.Read(bytes.NewReader(data), binary.LittleEndian, &v)
	return v, err
}
