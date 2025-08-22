package tensorboard

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"slices"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"gocloud.dev/blob"
	"google.golang.org/protobuf/proto"
)

// TFEventReader reads TFEvent protos out of tfevents files.
type TFEventReader struct {
	// fileFilter selects the tfevents files to read.
	fileFilter TFEventsFileFilter

	tfeventsPath   *LocalOrCloudPath
	tfeventsBucket *blob.Bucket

	logger *observability.CoreLogger

	buffer        []byte
	currentFile   string
	currentOffset int64
}

func NewTFEventReader(
	logDir *LocalOrCloudPath,
	fileFilter TFEventsFileFilter,
	logger *observability.CoreLogger,
) *TFEventReader {
	return &TFEventReader{
		fileFilter:   fileFilter,
		tfeventsPath: logDir,

		logger: logger,

		buffer: make([]byte, 0),
	}
}

// NextEvent reads the next event in the sequence.
//
// It returns nil if there's no next event yet. It returns an error if parsing
// or reading fails.
//
// New files encountered are passed to `onNewFile`.
func (s *TFEventReader) NextEvent(
	ctx context.Context,
	onNewFile func(*LocalOrCloudPath),
) (*tbproto.TFEvent, error) {
	// FORMAT: https://github.com/tensorflow/tensorboard/blob/f3f26b46981da5bd46a5bb93fcf02d9eb7608bc1/tensorboard/summary/writer/record_writer.py#L31-L40
	//
	// (all integers little-endian)
	//   uint64      length
	//   uint32      "masked CRC" of length
	//   byte        data[length]
	//   uint32      "masked CRC" of data

	bytesRead := uint64(0)

	// Read the header, which specifies the size of the event proto.
	if !s.ensureBuffer(ctx, bytesRead+8, onNewFile) {
		return nil, nil
	}
	headerBytes := s.buffer[bytesRead : bytesRead+8]
	header := binary.LittleEndian.Uint64(headerBytes)
	bytesRead += 8

	// Read the CRC32 footer for the header.
	if !s.ensureBuffer(ctx, bytesRead+4, onNewFile) {
		return nil, nil
	}
	expectedHeaderCRC32C := binary.LittleEndian.Uint32(s.buffer[bytesRead : bytesRead+4])
	bytesRead += 4

	// Check the CRC32 checksum of the header.
	actualHeaderCRC32C := MaskedCRC32C(headerBytes)
	if actualHeaderCRC32C != expectedHeaderCRC32C {
		return nil, fmt.Errorf(
			"tensorboard: unexpected CRC-32C checksum for event header. Expected: %d, got: %d",
			expectedHeaderCRC32C,
			actualHeaderCRC32C,
		)
	}

	// Read the event proto.
	if !s.ensureBuffer(ctx, bytesRead+header, onNewFile) {
		return nil, nil
	}
	eventBytes := s.buffer[bytesRead : bytesRead+header]
	bytesRead += header

	// Read the CRC32 footer for the proto.
	if !s.ensureBuffer(ctx, bytesRead+4, onNewFile) {
		return nil, nil
	}
	expectedEventCRC32C := binary.LittleEndian.Uint32(s.buffer[bytesRead : bytesRead+4])
	bytesRead += 4

	// Check the CRC32 checksum of the event.
	actualEventCRC32C := MaskedCRC32C(eventBytes)
	if actualEventCRC32C != expectedEventCRC32C {
		return nil, fmt.Errorf(
			"tensorboard: unexpected CRC-32C checksum for event. Expected: %d, got: %d",
			expectedEventCRC32C,
			actualEventCRC32C,
		)
	}

	s.buffer = slices.Clone(s.buffer[bytesRead:])

	var ret tbproto.TFEvent
	err := proto.Unmarshal(eventBytes, &ret)
	if err != nil {
		return nil, fmt.Errorf(
			"tensorboard: failed to unmarshal proto: %v", err)
	}

	return &ret, nil
}

// ensureBuffer tries to read enough data into the buffer so that it
// has at least count bytes.
//
// When this starts reading a new file, its path is passed to `onNewFile`.
//
// It returns whether the buffer has the desired amount of data.
func (s *TFEventReader) ensureBuffer(
	ctx context.Context,
	count uint64,
	onNewFile func(*LocalOrCloudPath),
) bool {
	if uint64(len(s.buffer)) >= count {
		return true
	}

	// If we haven't found the first file, try to find it.
	if s.currentFile == "" {
		s.currentFile = s.nextTFEventsFile(ctx)

		if s.currentFile == "" {
			return false
		}

		s.emitCurrentFile(onNewFile)
	}

	for {
		// Look for the next file before we read from the current file.
		//
		// We assume that after the next file is observed to exist, the current
		// file will not be modified. Doing this in the opposite order would
		// not work because between reaching the end of the current file and
		// finding the next file, more events could have been written to the
		// current file.
		nextFile := s.nextTFEventsFile(ctx)

		success, err := s.readFromCurrent(ctx, count)

		if success {
			return true
		}

		if err != nil && !errors.Is(err, io.EOF) {
			// We saw an error that wasn't EOF, so something may be wrong.
			s.logger.Warn(
				"tensorboard: error reading current tfevents file",
				"error", err)
			return false
		}

		if nextFile == "" {
			return false
		}

		s.currentFile = nextFile
		s.currentOffset = 0
		s.emitCurrentFile(onNewFile)
	}
}

// emitCurrentFile passes the current tfevents file path to the callback.
func (s *TFEventReader) emitCurrentFile(onNewFile func(*LocalOrCloudPath)) {
	if s.currentFile == "" {
		return
	}

	child, err := s.tfeventsPath.Child(s.currentFile)

	if err != nil {
		s.logger.Warn("tensorboard: bad file name, not uploading", "error", err)
		return
	}

	onNewFile(child)
}

// nextTFEventsFile finds the tfevents file that comes after the current one.
//
// Returns an empty string if there is no next file yet.
func (s *TFEventReader) nextTFEventsFile(ctx context.Context) string {
	if s.tfeventsBucket == nil {
		var err error
		s.tfeventsBucket, err = s.tfeventsPath.Bucket(ctx)
		if err != nil {
			s.logger.Warn(
				"tensorboard: failed to open tfevents logging directory",
				"error", err)
			return ""
		}
	}

	nextFile, err := nextTFEventsFile(
		ctx,
		s.tfeventsBucket,
		s.currentFile,
		s.fileFilter,
	)

	if err != nil {
		s.logger.Warn(
			"tensorboard: error while looking for next tfevents file",
			"error", err)
		return ""
	}

	return nextFile
}

// readFromCurrent reads into the buffer from the current tfevents file until
// the buffer has count bytes or the end of the file is reached.
//
// Returns true if the buffer has count bytes. Returns false if there is an
// error.
//
// For cloud files, the error may be the result of a network issue.
// The returned error may wrap io.EOF if we're at the end of a file,
// but some cloud APIs (such as Google Cloud Storage) return a generic
// error when calling NewRangeReader with an offset equal to the file length.
func (s *TFEventReader) readFromCurrent(
	ctx context.Context,
	count uint64,
) (bool, error) {
	// Read at least 16KB from the file each time to minimize the number of
	// times we have to reopen it, without using too much memory.
	//
	// Note that the file may exist in the cloud, in which case this is the
	// number of bytes we will try to download. It's best to download as much
	// as we can to avoid frequently re-establishing a connection.
	const readBufferMinSize = 1 << 14
	readBufferSize := max(int64(count)-int64(len(s.buffer)), readBufferMinSize)

	file, err := s.tfeventsBucket.NewRangeReader(
		ctx,
		s.currentFile,
		s.currentOffset,
		readBufferSize,
		nil,
	)

	if err != nil {
		return false, err
	}
	defer func() {
		_ = file.Close()
	}()

	// Read from the file until we've read enough.
	nextBuffer := make([]byte, readBufferSize)
	for uint64(len(s.buffer)) < count {
		nRead, err := file.Read(nextBuffer)
		s.buffer = append(s.buffer, nextBuffer[:nRead]...)
		s.currentOffset += int64(nRead)

		if err != nil {
			return false, err
		}
	}

	return true, nil
}
