package parquet

// This file copies most of its logic from how history parquet files
// are read on the backend.
// See: https://github.com/wandb/core/blob/master/services/gorilla/internal/parquet/partition_reader.go

import (
	"context"
	"iter"

	"github.com/apache/arrow-go/v18/parquet/metadata"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/iterator"
)

// ParquetPartitionReader is a reader for a single run history parquet file.
// Run history may be partitioned into multiple parquet files.
// It uses RowIterator's to iterate over the rows in the parquet file.
// RowIterators are composed into various iterators types,
// to handle reading parquet files by chunks.
type ParquetPartitionReader struct {
	ctx context.Context

	// file is the underlying parquet file reader.
	file *pqarrow.FileReader

	// dataReady is used to signal that the iterator is ready to be used.
	dataReady chan struct{}

	// iter is used to iterate over all rows in the parquet file.
	iter iterator.RowIterator

	// iterCreationError is the error that occurred while creating the iter.
	// if no error occurred, it is nil.
	iterCreationError error
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
	p.iter = it
	return p.iter.Next()
}

// Value returns the value of the current row in the row iterator.
func (p *ParquetPartitionReader) Value() iterator.KeyValueList {
	return p.iter.Value()
}

// Release releases the resources used by the reader.
func (p *ParquetPartitionReader) Release() {
	if p.iter != nil {
		p.iter.Release()
	}
}

// All returns an iterator over the values of the parquet partition
func (p *ParquetPartitionReader) All() iter.Seq2[iterator.KeyValueList, error] {
	return func(yield func(iterator.KeyValueList, error) bool) {
		for {
			hasNext, err := p.Next()
			if err != nil {
				yield(iterator.KeyValueList{}, err)
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

func (p *ParquetPartitionReader) iterator() (iterator.RowIterator, error) {
	select {
	case <-p.ctx.Done():
		return nil, p.ctx.Err()
	case <-p.dataReady:
		return p.iter, p.iterCreationError
	}
}

// NewParquetPartitionReader creates a new parquet partition reader for the given file.
// keys argument is the list of columns to include in the row iterator.
// opt argument is used to filter out rows based on a key and range of values.
func NewParquetPartitionReader(
	ctx context.Context,
	file *pqarrow.FileReader,
	keys []string,
	opt iterator.RowIteratorOption,
) *ParquetPartitionReader {
	makeIterator := func(partition *ParquetPartitionReader) (iterator.RowIterator, error) {
		return iterator.NewRowIterator(ctx, file, keys, opt)
	}

	return newParquetPartitionReader(ctx, file, makeIterator)
}

func newParquetPartitionReader(
	ctx context.Context,
	file *pqarrow.FileReader,
	makeIterator func(*ParquetPartitionReader) (iterator.RowIterator, error),
) *ParquetPartitionReader {
	partition := &ParquetPartitionReader{
		ctx:       ctx,
		file:      file,
		dataReady: make(chan struct{}),
	}

	go func() {
		defer close(partition.dataReady)
		partition.iter, partition.iterCreationError = makeIterator(partition)
	}()

	return partition
}
