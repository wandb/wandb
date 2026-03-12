package ffi

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"unsafe"

	"github.com/ebitengine/purego"

	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet"
)

var ErrOffsetOutOfBounds = errors.New("offset out of bounds")

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
	// freeBuffer is a Rust FFI to free a byte buffer allocated by Rust.
	freeBuffer func(bufferPtr unsafe.Pointer)
	// freeReader is a Rust FFI to free a ReaderHandle allocated by Rust.
	freeReader func(readerPtr unsafe.Pointer)
}

// StepScanResult matches the Rust struct StepScanResult.
// It is used as a output parameter for the scanStepRange function.
type StepScanResult struct {
	// VecPtr is the pointer to the Rust Vec<u8> that contains the serialized scanned data.
	// This should be freed using freeBuffer when the result is no longer needed.
	VecPtr uintptr
	// DataPtr is the pointer to the actual data in the VecPtr.
	DataPtr uintptr
	// DataLen is the length of the data in the DataPtr (in bytes).
	DataLen uint64
	// NumRowsReturned is the number of rows returned.
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
	var freeBuffer func(bufferPtr unsafe.Pointer)
	purego.RegisterLibFunc(&freeBuffer, rustLib, "free_buffer")
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
		freeBuffer:    freeBuffer,
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
		freeBuffer:    func(bufferPtr unsafe.Pointer) {},
		freeReader:    func(readerPtr unsafe.Pointer) {},
	}
}

// CreateRustArrowReader creates a new RustArrowReader for a given list of file paths.
// Only the columns names provided will be read from the parquet files.
func CreateRustArrowReader(
	rustArrowWrapper *RustArrowWrapper,
	filePath string,
	columnNames []string,
) (*RustArrowReader, error) {
	// convert column names to C strings
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
	if scanResult.NumRowsReturned == 0 || scanResult.DataLen == 0 {
		return []parquet.KeyValueList{}, nil
	}

	// The data pointers come from Rust FFI,
	// but we must manage the lifetime of the data ourselves via freeBuffer.
	//
	// We need to convert uintptr to unsafe.Pointer here for FFI interop.
	// This is safe because:
	// 1. The pointer is owned by Rust and kept alive until freeBuffer is called
	// 2. We call freeBuffer in the defer to ensure cleanup
	// 3. The data is not moved by Go's GC (it's Rust-owned memory)
	dataPtr := scanResult.DataPtr
	vecPtr := scanResult.VecPtr
	bufferBytes := unsafe.Slice(
		//nolint:govet // pointer memory is managed in the rust wrapper library
		(*byte)(unsafe.Pointer(dataPtr)),
		scanResult.DataLen,
	)
	defer func() {
		//nolint:govet // pointer memory is managed in the rust wrapper library
		r.rustArrowWrapper.freeBuffer(unsafe.Pointer(vecPtr))
	}()

	results, err := parseScanResultData(bufferBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to decode binary data: %w", err)
	}

	return results, nil
}

// Release frees the resources allocated by the RustReader.
// It should be called only once when the RustReader is no longer needed.
func (r *RustArrowReader) Release() {
	if r.reader != nil {
		r.rustArrowWrapper.freeReader(r.reader)
	}
}

// Type tags matching the Rust serialize module.
const (
	typeNull    = 0
	typeInt64   = 1
	typeUint64  = 2
	typeFloat64 = 3
	typeString  = 4
	typeBool    = 5
	typeBinary  = 6
	typeList    = 7
	typeMap     = 8
)

// parseScanResultData decodes the scan data returned by the Rust scanStepRange function
// into a []parquet.KeyValueList.
func parseScanResultData(data []byte) ([]parquet.KeyValueList, error) {
	if len(data) == 0 {
		return []parquet.KeyValueList{}, nil
	}

	// offset tracks the current position in the data byte slice
	offset := 0

	numColumns, err := readU32(data, &offset)
	if err != nil {
		return nil, fmt.Errorf("reading num_columns: %w", err)
	}

	columnNames := make([]string, numColumns)
	for i := 0; i < int(numColumns); i++ {
		nameLen, err := readU32(data, &offset)
		if err != nil {
			return nil, fmt.Errorf("reading column name length: %w", err)
		}
		if offset+int(nameLen) > len(data) {
			return nil, fmt.Errorf("column name extends past buffer")
		}

		columnNames[i] = string(data[offset : offset+int(nameLen)])
		offset += int(nameLen)
	}

	numRows, err := readU32(data, &offset)
	if err != nil {
		return nil, fmt.Errorf("reading num_rows: %w", err)
	}

	results := make([]parquet.KeyValueList, 0, numRows)
	for row := 0; row < int(numRows); row++ {
		kvList := make(parquet.KeyValueList, 0, numColumns)
		for col := 0; col < int(numColumns); col++ {
			value, err := readValue(data, &offset)
			if err != nil {
				return nil, fmt.Errorf("row %d col %d: %w", row, col, err)
			}
			kvList = append(kvList, parquet.KeyValuePair{
				Key:   columnNames[col],
				Value: value,
			})
		}
		results = append(results, kvList)
	}

	return results, nil
}

// readU32 reads a 32-bit unsigned integer from the data at the given offset,:wincmd j
// and updates the offset to the next byte after the read value.
func readU32(data []byte, offset *int) (uint32, error) {
	if *offset+4 > len(data) {
		return 0, fmt.Errorf("buffer underflow reading u32 at offset %d", *offset)
	}
	v := binary.LittleEndian.Uint32(data[*offset : *offset+4])
	*offset += 4
	return v, nil
}

// readValue reads a value from the data at the given offset.
//
// The offset is updated to the next byte after the read value.
// If the offset is out of bounds, an error is returned.
func readValue(data []byte, offset *int) (any, error) {
	if *offset >= len(data) {
		return nil, fmt.Errorf("buffer underflow reading type tag at offset %d", *offset)
	}
	typeTag := data[*offset]
	*offset++

	switch typeTag {
	case typeNull:
		return nil, nil
	case typeInt64:
		return readInt64(data, offset)
	case typeUint64:
		return readUint64(data, offset)
	case typeFloat64:
		return readFloat64(data, offset)
	case typeString:
		return readString(data, offset)
	case typeBool:
		return readBool(data, offset)
	case typeBinary:
		return readBinary(data, offset)
	case typeList:
		return readList(data, offset)
	case typeMap:
		return parseMapValue(data, offset)
	default:
		return nil, fmt.Errorf("unknown type: %d", typeTag)
	}
}

func readInt64(data []byte, offset *int) (int64, error) {
	const size = 8
	if *offset+size > len(data) {
		return 0, ErrOffsetOutOfBounds
	}
	v := int64(binary.LittleEndian.Uint64(data[*offset : *offset+size]))
	*offset += size
	return v, nil
}

func readUint64(data []byte, offset *int) (uint64, error) {
	const size = 8
	if *offset+size > len(data) {
		return 0, ErrOffsetOutOfBounds
	}
	v := binary.LittleEndian.Uint64(data[*offset : *offset+size])
	*offset += size
	return v, nil
}

func readFloat64(data []byte, offset *int) (float64, error) {
	const size = 8
	if *offset+size > len(data) {
		return 0, ErrOffsetOutOfBounds
	}
	bits := binary.LittleEndian.Uint64(data[*offset : *offset+size])
	*offset += size
	return math.Float64frombits(bits), nil
}

func readString(data []byte, offset *int) (string, error) {
	strLen, err := readU32(data, offset)
	if err != nil {
		return "", fmt.Errorf("reading string length: %w", err)
	}
	if *offset+int(strLen) > len(data) {
		return "", ErrOffsetOutOfBounds
	}
	s := string(data[*offset : *offset+int(strLen)])
	*offset += int(strLen)
	return s, nil
}

func readBool(data []byte, offset *int) (bool, error) {
	if *offset >= len(data) {
		return false, ErrOffsetOutOfBounds
	}
	v := data[*offset] != 0
	*offset++
	return v, nil
}

func readBinary(data []byte, offset *int) ([]byte, error) {
	binLen, err := readU32(data, offset)
	if err != nil {
		return nil, fmt.Errorf("reading binary length: %w", err)
	}
	if *offset+int(binLen) > len(data) {
		return nil, ErrOffsetOutOfBounds
	}
	b := make([]byte, binLen)
	copy(b, data[*offset:*offset+int(binLen)])
	*offset += int(binLen)
	return b, nil
}

func readList(data []byte, offset *int) ([]any, error) {
	listLen, err := readU32(data, offset)
	if err != nil {
		return nil, fmt.Errorf("reading list length: %w", err)
	}
	values := make([]any, 0, listLen)
	for i := 0; i < int(listLen); i++ {
		v, err := readValue(data, offset)
		if err != nil {
			return nil, fmt.Errorf("list element %d: %w", i, err)
		}
		values = append(values, v)
	}
	return values, nil
}

// parseMapValue reads a map/struct value from the data at the given offset.
func parseMapValue(data []byte, offset *int) (map[string]any, error) {
	numEntries, err := readU32(data, offset)
	if err != nil {
		return nil, fmt.Errorf("reading map entry count: %w", err)
	}
	m := make(map[string]any, numEntries)
	for i := 0; i < int(numEntries); i++ {
		keyLen, err := readU32(data, offset)
		if err != nil {
			return nil, fmt.Errorf("map entry %d key length: %w", i, err)
		}
		if *offset+int(keyLen) > len(data) {
			return nil, ErrOffsetOutOfBounds
		}
		key := string(data[*offset : *offset+int(keyLen)])
		*offset += int(keyLen)

		val, err := readValue(data, offset)
		if err != nil {
			return nil, fmt.Errorf("map entry %d value: %w", i, err)
		}
		m[key] = val
	}
	return m, nil
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
