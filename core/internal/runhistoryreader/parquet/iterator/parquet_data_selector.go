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

	columnIndices []int
}

func SelectAllColumns(schema *schema.Schema) SelectedColumns {
	indices := make([]int, schema.NumColumns())
	for i := range indices {
		indices[i] = i
	}
	return SelectedColumns{
		selectAll:     true,
		columnIndices: indices,
	}
}

func SelectOnlyColumns(
	keys []string,
	schema *schema.Schema,
) (SelectedColumns, error) {
	requestedColumns := keySet{}
	for _, key := range keys {
		requestedColumns[key] = struct{}{}
	}

	foundColumns := keySet{}

	var indices []int
	for i := 0; i < schema.NumColumns(); i++ {
		col := schema.Column(i)
		if _, ok := requestedColumns[col.ColumnPath()[0]]; ok {
			indices = append(indices, i)
			foundColumns[col.ColumnPath()[0]] = struct{}{}
		}
	}

	// Make sure that selected columns were found.
	for column := range requestedColumns {
		if _, ok := foundColumns[column]; !ok {
			return SelectedColumns{}, fmt.Errorf(
				"column %s selected but not found",
				column,
			)
		}
	}

	return SelectedColumns{
		selectAll:     false,
		columnIndices: indices,
	}, nil
}

func (sc *SelectedColumns) GetColumnIndices() []int {
	return sc.columnIndices
}

type SeletedRowGroups struct {
	selectAll       bool
	rowGroupIndices []int
}

func SelectAllRowGroups(pf *pqarrow.FileReader) SeletedRowGroups {
	indices := make([]int, pf.ParquetReader().NumRowGroups())
	for i := range indices {
		indices[i] = i
	}
	return SeletedRowGroups{
		selectAll:       true,
		rowGroupIndices: indices,
	}
}

func SelectOnlyRowGroups(
	pf *pqarrow.FileReader,
	config IteratorConfig,
) (SeletedRowGroups, error) {
	indices := []int{}

	// filter row groups that are outside of the requested step range
	metadata := pf.ParquetReader().MetaData()
	for i := 0; i < len(metadata.RowGroups); i++ {
		minValue, maxValue, err := getColumnRangeFromStats(
			metadata,
			i,
			config.key,
		)
		if err != nil {
			return SeletedRowGroups{}, err
		}

		if minValue < config.max && maxValue >= config.min {
			indices = append(indices, i)
		}
	}

	return SeletedRowGroups{
		selectAll:       false,
		rowGroupIndices: indices,
	}, nil
}

func (sr *SeletedRowGroups) GetRowGroupIndices() []int {
	return sr.rowGroupIndices
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
