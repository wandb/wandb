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

// SelectedColumns contains the information about the columns
// that were requested to be read from the parquet file.
type SelectedColumns struct {
	selectAll bool
	schema    *schema.Schema

	requestedColumns map[string]struct{}
	columnIndices    []int
}

// SelectColumns returns a SelectedColumns struct.
//
// When no keys are provided, then all columns are selected.
// When at least one key is provided,
// then only the columns for those keys are selected.
func SelectColumns(
	indexKey string,
	keys []string,
	schema *schema.Schema,
	selectAll bool,
) (*SelectedColumns, error) {
	var requestedColumns map[string]struct{}
	var columnIndices []int

	if len(keys) == 0 && !selectAll {
		return nil, fmt.Errorf("no keys provided and selectAll is false")
	}

	if selectAll {
		requestedColumns = make(map[string]struct{}, schema.NumColumns())
		columnIndices = make([]int, 0, schema.NumColumns())
		for i := 0; i < schema.NumColumns(); i++ {
			col := schema.Column(i)
			requestedColumns[col.ColumnPath()[0]] = struct{}{}
			columnIndices = append(columnIndices, i)
		}
	} else {
		requestedColumns = make(map[string]struct{}, len(keys)+1)
		columnIndices = make([]int, 0, len(keys)+1)

		requestedColumns[indexKey] = struct{}{}
		columnIndices = append(columnIndices, schema.ColumnIndexByName(indexKey))

		for _, key := range keys {
			colIndex := schema.ColumnIndexByName(key)
			if colIndex < 0 {
				return nil, fmt.Errorf(
					"column %s selected but not found",
					key,
				)
			}

			// Only add the column if it hasn't been seen yet.
			if _, ok := requestedColumns[key]; !ok {
				columnIndices = append(columnIndices, colIndex)
				requestedColumns[key] = struct{}{}
			}
		}
	}

	return &SelectedColumns{
		schema:           schema,
		requestedColumns: requestedColumns,
		selectAll:        selectAll,
		columnIndices:    columnIndices,
	}, nil
}

// GetColumnIndices returns the indices of the columns
// in the parquet file corresponding to the requested columns.
func (sc *SelectedColumns) GetColumnIndices() []int {
	return sc.columnIndices
}

// GetRequestedColumns returns the columns that were requested to be read.
func (sc *SelectedColumns) GetRequestedColumns() map[string]struct{} {
	return sc.requestedColumns
}

// SelectedRowsRange contains the information about which rows
// to read from the parquet file.
type SelectedRowsRange struct {
	parquetFileReader *pqarrow.FileReader
	indexKey          string
	minValue          float64
	maxValue          float64
}

// SelectRowsInRange returns a SelectedRows struct.
func SelectRowsInRange(
	pf *pqarrow.FileReader,
	indexKey string,
	minValue float64,
	maxValue float64,
) *SelectedRowsRange {
	return &SelectedRowsRange{
		parquetFileReader: pf,
		indexKey:          indexKey,
		minValue:          minValue,
		maxValue:          maxValue,
	}
}

func (sr *SelectedRowsRange) GetIndexKey() string {
	return sr.indexKey
}

// GetRowGroupIndices returns the indices of the row groups that should be read.
//
// It does this by checking if the index key value
// is within the min and max value range.
func (sr *SelectedRowsRange) GetRowGroupIndices() ([]int, error) {
	var rowGroupIndices []int

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

	return rowGroupIndices, nil
}

// IsRowGreaterThanMinValue returns whether the requested index column's value
// is greater than the min value for the selected range.
//
// If the current row does not have a value for the index column,
// then it returns false.
func (sr *SelectedRowsRange) IsRowGreaterThanMinValue(rowIndexValue any) bool {
	if rowIndexValue == nil {
		return false
	}

	switch value := rowIndexValue.(type) {
	case int64:
		return value >= int64(sr.minValue)
	case float64:
		return value >= float64(sr.minValue)
	default:
		return false
	}

}

// IsRowLessThanMaxValue returns whether the requested index column's value
// is less than the max value for the selected range.
func (sr *SelectedRowsRange) IsRowLessThanMaxValue(rowIndexValue any) bool {
	if rowIndexValue == nil {
		return false
	}

	switch value := rowIndexValue.(type) {
	case int64:
		return value < int64(sr.maxValue)
	case float64:
		return value < float64(sr.maxValue)
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
