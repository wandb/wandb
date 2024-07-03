package runconsolelogs

import (
	"errors"
	"fmt"
	"io/fs"
	"os"

	"github.com/wandb/wandb/core/internal/sparselist"
)

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

	// buf is buffered data from the file.
	buf []byte

	// bufStart is the file offset from which the rest of the file is
	// contained in buf.
	bufStart int64

	// cursor is an offset into the file.
	//
	// `cursor - bufStartOffset` is always a valid index into the buffer
	// if it holds at least one byte. Otherwise, `cursor == bufStart`.
	cursor int64
}

// CreateLineFile creates an empty file or returns an error.
//
// The file must not already exist. Its parent directory must exist.
func CreateLineFile(path string, perm fs.FileMode) (*lineFile, error) {
	if err := os.WriteFile(string(path), []byte{}, perm); err != nil {
		return nil, err
	}

	return &lineFile{path: path, nextLineNum: 0}, nil
}

// UpdateLines replaces lines in the file.
//
// This is written for performance when updating lines near the end of the file.
func (f *lineFile) UpdateLines(lines sparselist.SparseList[string]) error {
	if lines.Len() == 0 {
		return nil
	}

	file, err := f.Open()
	if err != nil {
		return err
	}
	defer file.Close()

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
	if err := f.f.Truncate(f.bufStart + int64(len(f.buf))); err != nil {
		return err
	}

	if err := f.f.Close(); err != nil {
		return err
	}

	return nil
}

// AppendLine writes a line to the file.
//
// The line must not contain '\n'.
func (f *lineFileIO) AppendLine(line string) error {
	lineStart := f.bufStart + int64(len(f.buf))

	// Truncate the file to the current position first.
	if len(f.buf) > 0 {
		if err := f.f.Truncate(lineStart); err != nil {
			return err
		}
	}

	// Write the UTF-8 bytes of the line to the file with a '\n' at the end.
	data := make([]byte, 0, len(line)+1)
	data = append(data, line...)
	data = append(data, '\n')

	_, err := f.f.WriteAt(data, lineStart)
	if err != nil {
		return err
	}

	f.buf = make([]byte, 0)
	f.bufStart = lineStart + int64(len(data))
	f.cursor = f.bufStart
	return nil
}

// PopLine drops the last file from the file and returns it.
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

	if f.cursor <= f.bufStart {
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

	if len(f.buf) == 0 || f.cursor == f.bufStart {
		if err := f.loadMore(); err != nil {
			return 0, false, err
		}
	}

	return f.buf[f.cursor-f.bufStart-1], false, nil
}

// loadMore reads more data from the file to the buffer.
//
// Guarantees that bufStartOffset decreases. Returns an error if it is
// already at 0.
func (f *lineFileIO) loadMore() error {
	if f.bufStart == 0 {
		return errors.New("no more data in file")
	}

	// Read 8K at a time, which is one or two pages on most systems.
	// It doesn't really matter, it's fast enough.
	nToRead := min(2<<13, f.bufStart)
	newBufStartOffset := f.bufStart - int64(nToRead)

	newBuf := make([]byte, nToRead, int(nToRead)+len(f.buf))
	_, err := f.f.ReadAt(newBuf, newBufStartOffset)
	if err != nil {
		return err
	}

	newBuf = append(newBuf, f.buf...)
	f.buf = newBuf
	f.bufStart = newBufStartOffset
	return nil
}
