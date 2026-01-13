package runconsolelogs

import (
	"errors"
	"fmt"
	"io/fs"
	"os"

	"github.com/wandb/wandb/core/internal/sparselist"
)

var errCursorBehindBufStart = errors.New("cursor < bufStart")

// lineFile is a file containing line-oriented text.
type lineFile struct {
	// path is the path to the file.
	path string

	// nextLineNum is the number of '\n' in the file.
	//
	// The file always ends with a '\n' unless it is empty.
	nextLineNum int
}

// lineFileIO is an open handle to a line-oriented file.
type lineFileIO struct {
	f *os.File

	// buf is buffered data from the tail end of the file.
	buf []byte

	// bufStart is the file offset from which the rest of the file is
	// contained in buf.
	//
	// The file's contents from bufStart to bufStart+len(buf) are guaranteed
	// to be equal to buf. It may have contents beyond that which are stale
	// and will be removed on the next write.
	bufStart int64

	// needsTruncate is true if the file contains bytes beyond
	// bufStart+len(buf) that should be discarded.
	needsTruncate bool

	// cursor is an offset into the file used during PopLine.
	//
	// It is always true that bufStart <= cursor <= bufStart+len(buf).
	cursor int64
}

// CreateLineFile creates an empty file or returns an error.
//
// The file's parent directory must exist. If the file already exists,
// it is truncated.
func CreateLineFile(path string, perm fs.FileMode) (*lineFile, error) {
	if err := os.WriteFile(string(path), []byte{}, perm); err != nil {
		return nil, err
	}

	return &lineFile{path: path, nextLineNum: 0}, nil
}

// UpdateLines replaces lines in the file.
//
// This is written for performance when updating lines near the end of the file.
func (f *lineFile) UpdateLines(lines *sparselist.SparseList[string]) (err error) {
	if lines.Len() == 0 {
		return nil
	}

	file, err := f.Open()
	if err != nil {
		return err
	}
	defer func() {
		// An error in Close() can indicate a problem flushing writes
		// to the file.
		closeErr := file.Close()
		if err == nil {
			err = closeErr
		}
	}()

	oldLinesReversed := []string{}
	origNextLine := f.nextLineNum

	// Pop off old lines until the line we're modifying.
	for ; f.nextLineNum > lines.FirstIndex(); f.nextLineNum-- {
		line, err := file.PopLine()
		if err != nil {
			return err
		}

		oldLinesReversed = append(oldLinesReversed, line)
	}

	// Write back lines, replacing old lines as necessary.
loop:
	for {
		var lineToWrite string

		newLine, hadNewLine := lines.Get(f.nextLineNum)
		switch {
		// Use the new line if there is one.
		case hadNewLine:
			lineToWrite = newLine

		// Use the old line if there is one.
		case f.nextLineNum < origNextLine:
			idx := origNextLine - 1 - f.nextLineNum
			lineToWrite = oldLinesReversed[idx]

		// If we're adding lines past the original number of lines in the
		// file, append blanks for any unspecified lines.
		case f.nextLineNum < lines.LastIndex():
			lineToWrite = ""

		// No more lines to write, stop.
		default:
			break loop
		}

		f.nextLineNum++

		if err := file.AppendLine(lineToWrite); err != nil {
			return err
		}
	}

	return nil
}

// Open opens the file for modification.
func (f *lineFile) Open() (*lineFileIO, error) {
	file, err := os.OpenFile(f.path, os.O_RDWR, 0)
	if err != nil {
		return nil, fmt.Errorf("failed to open file: %v", err)
	}

	info, err := file.Stat()
	if err != nil {
		return nil, fmt.Errorf("failed to stat file: %v", err)
	}

	endOffset := info.Size()

	return &lineFileIO{
		f:        file,
		bufStart: endOffset,
		buf:      make([]byte, 0),
		cursor:   endOffset,
	}, nil
}

// Close flushes changes and closes the file handle.
func (f *lineFileIO) Close() error {
	// Drop data that was removed by PopLine.
	if err := f.f.Truncate(f.bufStart + int64(len(f.buf))); err != nil {
		return fmt.Errorf("failed to truncate when closing: %v", err)
	}

	if err := f.f.Close(); err != nil {
		return fmt.Errorf("failed to close: %v", err)
	}

	return nil
}

// AppendLine writes a line to the file.
//
// The line must not contain '\n'.
func (f *lineFileIO) AppendLine(line string) error {
	lineStart := f.bufStart + int64(len(f.buf))

	// Drop data that was removed by PopLine.
	if f.needsTruncate {
		if err := f.f.Truncate(lineStart); err != nil {
			return fmt.Errorf("failed to truncate before appending: %v", err)
		}
		f.needsTruncate = false
	}

	// Write the UTF-8 bytes of the line to the file with a '\n' at the end.
	data := make([]byte, 0, len(line)+1)
	data = append(data, line...)
	data = append(data, '\n')

	_, err := f.f.WriteAt(data, lineStart)
	if err != nil {
		return fmt.Errorf("failed to append: %v", err)
	}

	f.buf = make([]byte, 0)
	f.bufStart = lineStart + int64(len(data))
	f.cursor = f.bufStart
	return nil
}

// PopLine removes the last file from the file and returns it.
//
// The returned line does not end with '\n'.
//
// Returns an error if there's an issue reading the file or if there are no
// more lines.
func (f *lineFileIO) PopLine() (string, error) {
	// Start with the cursor at the end of the file.
	f.cursor = f.bufStart + int64(len(f.buf))

	for {
		err := f.cursorBack()
		if err != nil {
			return "", err
		}

		prevByte, isAtStart, err := f.peekPrevByte()
		if err != nil {
			return "", err
		}

		// We encode the text in the file using UTF-8. In the UTF-8 encoding,
		// a '\n' byte (0x0A) is always a '\n' rune and never part of another
		// rune---this is because the most significant bit is zero only for
		// single-byte UTF-8 code points.
		//
		// This is a crucial fact for reading the file in reverse.
		if isAtStart || prevByte == '\n' {
			bufIdx := f.cursor - f.bufStart

			// Read the line contents, which is everything from the current
			// cursor position up to the end of the buffer, minus the last
			// character which is a '\n'.
			line := string(f.buf[bufIdx : len(f.buf)-1])

			// Drop the line from the buffer.
			f.buf = f.buf[:bufIdx:bufIdx]
			f.needsTruncate = true

			return line, nil
		}
	}
}

// cursorBack moves the cursor back one byte, loading data as necessary.
//
// It is an error to call this if the cursor is already at offset 0.
func (f *lineFileIO) cursorBack() error {
	if f.cursor == 0 {
		return errors.New("cursor is at start of file")
	}
	if f.cursor < f.bufStart {
		return errCursorBehindBufStart
	}

	if f.cursor == f.bufStart {
		if err := f.loadMore(); err != nil {
			return err
		}
	}

	f.cursor -= 1
	return nil
}

// peekPrevByte returns the byte in the file before the cursor, loading
// data as necessary.
//
// If the cursor is already at the start of the file, the second return
// value is true.
func (f *lineFileIO) peekPrevByte() (byte, bool, error) {
	if f.cursor == 0 {
		return 0, true, nil
	}
	if f.cursor < f.bufStart {
		return 0, false, errCursorBehindBufStart
	}

	if f.cursor == f.bufStart {
		if err := f.loadMore(); err != nil {
			return 0, false, err
		}
	}

	return f.buf[f.cursor-f.bufStart-1], false, nil
}

// loadMore reads the file backwards to grow the buffer.
//
// Guarantees that bufStart decreases. Returns an error if it is
// already at 0.
func (f *lineFileIO) loadMore() error {
	if f.bufStart == 0 {
		return errors.New("no more data in file")
	}

	// Read 8K at a time, which is one or two pages on most systems.
	// It doesn't really matter, it's fast enough.
	nToRead := min(8*1024, f.bufStart)
	newBufStart := f.bufStart - int64(nToRead)

	// We don't have to loop here. From the ReaderAt.ReadAt docs:
	//   If some data is available but not len(p) bytes, ReadAt blocks until
	//   either all the data is available or an error occurs. In this respect
	//   ReadAt is different from Read.
	newBuf := make([]byte, nToRead, int(nToRead)+len(f.buf))
	n, err := f.f.ReadAt(newBuf, newBufStart)

	// From the ReaderAt.ReadAt docs:
	//   If the n = len(p) bytes returned by ReadAt are at the end of the
	//   input source, ReadAt may return either err == EOF or err == nil.
	// Although File.ReadAt doesn't say this, it appears to still be possible.
	if int64(n) != nToRead {
		// err is guaranteed non-nil by ReadAt in this case.
		return fmt.Errorf("failed to load %d bytes at offset %d: %v",
			nToRead, newBufStart, err)
	}

	newBuf = append(newBuf, f.buf...)
	f.buf = newBuf
	f.bufStart = newBufStart
	return nil
}
