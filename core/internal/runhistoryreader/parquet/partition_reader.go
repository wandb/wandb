package parquet

// This file copies most of its logic from how history parquet files
// are read on the backend.
// See: https://github.com/wandb/core/blob/master/services/gorilla/internal/parquet/partition_reader.go

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"iter"

	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/metadata"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/wandb/parallel"
)

// ParquetPartitionReader is a reader for a single run history parquet file.
// Run history may be partitioned into multiple parquet files.
type ParquetPartitionReader struct {
	ctx       context.Context
	ctxDone   <-chan struct{}
	executor  parallel.Executor
	file      *pqarrow.FileReader
	dataReady chan struct{}
	it        RowIterator
	err       error
}

// Metadata returns the metadata of the underlying parquet partition file.
func (p *ParquetPartitionReader) MetaData() (*metadata.FileMetaData, error) {
	return p.file.ParquetReader().MetaData(), nil
}

// Next advances the reader to the next row in the row iterator.
func (p *ParquetPartitionReader) Next() (bool, error) {
	it, err := p.iterator()
	if err != nil {
		return false, err
	}
	p.it = it
	return p.it.Next()
}

// Value returns the value of the current row in the row iterator.
func (p *ParquetPartitionReader) Value() KVMapList {
	return p.it.Value()
}

// Release releases the resources used by the reader.
func (p *ParquetPartitionReader) Release() {
	if p.it != nil {
		p.it.Release()
	}
}

// All returns an iterator over the values of the parquet partition
func (p *ParquetPartitionReader) All() iter.Seq2[KVMapList, error] {
	return func(yield func(KVMapList, error) bool) {
		for {
			hasNext, err := p.Next()
			if err != nil {
				yield(KVMapList{}, err)
				return
			}
			if !hasNext {
				return
			}

			value := p.Value()
			if !yield(value, nil) {
				return
			}
		}
	}
}

func (p *ParquetPartitionReader) iterator() (RowIterator, error) {
	select {
	case <-p.ctxDone:
		return nil, p.ctx.Err()
	case <-p.dataReady:
		p.executor.Wait()
		return p.it, p.err
	}
}

// NewParquetPartitionReader creates a new parquet partition reader for the given file.
// keys argument is the list of columns to include in the row iterator.
// opt argument is used to filter out rows based on a key and range of values.
func NewParquetPartitionReader(
	ctx context.Context,
	file *pqarrow.FileReader,
	keys []string,
	opt RowIteratorOption,
) *ParquetPartitionReader {
	makeIterator := func(partition *ParquetPartitionReader) (RowIterator, error) {
		return NewRowIterator(ctx, file, keys, opt)
	}

	return newParquetPartitionReader(ctx, file, makeIterator)
}

func newParquetPartitionReader(
	ctx context.Context,
	file *pqarrow.FileReader,
	makeIterator func(*ParquetPartitionReader) (RowIterator, error),
) *ParquetPartitionReader {
	partition := &ParquetPartitionReader{
		ctx:       ctx,
		ctxDone:   ctx.Done(),
		executor:  parallel.Unlimited(ctx),
		file:      file,
		dataReady: make(chan struct{}),
	}

	partition.executor.Go(func(ctx context.Context) {
		defer close(partition.dataReady)
		partition.it, partition.err = makeIterator(partition)
	})

	return partition
}

// GetColumnRangeFromStats returns the range of values
// for the given column index in the given row group.
func GetColumnRangeFromStats(
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
