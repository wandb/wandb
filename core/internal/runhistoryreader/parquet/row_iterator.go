package historyparquet

// This file copies most of its logic from how history parquet files
// are read on the backend.
// See: https://github.com/wandb/core/blob/master/services/gorilla/internal/parquet/row_iterator.go

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"slices"
	"time"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/parquet/file"
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

// KVMap is a key-value pair mapping,
// it represents a single metric for a history row.
// Where Key is the metric name and Value is the metric value.
type KVMap struct {
	Key   string
	Value any
}

// KVMapList is a list of KVMaps which represent a single history row.
type KVMapList []KVMap

// RowIterator is the primary interface to iterate over history rows
// for a runs history parquet file.
type RowIterator interface {
	Next() (bool, error)
	Value() KVMapList
	Release()
}

type dummyRowIterator struct{}

func (d *dummyRowIterator) Next() (bool, error) { return false, nil }

func (d *dummyRowIterator) Value() KVMapList { return KVMapList{} }

func (d *dummyRowIterator) Release() {}

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
		minValue, maxValue, err := GetColumnRangeFromStats(pf.MetaData(), i, config.Key)
		if err != nil {
			return nil, err
		}

		if (config.Max == 0 || minValue < config.Max) && (config.Min == math.MaxInt64 || maxValue >= config.Min) {
			indices = append(indices, i)
		}
	}

	return indices, nil
}

//
// // Iterator uses the recordIterator to iterate over the records batches in the given parquet file

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
			current: &dummyRowIterator{},
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
			current: &dummyRowIterator{},
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
		current:      &dummyRowIterator{},
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
	r.current = &dummyRowIterator{}
	return false, nil
}

func (r *Iterator) Value() KVMapList {
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

// recordIterator iterates over the rows in the given arrow.Table
type recordIterator struct {
	record           arrow.RecordBatch
	columns          []keyIteratorPair
	resultCols       []keyIteratorPair
	resultsWhitelist map[string]struct{}

	requireAllValues bool
	indexKey         string
	indexCol         columnIterator
	validIndex       func(columnIterator) bool
	value            KVMapList
}

type RecordIteratorOption func(*recordIterator)

func (r *recordIterator) Apply(opts ...RecordIteratorOption) {
	for _, opt := range opts {
		opt(r)
	}
}

func RecordIteratorWithPage(config IteratorConfig) RecordIteratorOption {
	return func(t *recordIterator) {
		t.indexKey = config.Key
		t.validIndex = func(it columnIterator) bool {
			if it == nil {
				return false
			}
			// cache the type of Value()
			switch it.Value().(type) {
			case int64:
				minStep := int64(config.Min)
				maxStep := int64(config.Max)
				t.validIndex = func(it columnIterator) bool {
					step, ok := it.Value().(int64)
					if !ok {
						return false
					}
					return step >= minStep && step < maxStep
				}
			case float64:
				t.validIndex = func(it columnIterator) bool {
					indexVal, ok := it.Value().(float64)
					if !ok {
						return false
					}

					return indexVal >= config.Min && indexVal < config.Max
				}
			default:
				t.validIndex = func(columnIterator) bool {
					return false
				}
			}
			return t.validIndex(it)
		}
	}
}

func RecordIteratorWithResultCols(columns []string) RecordIteratorOption {
	whitelist := map[string]struct{}{}
	for _, c := range columns {
		whitelist[c] = struct{}{}
	}
	return func(t *recordIterator) {
		if len(columns) == 0 {
			return
		}

		t.resultsWhitelist = whitelist
	}
}

func NewRecordIterator(record arrow.RecordBatch, options ...RecordIteratorOption) (RowIterator, error) {
	record.Retain()
	t := &recordIterator{
		record:           record,
		resultsWhitelist: nil,
		columns:          make([]keyIteratorPair, int(record.NumCols())),
		validIndex: func(columnIterator) bool {
			return true
		},
		indexKey: StepKey,
	}
	t.Apply(options...)

	for i := 0; i < int(record.NumCols()); i++ {
		colName := record.ColumnName(i)
		col := record.Column(i)
		it, err := newColumnIterator(col, columnIteratorConfig{returnRawBinary: false})
		if err != nil {
			return nil, fmt.Errorf("%s > %w", colName, err)
		}
		t.columns[i] = keyIteratorPair{
			Key:      colName,
			Iterator: it,
		}

		if t.indexKey == colName {
			t.indexCol = it
		}
	}

	t.resultCols = t.columns
	if t.resultsWhitelist != nil {
		resultCols := []keyIteratorPair{}
		for _, c := range t.resultCols {
			if _, whitelisted := t.resultsWhitelist[c.Key]; whitelisted {
				resultCols = append(resultCols, c)
			}
		}
		t.resultCols = resultCols
		t.requireAllValues = true
	}

	return t, nil
}

func (t *recordIterator) Next() (bool, error) {
	t.value = nil
	for {
		for _, c := range t.columns {
			if !c.Iterator.Next() {
				return false, nil
			}
		}

		if !t.validIndex(t.indexCol) {
			continue
		}

		if t.requireAllValues {
			allValues := true
			for _, c := range t.resultCols {
				if c.Iterator.Value() == nil {
					allValues = false
				}
			}
			if !allValues {
				continue
			}
		}

		return true, nil
	}
}

func (t *recordIterator) Value() KVMapList {
	if t.value != nil { // cache the value in case we're asked for it multiple times
		return t.value
	}
	t.value = make(KVMapList, len(t.resultCols))
	for i, col := range t.resultCols {
		t.value[i] = KVMap{
			Key:   col.Key,
			Value: col.Iterator.Value(),
		}
	}
	return t.value
}

func (t *recordIterator) Release() {
	t.record.Release()
}

// columnIterator is the interface used to iterate over the values in a single
// column. The values across columns should be merged together to form a single
// row.
type columnIterator interface {
	Next() bool
	Value() any
}

type columnIteratorConfig struct {
	returnRawBinary bool
}

// newColumnIterator returns the concrete struct responsible for iterating over
// a single arrow.Array (values for a single data chunk in a single column).
func newColumnIterator(data arrow.Array, config columnIteratorConfig) (columnIterator, error) {
	switch data.DataType().(type) {
	case *arrow.StructType:
		return newStructIterator(data, config)
	case *arrow.ListType:
		return newListIterator(data, config)
	case *arrow.Int32Type:
		return newScalarIterator(data, int32Accessor), nil
	case *arrow.Int64Type:
		return newScalarIterator(data, int64Accessor), nil
	case *arrow.Uint32Type:
		return newScalarIterator(data, uint32Accessor), nil
	case *arrow.Uint64Type:
		return newScalarIterator(data, uint64Accessor), nil
	case *arrow.Float32Type:
		return newScalarIterator(data, float32Accessor), nil
	case *arrow.Float64Type:
		return newScalarIterator(data, float64Accessor), nil
	case *arrow.StringType:
		return newScalarIterator(data, stringAccessor), nil
	case *arrow.BinaryType:
		if config.returnRawBinary {
			return newScalarIterator(data, rawBinaryAccessor), nil
		}
		return newScalarIterator(data, binaryAccessor), nil
	case *arrow.FixedSizeBinaryType:
		return newScalarIterator(data, fixedBinaryAccessor), nil
	case *arrow.BooleanType:
		return newScalarIterator(data, booleanAccessor), nil
	case *arrow.Time64Type:
		return newScalarIterator(data, time64Accessor), nil
	}
	return nil, fmt.Errorf("unsupported column type: %T", data.DataType)
}

type structIterator struct {
	data   *array.Struct
	offset int
	typ    *arrow.StructType

	children []columnIterator
	config   columnIteratorConfig
}

func newStructIterator(data arrow.Array, config columnIteratorConfig) (*structIterator, error) {
	arr := data.(*array.Struct)
	children := make([]columnIterator, arr.NumField())
	typ := data.DataType().(*arrow.StructType)
	var err error
	for i := 0; i < arr.NumField(); i++ {
		children[i], err = newColumnIterator(arr.Field(i), config)
		if err != nil {
			return nil, fmt.Errorf("%s > %w", typ.Field(i).Name, err)
		}
	}
	return &structIterator{
		data:     arr,
		typ:      typ,
		offset:   -1,
		children: children,
		config:   config,
	}, nil
}

func (s *structIterator) Next() bool {
	s.offset++
	if s.offset >= s.data.Len() {
		return false
	}
	next := false
	for _, c := range s.children {
		if c.Next() {
			next = true
		}
	}
	return next
}

func (s *structIterator) Value() interface{} {
	if s.data.IsNull(s.offset) {
		return nil
	}
	result := map[string]interface{}{}
	for i, c := range s.children {
		v := c.Value()
		if v != nil {
			result[s.typ.Field(i).Name] = c.Value()
		}
	}
	return result
}

type listIterator struct {
	data   *array.List
	offset int
	config columnIteratorConfig
}

func newListIterator(data arrow.Array, config columnIteratorConfig) (*listIterator, error) {
	arr := data.(*array.List)
	_, err := newColumnIterator(arr.ListValues(), config)
	if err != nil {
		return nil, err
	}
	return &listIterator{
		data:   arr,
		offset: -1,
		config: config,
	}, nil
}

func (c *listIterator) Next() bool {
	c.offset++
	return c.offset < c.data.Len()
}

func (c *listIterator) Value() any {
	if c.data.IsNull(c.offset) {
		return nil
	}
	offset := c.data.Offset() + c.offset
	beg := int(c.data.Offsets()[offset])
	end := int(c.data.Offsets()[offset+1])
	if end <= beg {
		return []any{}
	}
	s := array.NewSlice(c.data.ListValues(), int64(beg), int64(end))
	defer s.Release()
	it, err := newColumnIterator(s, c.config)
	if err != nil {
		// we did check for errors in the constructor,
		// so there should not be any errors...
		panic(err)
	}
	values := make([]any, 0, end-beg)
	for it.Next() {
		values = append(values, it.Value())
	}
	return values
}

type accessorFunc func(arrow.Array, int) any

type scalarIterator struct {
	data   arrow.Array
	offset int

	accessor accessorFunc
}

func newScalarIterator(data arrow.Array, accessor accessorFunc) *scalarIterator {
	return &scalarIterator{
		data:   data,
		offset: -1,

		accessor: accessor,
	}
}

func (c *scalarIterator) Next() bool {
	c.offset++
	return c.offset < c.data.Len()
}

func (c *scalarIterator) Value() (value any) {
	defer func() {
		// A panic may occur when the underlying data array is corrupt,
		// e.g. index out of bounds panic even when c.offset < c.data.Len()
		// For now, just catch the panic and return nil to avoid killing the calling process.
		if p := recover(); p != nil {
			// TODO: Bubble up some sort of corruption indicator for observability
			value = nil
		}
	}()
	if c.data.IsNull(c.offset) {
		return nil
	}
	return c.accessor(c.data, c.offset)
}

func int32Accessor(data arrow.Array, offset int) any {
	return data.(*array.Int32).Value(offset)
}

func uint32Accessor(data arrow.Array, offset int) any {
	return data.(*array.Uint32).Value(offset)
}

func int64Accessor(data arrow.Array, offset int) any {
	return data.(*array.Int64).Value(offset)
}

func uint64Accessor(data arrow.Array, offset int) any {
	return data.(*array.Uint64).Value(offset)
}

func float32Accessor(data arrow.Array, offset int) any {
	return data.(*array.Float32).Value(offset)
}

func float64Accessor(data arrow.Array, offset int) any {
	value := data.(*array.Float64).Value(offset)
	// Check for special float values - can't use switch due to NaN comparison
	if math.IsNaN(value) {
		return "NaN"
	}
	if math.IsInf(value, -1) {
		return "-Infinity"
	}
	if math.IsInf(value, +1) {
		return "Infinity"
	}
	return value
}

func stringAccessor(data arrow.Array, offset int) any {
	return data.(*array.String).Value(offset)
}

func binaryAccessor(data arrow.Array, offset int) any {
	raw := data.(*array.Binary).Value(offset)
	var value []byte
	if err := json.Unmarshal(raw, &value); err != nil {
		return raw
	}
	return value
}

func rawBinaryAccessor(data arrow.Array, offset int) any {
	return data.(*array.Binary).Value(offset)
}

func fixedBinaryAccessor(data arrow.Array, offset int) any {
	return data.(*array.FixedSizeBinary).Value(offset)
}

func time64Accessor(data arrow.Array, offset int) any {
	ts := int64(data.(*array.Time64).Value(offset))
	return time.Unix(ts/1e9, ts%1e9)
}

func booleanAccessor(data arrow.Array, offset int) any {
	return data.(*array.Boolean).Value(offset)
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
