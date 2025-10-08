package iterator

import (
	"bytes"
	"encoding/binary"
	"fmt"

	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/metadata"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/apache/arrow-go/v18/parquet/schema"
)

// keySet is a mapping of strings to empty structs
//
// It acts a set of strings for easier lookups.
type keySet map[string]struct{}

type SelectedColumns struct {
	selectAll bool
	schema *schema.Schema

	indexKey string
	requestedColumns keySet
}

func SelectColumns(
	indexKey string,
	keys []string,
	schema *schema.Schema,
) (*SelectedColumns, error) {
	var requestedColumns keySet
	selectAll := false

	// When no keys are provided, then we will return all columns.
	if len(keys) == 0 {
		selectAll = true
		requestedColumns = make(keySet, schema.NumColumns())
		for i := 0; i < schema.NumColumns(); i++ {
			col := schema.Column(i)
			requestedColumns[col.ColumnPath()[0]] = struct{}{}
		}
	} else {
		requestedColumns = make(keySet, len(keys)+1)
		requestedColumns[indexKey] = struct{}{}
		for _, key := range keys {
			requestedColumns[key] = struct{}{}

			colIndex := schema.ColumnIndexByName(key)
			if colIndex < 0 {
				return nil, fmt.Errorf(
					"column %s selected but not found",
					key,
				)
			}
		}
	}

	return &SelectedColumns{
		indexKey: indexKey,
		schema: schema,
		requestedColumns: requestedColumns,
		selectAll: selectAll,
	}, nil
}

func (sc *SelectedColumns) GetColumnIndices() []int {
	var indices []int
	if sc.selectAll {
		indices := make([]int, sc.schema.NumColumns())
		for i := range indices {
			indices[i] = i
		}
	} else {
		indices = make([]int, len(sc.requestedColumns))
		i := 0
		for column := range sc.requestedColumns {
			colIndex := sc.schema.ColumnIndexByName(column)
			indices[i] = colIndex
			i++
		}
	}

	return indices
}

func (sc *SelectedColumns) GetRequestedColumns() keySet {
	return sc.requestedColumns
}

func (sc *SelectedColumns) GetIndexKey() string {
	return sc.indexKey
}

type SelectedRows struct {
	selectAll       bool
	parquetFileReader *pqarrow.FileReader
	indexKey string
	minValue float64
	maxValue float64
}
func SelectRows(
	pf *pqarrow.FileReader,
	indexKey string,
	minValue float64,
	maxValue float64,
	selectAll bool,
) *SelectedRows {
	return &SelectedRows{
		selectAll:       selectAll,
		parquetFileReader: pf,
		indexKey: indexKey,
		minValue: minValue,
		maxValue: maxValue,
	}
}

// GetRowGroupIndices returns the indices of the row groups that should be read.
//
// It does this by checking if the index key value
// is within the min and max value range.
func (sr *SelectedRows) GetRowGroupIndices() ([]int, error) {
	var rowGroupIndices []int

	// If selecting all rows, then return all row groups.
	if sr.selectAll {
		rowGroupIndices = make(
			[]int,
			sr.parquetFileReader.ParquetReader().NumRowGroups(),
		)
		for i := range rowGroupIndices {
			rowGroupIndices[i] = i
		}
	} else {
		// filter row groups that are outside of the requested step range
		metadata := sr.parquetFileReader.ParquetReader().MetaData()
		for i := 0; i < len(metadata.RowGroups); i++ {
			fileMinValue, fileMaxValue, err := getColumnRangeFromStats(
				metadata,
				i,
				sr.indexKey,
			)
			if err != nil {
				return nil, err
			}

			if fileMinValue < sr.maxValue && fileMaxValue >= sr.minValue {
				rowGroupIndices = append(rowGroupIndices, i)
			}
		}
	}

	return rowGroupIndices, nil
}

// ShouldSkipRecordRow checks if the current row within a row group
// should be skipped based on SelectedRows min and max values.
func (sr *SelectedRows) IsRowValid(
	columnIterators map[string]keyIteratorPair,
) bool {
	if sr.selectAll {
		return true
	}

	indexColumnIterator := columnIterators[sr.indexKey].Iterator
	if indexColumnIterator == nil {
		return false
	}

	switch indexColumnIterator.Value().(type) {
	case int64:
		minValue := int64(sr.minValue)
		maxValue := int64(sr.maxValue)
		colValue, ok := indexColumnIterator.Value().(int64)
		if !ok {
			return false
		}
		return colValue >= minValue && colValue < maxValue
	case float64:
		colValue, ok := indexColumnIterator.Value().(float64)
		if !ok {
			return false
		}
		return colValue >= sr.minValue && colValue < sr.maxValue
	default:
		return false
	}
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
			return -1, -1, fmt.Errorf(
				"getColumnRangeFromStats: Error decoding int64 min value: %v",
				err,
			)
		}
		imax, err := decodeValue[int64](statistics.MaxValue)
		if err != nil {
			return -1, -1, fmt.Errorf(
				"getColumnRangeFromStats: Error decoding int64 max value: %v",
				err,
			)
		}
		minValue, maxValue = float64(imin), float64(imax)
	case parquet.Types.Double:
		minValue, err = decodeValue[float64](statistics.MinValue)
		if err != nil {
			return -1, -1, fmt.Errorf(
				"getColumnRangeFromStats: Error decoding double min value: %v",
				err,
			)
		}
		maxValue, err = decodeValue[float64](statistics.MaxValue)
		if err != nil {
			return -1, -1, fmt.Errorf(
				"getColumnRangeFromStats: Error decoding double max value: %v",
				err,
			)
		}
	default:
		return -1, -1, fmt.Errorf(
			"getColumnRangeFromStats: Unsupported type %v",
			t,
		)
	}
	return
}

func decodeValue[T any](data []byte) (T, error) {
	var v T
	err := binary.Read(bytes.NewReader(data), binary.LittleEndian, &v)
	return v, err
}
