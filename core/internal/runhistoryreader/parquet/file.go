package parquet

import (
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

// LocalParquetFile opens a parquet file from the local file system
// and creates an arrow reader.
//
// The caller may specify whether to parallelize the reading columns
// of the parquet file.
func LocalParquetFile(
	filepath string,
	parallel bool,
) (*pqarrow.FileReader, error) {
	parquetReader, err := file.OpenParquetFile(filepath, true)
	if err != nil {
		return nil, err
	}

	return pqarrow.NewFileReader(
		parquetReader,
		pqarrow.ArrowReadProperties{Parallel: parallel},
		memory.DefaultAllocator,
	)
}

// RemoteParquetFile provides a pqarrow.FileReader for accessing a parquet file
// that is stored remotely.
func RemoteParquetFile(
	reader parquet.ReaderAtSeeker,
) (*pqarrow.FileReader, error) {
	fileReader, err := file.NewParquetReader(
		reader,
	)
	if err != nil {
		return nil, err
	}

	return pqarrow.NewFileReader(
		fileReader,
		pqarrow.ArrowReadProperties{Parallel: false},
		memory.DefaultAllocator,
	)
}
