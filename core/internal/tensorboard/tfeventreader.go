package tensorboard

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"gocloud.dev/blob"
	"google.golang.org/protobuf/proto"
)

// maxChecksumErrorDuration is the timeframe within which we expect transient
// checksum mismatches to resolve themselves. Mismatches within this time
// emit warnings, and after this time cause reading to fail.
const maxChecksumErrorDuration = 30 * time.Second

// TFEventReader reads TFEvent protos out of tfevents files.
type TFEventReader struct {
	// fileFilter selects the tfevents files to read.
	fileFilter TFEventsFileFilter

	tfeventsPath   *LocalOrCloudPath
	tfeventsBucket *blob.Bucket

	getNow func() time.Time // allows stubbing time.Now for testing
	logger *observability.CoreLogger

	buffer            []byte
	bufferStartOffset int64  // offset in currentFile where buffer starts
	currentFile       string // file from which to read more data
	currentOffset     int64  // offset in currentFile from which to read more

	lastUnexpectedChecksumTime time.Time
}

func NewTFEventReader(
	logDir *LocalOrCloudPath,
	fileFilter TFEventsFileFilter,
	logger *observability.CoreLogger,
	getNow func() time.Time,
) *TFEventReader {
	return &TFEventReader{
		fileFilter:   fileFilter,
		tfeventsPath: logDir,

		getNow: getNow,
		logger: logger,
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

	// Clear the checksum error timer if we don't see a checksum error.
	hitUnexpectedChecksum := false
	defer func() {
		if !hitUnexpectedChecksum {
			s.lastUnexpectedChecksumTime = time.Time{}
		}
	}()

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
	computedHeaderCRC32C := MaskedCRC32C(headerBytes)
	if computedHeaderCRC32C != expectedHeaderCRC32C {
		hitUnexpectedChecksum = true
		return nil, s.logOrFailUnexpectedChecksum(
			"header",
			expectedHeaderCRC32C,
			computedHeaderCRC32C,
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
	computedEventCRC32C := MaskedCRC32C(eventBytes)
	if computedEventCRC32C != expectedEventCRC32C {
		hitUnexpectedChecksum = true
		return nil, s.logOrFailUnexpectedChecksum(
			"payload",
			expectedEventCRC32C,
			computedEventCRC32C,
		)
	}

	s.buffer = slices.Clone(s.buffer[bytesRead:])
	s.bufferStartOffset += int64(bytesRead)

	var ret tbproto.TFEvent
	err := proto.Unmarshal(eventBytes, &ret)
	if err != nil {
		return nil, fmt.Errorf(
			"tensorboard: failed to unmarshal proto: %v", err)
	}

	return &ret, nil
}

// logOrFailUnexpectedChecksum either logs a warning or returns an error
// for NextEvent to return when a checksum mismatch occurs.
//
// Transient checksum errors are possible if a tfevents file is being written
// using mmap(). These should resolve quickly; if not, then there's probably
// real data corruption.
func (s *TFEventReader) logOrFailUnexpectedChecksum(
	where string,
	expectedCRC32C, computedCRC32C uint32,
) error {
	now := s.getNow()

	if s.lastUnexpectedChecksumTime.IsZero() {
		s.lastUnexpectedChecksumTime = now
	}

	if now.Sub(s.lastUnexpectedChecksumTime) > maxChecksumErrorDuration {
		return fmt.Errorf(
			"tensorboard: unexpected %s checksum for record at byte offset %d,"+
				" expected %d but calculated %d: %s",
			where,
			s.bufferStartOffset,
			expectedCRC32C,
			computedCRC32C,
			s.currentFile,
		)
	}

	s.rewindBuffer()
	s.logger.Warn(
		fmt.Sprintf("tensorboard: unexpected %s checksum, will retry", where),
		"expected", expectedCRC32C,
		"computed", computedCRC32C,
		"file", s.currentFile,
		"offset", s.bufferStartOffset,
	)
	return nil
}

// rewindBuffer clears the buffer and causes the next read to reread
// the same section of the file.
func (s *TFEventReader) rewindBuffer() {
	s.buffer = nil
	s.currentOffset = s.bufferStartOffset
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
		s.currentOffset = 0
		s.buffer = nil
		s.bufferStartOffset = 0

		if s.currentFile == "" {
			return false
		}

		s.emitCurrentFile(onNewFile)
	}

	if len(s.buffer) == 0 {
		s.bufferStartOffset = s.currentOffset
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

		// If there's still unconsumed data in the current file,
		// we can't move on to the next file. Events don't get split
		// between files.
		if len(s.buffer) > 0 {
			s.logger.Warn(
				"tensorboard: maybe incomplete event",
				"file", s.currentFile,
				"offset", s.bufferStartOffset)
			return false
		}

		s.currentFile = nextFile
		s.currentOffset = 0
		s.bufferStartOffset = 0
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
