package tensorboard

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"slices"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/observability"
	"google.golang.org/protobuf/proto"
)

// TFEventReader reads TFEvent protos out of tfevents files.
type TFEventReader struct {
	// fileFilter selects the tfevents files to read.
	fileFilter TFEventsFileFilter

	logger *observability.CoreLogger

	buffer        []byte
	logDir        paths.AbsolutePath
	currentFile   *paths.AbsolutePath
	currentOffset int64
}

func NewTFEventReader(
	logDir paths.AbsolutePath,
	fileFilter TFEventsFileFilter,
	logger *observability.CoreLogger,
) *TFEventReader {
	return &TFEventReader{
		fileFilter: fileFilter,

		logger: logger,

		buffer: make([]byte, 0),
		logDir: logDir,
	}
}

// NextEvent reads the next event in the sequence.
//
// It returns nil if there's no next event yet. It returns an error if parsing
// fails.
//
// New files encountered are passed to `onNewFile`.
func (s *TFEventReader) NextEvent(
	onNewFile func(paths.AbsolutePath),
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
	if !s.ensureBuffer(bytesRead+8, onNewFile) {
		return nil, nil
	}
	headerBytes := s.buffer[bytesRead : bytesRead+8]
	header := binary.LittleEndian.Uint64(headerBytes)
	bytesRead += 8

	// Read the CRC32 footer for the header.
	if !s.ensureBuffer(bytesRead+4, onNewFile) {
		return nil, nil
	}
	headerCRC32 := binary.LittleEndian.Uint32(s.buffer[bytesRead : bytesRead+4])
	bytesRead += 4

	// Check the CRC32 checksum of the header.
	if MaskedCRC32C(headerBytes) != headerCRC32 {
		return nil, fmt.Errorf(
			"tensorboard: unexpected CRC-32C checksum for event header")
	}

	// Read the event proto.
	if !s.ensureBuffer(bytesRead+header, onNewFile) {
		return nil, nil
	}
	eventBytes := s.buffer[bytesRead : bytesRead+header]
	bytesRead += header

	// Read the CRC32 footer for the proto.
	if !s.ensureBuffer(bytesRead+4, onNewFile) {
		return nil, nil
	}
	eventCRC32 := binary.LittleEndian.Uint32(s.buffer[bytesRead : bytesRead+4])
	bytesRead += 4

	// Check the CRC32 checksum of the event.
	if MaskedCRC32C(eventBytes) != eventCRC32 {
		return nil, fmt.Errorf(
			"tensorboard: unexpected CRC-32C checksum for event")
	}

	s.buffer = slices.Clone(s.buffer[bytesRead:])

	var ret tbproto.TFEvent
	err := proto.Unmarshal(eventBytes, &ret)
	if err != nil {
		return nil, fmt.Errorf(
			"tensorboard: failed to unmarshall proto: %v", err)
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
	count uint64,
	onNewFile func(paths.AbsolutePath),
) bool {
	if uint64(len(s.buffer)) >= count {
		return true
	}

	// If we haven't found the first file, try to find it.
	if s.currentFile == nil {
		s.currentFile = s.nextTFEventsFile()

		if s.currentFile == nil {
			return false
		}

		onNewFile(*s.currentFile)
	}

	for {
		// Look for the next file before we read from the current file.
		//
		// We assume that after the next file is observed to exist, the current
		// file will not be modified. Doing this in the opposite order would
		// not work because between reaching the end of the current file and
		// finding the next file, more events could have been written to the
		// current file.
		nextFile := s.nextTFEventsFile()

		success, err := s.readFromCurrent(count)

		if success {
			return true
		}

		if err != nil && err != io.EOF {
			// We saw an error that wasn't EOF, so something is wrong.
			s.logger.CaptureError(
				fmt.Errorf(
					"tensorboard: error reading current tfevents file: %v",
					err,
				))
			return false
		}

		if nextFile == nil {
			return false
		}

		s.currentFile = nextFile
		s.currentOffset = 0
		onNewFile(*s.currentFile)
	}
}

// nextTFEventsFile finds the tfevents file that comes after the current one.
//
// Returns nil if there is no next file yet.
func (s *TFEventReader) nextTFEventsFile() *paths.AbsolutePath {
	nextFile, err := nextTFEventsFile(
		s.logDir,
		s.currentFile,
		s.fileFilter,
	)

	if err != nil {
		s.logger.Warn(
			"tensorboard: error while looking for next tfevents file",
			"error",
			err,
		)
	}

	return nextFile
}

// readFromCurrent reads into the buffer from the current tfevents file until
// the buffer has count bytes or the end of the file is reached.
//
// Returns true if the buffer has count bytes. Otherwise, returns false if it
// reached EOF or another error while reading, and returns the error.
func (s *TFEventReader) readFromCurrent(count uint64) (bool, error) {
	file, err := os.Open(s.currentFile.OrEmpty())
	if err != nil {
		return false, err
	}
	defer file.Close()

	_, err = file.Seek(s.currentOffset, 0 /*offset is relative to origin*/)
	if err != nil {
		return false, err
	}

	// Read from the file until we've read enough.
	//
	// Read at least 4KB from the file each time to minimize the number of
	// times we have to reopen the file.
	nextBuffer := make([]byte, max(count, 4096))
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
