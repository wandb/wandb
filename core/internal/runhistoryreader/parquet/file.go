package parquet

import (
	"fmt"

	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/metadata"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
)

type ParquetFile struct {
	reader *pqarrow.FileReader
}

// LocalParquetFile opens a parquet file from the local file system
// and creates an arrow reader.
// The caller may specify whether to parallelize the reading columns
// of the parquet file.
func LocalParquetFile(
	filepath string,
	parallel bool,
) (*ParquetFile, error) {
	parquetReader, err := file.OpenParquetFile(filepath, true)
	if err != nil {
		return nil, err
	}

	arrowReader, err := pqarrow.NewFileReader(
		parquetReader,
		pqarrow.ArrowReadProperties{Parallel: parallel},
		memory.DefaultAllocator,
	)
	if err != nil {
		return nil, err
	}

	return &ParquetFile{
		reader: arrowReader,
	}, nil
}

// Reader returns the wrapped Arrow file reader.
// Reader will either return an error or a non-nil reader
func (p *ParquetFile) Reader() (*pqarrow.FileReader, error) {
	if p.reader == nil {
		return nil, fmt.Errorf("failed to open parquet reader")
	}
	return p.reader, nil
}

// Close closes the inner reader if it is open
func (p *ParquetFile) Close() {
	if p.reader != nil {
		_ = p.reader.ParquetReader().Close()
	}
}

// MetaData exposes the parquet file metadata
func (p *ParquetFile) MetaData() (*metadata.FileMetaData, error) {
	reader, err := p.Reader()
	if err != nil {
		fmt.Println("Error getting reader in meta data:")
		return nil, err
	}
	return reader.ParquetReader().MetaData(), nil
}
