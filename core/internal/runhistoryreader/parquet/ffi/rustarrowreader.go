package ffi

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"unsafe"

	"github.com/apache/arrow-go/v18/arrow"
	"github.com/apache/arrow-go/v18/arrow/array"
	"github.com/apache/arrow-go/v18/arrow/ipc"
	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/ebitengine/purego"

	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
)

// RustArrowReader is struct used to read parquet files using a wrapper library around arrow-rs.
//
// Arrow-rs provides faster reads, particularly for metadata reads on a parquet files.
type RustArrowReader struct {
	// readers is a slice of pointers of type ReaderHandle.
	// These pointers are used by the Rust library used to handle reading parquet files.
	//
	// The pointers should be freed by calling the freeReader function on the RustArrowWrapper,
	// when they are no longer needed.
	reader unsafe.Pointer

	// rustArrowWrapper is a interface used to make FFI calls to the Rust library.
	rustArrowWrapper *RustArrowWrapper
}

// RustArrowWrapper is a interface used to make FFI calls to the Rust wrapper library.
type RustArrowWrapper struct {
	// createReader is a Rust FFI to create a parquet reader for a given file path and column names.
	createReader func(
		filePathOrURL *byte,
		columnNames **byte,
		numColumns int,
	) unsafe.Pointer

	// scanStepRange is a Rust FFI to scan the readerPtr for a given range of steps.
	// It takes an out parameter for the result and returns an error string (or null on success)
	// The error string must be freed using freeString when the result is no longer needed
	scanStepRange func(
		readerPtr unsafe.Pointer,
		minStep int64,
		maxStep int64,
		outResult *StepScanResult,
	) *byte

	// freeString is a Rust FFI to free a string allocated by Rust.
	freeString func(s *byte)
	// freeIpcStream is a Rust FFI to free an Arrow IPC stream allocated by Rust.
	freeIpcStream func(bufferPtr unsafe.Pointer)
	// freeReader is a Rust FFI to free a ReaderHandle allocated by Rust.
	freeReader func(readerPtr unsafe.Pointer)
}

// StepScanResult matches the Rust struct StepScanResult
// It is used as a output parameter for the scanStepRange function.
type StepScanResult struct {
	// VecPtr is the pointer to the Rust Vec<u8> that contains the IPC stream
	// This should be freed using freeIpcStream when the result is no longer needed
	VecPtr uintptr
	// DataPtr is the pointer to the actual data in the VecPtr
	DataPtr uintptr
	// DataLen is the length of the data in the DataPtr (in bytes)
	DataLen uint64
	// NumRowsReturned is the number of rows returned in the IPC stream
	NumRowsReturned uint64
}

// NewRustArrowWrapper creates a new RustArrowWrapper.
//
// Its purpose is to link Arrow-rs Rust wrapper library with the Go code,
// and provide FFI functions to the Go code for reading parquet files.
func NewRustArrowWrapper() (*RustArrowWrapper, error) {
	libPath, err := findLibrary()
	if err != nil {
		return nil, err
	}

	rustLib, err := purego.Dlopen(libPath, purego.RTLD_NOW|purego.RTLD_GLOBAL)
	if err != nil {
		return nil, err
	}

	var createReader func(
		filePathOrURL *byte,
		columnNames **byte,
		numColumns int,
	) unsafe.Pointer
	purego.RegisterLibFunc(&createReader, rustLib, "create_reader")
	var freeString func(s *byte)
	purego.RegisterLibFunc(&freeString, rustLib, "free_string")
	var freeIpcStream func(bufferPtr unsafe.Pointer)
	purego.RegisterLibFunc(&freeIpcStream, rustLib, "free_ipc_stream")
	var scanStepRange func(
		readerPtr unsafe.Pointer,
		minStep int64,
		maxStep int64,
		outResult *StepScanResult,
	) *byte
	purego.RegisterLibFunc(&scanStepRange, rustLib, "reader_scan_step_range")
	var freeReader func(readerPtr unsafe.Pointer)
	purego.RegisterLibFunc(&freeReader, rustLib, "free_reader")

	return &RustArrowWrapper{
		createReader:  createReader,
		freeString:    freeString,
		freeIpcStream: freeIpcStream,
		freeReader:    freeReader,
		scanStepRange: scanStepRange,
	}, nil
}

func RustArrowWrapperTester(
	createReader func(
		filePath *byte,
		columnNames **byte,
		numColumns int,
	) unsafe.Pointer,
	scanStepRange func(
		readerPtr unsafe.Pointer,
		minStep int64,
		maxStep int64,
		outResult *StepScanResult,
	) *byte,
) *RustArrowWrapper {
	return &RustArrowWrapper{
		createReader:  createReader,
		scanStepRange: scanStepRange,
		freeString:    func(s *byte) {},
		freeIpcStream: func(bufferPtr unsafe.Pointer) {},
		freeReader:    func(readerPtr unsafe.Pointer) {},
	}
}

// CreateRustReaders creates a new RustReader for a given list of file paths.
// Only the columns names provided will be read from the parquet files.
func CreateRustArrowReader(
	rustArrowWrapper *RustArrowWrapper,
	filePath string,
	columnNames []string,
) (*RustArrowReader, error) {
	// Convert column names to C strings and keep them alive
	// We need to store the byte slices to prevent them from being GC'd
	columnNameBytes := make([][]byte, len(columnNames))
	columnNameBytesPtrs := make([]*byte, len(columnNames))
	for i, columnName := range columnNames {
		columnNameBytes[i] = append([]byte(columnName), 0)
		columnNameBytesPtrs[i] = &columnNameBytes[i][0]
	}

	filePathBytes := append([]byte(filePath), 0)

	var colNamesPtr **byte
	if len(columnNames) > 0 {
		colNamesPtr = &columnNameBytesPtrs[0]
	}

	readerPtr := rustArrowWrapper.createReader(
		&filePathBytes[0],
		colNamesPtr,
		len(columnNames),
	)
	if readerPtr == nil {
		return nil, fmt.Errorf("failed to create reader for file: %s", filePath)
	}

	return &RustArrowReader{
		reader:           readerPtr,
		rustArrowWrapper: rustArrowWrapper,
	}, nil
}

func (r *RustArrowReader) ScanStepRange(
	ctx context.Context,
	minStep int64,
	maxStep int64,
) ([]parquet.KeyValueList, error) {
	var scanResult StepScanResult
	errCStr := r.rustArrowWrapper.scanStepRange(
		r.reader,
		minStep,
		maxStep,
		&scanResult,
	)

	// Check for errors from Rust
	if errCStr != nil {
		errMsg := cByteToGoString(errCStr)
		r.rustArrowWrapper.freeString(errCStr)
		return nil, fmt.Errorf("error scanning step range: %s", errMsg)
	}

	// Create an Arrow IPC reader from the buffer
	// Note: The pointers come from Rust FFI
	// the lifetime of which is managed by us, via freeIpcStream
	//
	// We need to convert uintptr to unsafe.Pointer here for FFI interop.
	// This is safe because:
	// 1. The pointer is owned by Rust and kept alive until freeIpcStream is called
	// 2. We call freeIpcStream in the defer to ensure cleanup
	// 3. The data is not moved by Go's GC (it's Rust-owned memory)
	dataPtr := scanResult.DataPtr
	vecPtr := scanResult.VecPtr
	bufferBytes := unsafe.Slice(
		//nolint:govet // pointer memory is managed in the rust wrapper library
		(*byte)(unsafe.Pointer(dataPtr)),
		scanResult.DataLen,
	)
	bufferReader := bytes.NewReader(bufferBytes)
	ipcReader, err := ipc.NewReader(bufferReader, ipc.WithAllocator(memory.DefaultAllocator))
	if err != nil {
		return nil, fmt.Errorf("failed to create IPC reader: %w", err)
	}
	defer func() {
		ipcReader.Release()
		//nolint:govet // pointer memory is managed in the rust wrapper library
		r.rustArrowWrapper.freeIpcStream(unsafe.Pointer(vecPtr))
	}()

	resultsForReader, err := readIPCReaderRecords(ipcReader)
	if err != nil {
		return nil, fmt.Errorf("failed to read IPC reader records: %w", err)
	}

	return resultsForReader, nil
}

// Release frees the resources allocated by the RustReader.
// It should be called only once when the RustReader is no longer needed.
func (r *RustArrowReader) Release() {
	if r.reader != nil {
		r.rustArrowWrapper.freeReader(r.reader)
	}
}

func readIPCReaderRecords(
	ipcReader *ipc.Reader,
) ([]parquet.KeyValueList, error) {
	results := []parquet.KeyValueList{}
	for ipcReader.Next() {
		record := ipcReader.RecordBatch()

		// Convert each row in the record to a KeyValueList
		for rowIdx := 0; rowIdx < int(record.NumRows()); rowIdx++ {
			kvList := make(parquet.KeyValueList, 0, int(record.NumCols()))

			// Iterate through each column
			for colIdx := 0; colIdx < int(record.NumCols()); colIdx++ {
				column := record.Column(colIdx)
				field := record.Schema().Field(colIdx)

				// Extract the value at this row
				value, err := extractArrowValue(column, rowIdx)
				if err != nil {
					return nil, fmt.Errorf(
						"failed to extract value at row %d, col %d: %w",
						rowIdx,
						colIdx,
						err,
					)
				}

				kvList = append(kvList, parquet.KeyValuePair{
					Key:   field.Name,
					Value: value,
				})
			}

			results = append(results, kvList)
		}
	}

	return results, nil
}

func extractListValueAtIndex(arr *array.List, idx int) (any, error) {
	start, end := arr.ValueOffsets(idx)
	values := make([]any, 0, end-start)
	for i := start; i < end; i++ {
		value, err := extractArrowValue(arr.ListValues(), int(i))
		if err != nil {
			return nil, err
		}
		values = append(values, value)
	}
	return values, nil
}

// extractArrowValue extracts a value from an Arrow array at a specific index
func extractArrowValue(arr arrow.Array, idx int) (any, error) {
	if arr.IsNull(idx) {
		return nil, nil
	}

	switch arr := arr.(type) {
	case *array.Int64:
		return arr.Value(idx), nil
	case *array.Int32:
		return int64(arr.Value(idx)), nil
	case *array.Int16:
		return int64(arr.Value(idx)), nil
	case *array.Int8:
		return int64(arr.Value(idx)), nil
	case *array.Uint64:
		return arr.Value(idx), nil
	case *array.Uint32:
		return int64(arr.Value(idx)), nil
	case *array.Uint16:
		return int64(arr.Value(idx)), nil
	case *array.Uint8:
		return int64(arr.Value(idx)), nil
	case *array.Float64:
		return arr.Value(idx), nil
	case *array.Float32:
		return float64(arr.Value(idx)), nil
	case *array.String:
		return arr.Value(idx), nil
	case *array.Binary:
		return []byte(arr.Value(idx)), nil
	case *array.Boolean:
		return arr.Value(idx), nil
	case *array.Struct:
		return nil, fmt.Errorf("structs are not supported")
	case *array.List:
		return extractListValueAtIndex(arr, idx)
	default:
		return nil, fmt.Errorf("unsupported arrow type: %s", arr.DataType())
	}
}

// cByteToGoString converts a null-terminated C string to a Go string
func cByteToGoString(cStr *byte) string {
	if cStr == nil {
		return ""
	}

	var length int
	for {
		ptr := (*byte)(unsafe.Add(unsafe.Pointer(cStr), length))
		if *ptr == 0 {
			break
		}
		length++
	}

	return string(unsafe.Slice(cStr, length))
}

// findLibrary searches for the Parquet rust reader wrapper library.
func findLibrary() (string, error) {
	libName := "librust_parquet_ffi.dylib"
	switch runtime.GOOS {
	case "linux":
		libName = "librust_parquet_ffi.so"
	case "windows":
		libName = "rust_parquet_ffi.dll"
	}

	if exePath, err := os.Executable(); err == nil {
		wheelPath := filepath.Join(filepath.Dir(exePath), "..", "..", "wandb", "bin", libName)
		if _, err := os.Stat(wheelPath); err == nil {
			return wheelPath, nil
		}
	}

	return "", fmt.Errorf("could not find library %s in any expected location", libName)
}
