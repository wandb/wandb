// Modified from upstream sources
// https://github.com/golang/leveldb/blob/master/record/record.go
// Changes:
// - Add ability to use different CRC algorithm
// - Extra handling for W&B's regrettable customization of the format

// Copyright 2011 The LevelDB-Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

// Package record reads and writes sequences of records. Each record is a stream
// of bytes that completes before the next record starts.
//
// When reading, call Next to obtain an io.Reader for the next record. Next will
// return io.EOF when there are no more records. It is valid to call Next
// without reading the current record to exhaustion.
//
// When writing, call Next to obtain an io.Writer for the next record. Calling
// Next finishes the current record. Call Close to finish the final record.
//
// Optionally, call Flush to finish the current record and flush the underlying
// writer without starting a new record. To start a new record after flushing,
// call Next.
//
// Neither Readers or Writers are safe to use concurrently.
//
// Example code:
//
//	func read(r io.Reader) ([]string, error) {
//		var ss []string
//		records := record.NewReader(r)
//		for {
//			rec, err := records.Next()
//			if err == io.EOF {
//				break
//			}
//			if err != nil {
//				log.Printf("recovering from %v", err)
//				r.Recover()
//				continue
//			}
//			s, err := ioutil.ReadAll(rec)
//			if err != nil {
//				log.Printf("recovering from %v", err)
//				r.Recover()
//				continue
//			}
//			ss = append(ss, string(s))
//		}
//		return ss, nil
//	}
//
//	func write(w io.Writer, ss []string) error {
//		records := record.NewWriter(w)
//		for _, s := range ss {
//			rec, err := records.Next()
//			if err != nil {
//				return err
//			}
//			if _, err := rec.Write([]byte(s)), err != nil {
//				return err
//			}
//		}
//		return records.Close()
//	}
//
// The wire format is that the stream is divided(*) into 32KiB blocks, and each
// block contains a number of tightly packed chunks. Chunks cannot cross block
// boundaries. The last block may be shorter than 32 KiB. Any unused bytes in a
// block must be zero.
//
// (*) - W&B customizes this format such that the first 7 bytes of the stream
// contain a custom header. These 7 bytes are subtracted from the initial block,
// making it at most (32KiB - 7B) long.
//
// A record maps to one or more chunks. Each chunk has a 7 byte header (a 4
// byte checksum, a 2 byte little-endian uint16 length, and a 1 byte chunk type)
// followed by a payload. The checksum is over the chunk type and the payload.
//
// There are four chunk types: whether the chunk is the full record, or the
// first, middle or last chunk of a multi-chunk record. A multi-chunk record
// has one first chunk, zero or more middle chunks, and one last chunk.
//
// The wire format allows for limited recovery in the face of data corruption:
// on a format error (such as a checksum mismatch), the reader moves to the
// next block and looks for the next full or first chunk.
package leveldb

// The C++ Level-DB code calls this the log, but it has been renamed to record
// to avoid clashing with the standard log package, and because it is generally
// useful outside of logging. The C++ code also uses the term "physical record"
// instead of "chunk", but "chunk" is shorter and less confusing.

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
)

// These constants are part of the wire format and should not be changed.
const (
	fullChunkType   = 1
	firstChunkType  = 2
	middleChunkType = 3
	lastChunkType   = 4
)

const (
	blockSize     = 32 * 1024
	blockSizeMask = blockSize - 1
	headerSize    = 7
)

// W&B transaction log files begin with a 7-byte header (unrelated to the
// 7-byte LevelDB block header).
//
// The first block, if full, is 7 bytes short of 32 KiB.
const (
	wandbHeaderIdent  = ":W&B"
	wandbHeaderMagic  = 0xBEE1
	wandbHeaderLength = 7 // ident(4) + magic(2) + version(1)
)

var (
	// ErrNotAnIOSeeker is returned if the io.Reader underlying a Reader does not implement io.Seeker.
	ErrNotAnIOSeeker = errors.New("leveldb/record: reader does not implement io.Seeker")

	// ErrNoLastRecord is returned if LastRecordOffset is called and there is no previous record.
	ErrNoLastRecord = errors.New("leveldb/record: no last record exists")

	// errZeroChunk is an internal-only error used to detect and skip zeroed
	// blocks, which may occur for files created with mmap.
	errZeroChunk = errors.New("leveldb/record: block appears to be zeroed")
)

type flusher interface {
	Flush() error
}

// Reader reads records from an underlying io.Reader.
type Reader struct {
	// r is the underlying reader.
	r io.Reader

	// seq is the sequence number of the current record.
	seq int

	// blockOffset is the start position of the current block in the reader.
	//
	// If the reader started at position zero in a file, then this is
	// the file offset of the first byte of buf.
	blockOffset int64

	// buf[i:j] is the unread portion of the current chunk's payload.
	// The low bound, i, excludes the chunk header.
	//
	// If j is zero, then i is zero and there is no current chunk.
	i, j int

	// nextChunkStart is the offset of the next chunk from the start of the
	// current block.
	//
	// It may be greater than or equal to n, in which case the next chunk is in
	// a future block. It is normally equal to j except when seeking or at the
	// end of a padded block.
	nextChunkStart int

	// n is the number of bytes of buf that are valid. Once reading has started,
	// only the final block can have n < blockSize.
	n int

	// recovering is true when recovering from corruption.
	recovering bool

	// last is whether the current chunk is the last chunk of the record.
	last bool

	// err is any accumulated error.
	err error

	// buf is the buffer.
	buf [blockSize]byte

	// CRC function
	crc func([]byte) uint32
}

// NewReader returns a new reader.
//
// The given reader must start with the W&B header.
func NewReaderExt(r io.Reader, algo CRCAlgo) *Reader {
	crc := CRCCustom
	if algo == CRCAlgoIEEE {
		crc = CRCStandard
	}
	return &Reader{
		r:              r,
		crc:            crc,
		nextChunkStart: wandbHeaderLength,
	}
}

// NewReader returns a new reader.
//
// The given reader must start with the W&B header.
func NewReader(r io.Reader) *Reader {
	return NewReaderExt(r, CRCAlgoCustom)
}

// nextChunk sets r.buf[r.i:r.j] to hold the next chunk's payload, reading the
// next block into the buffer if necessary.
func (r *Reader) nextChunk(wantFirst bool) error {
	for {
		if r.nextChunkStart < 0 {
			return errors.New("leveldb/record: next chunk is behind reader")
		}

		if r.nextChunkStart+headerSize <= r.n {
			chunkType, err := r.readChunkInBlock(r.nextChunkStart)

			if err != nil {
				if r.recovering || (wantFirst && errors.Is(err, errZeroChunk)) {
					r.err = err // Recover() requires err to be set
					r.Recover()
					continue
				}

				return err
			}

			if wantFirst &&
				chunkType != fullChunkType &&
				chunkType != firstChunkType {
				continue
			}

			return nil
		}

		// There must be no bytes after the final chunk.
		//
		// We can only partially detect this error: the final chunk is the
		// last chunk in the final block, and we can detect a final block
		// only if it is not the full size. If it's a full block, it could be
		// a (potentially padded) middle block.
		//
		// If r.j is zero, then there is no current chunk.
		// Otherwise, the end of the chunk must equal the end of the block.
		if r.isShortBlock() && 0 < r.j && r.j != r.n {
			return io.ErrUnexpectedEOF
		}

		// If the next chunk was expected to be in the current block,
		// that's an unexpected EOF: it means this block contains some
		// but not all of the next chunk's bytes.
		//
		// If this is the final block and the next chunk offset is after its
		// end, that's a normal EOF.
		if r.nextChunkStart < r.n {
			return io.ErrUnexpectedEOF
		}

		// Read the next block.
		if err := r.readBlock(); err != nil {
			return err
		}
	}
}

// readChunkInBlock sets up the reader to read the chunk at the given offset
// in the current block.
//
// Returns the chunk type on success.
// Returns errZeroChunk if the chunk's header is zero.
func (r *Reader) readChunkInBlock(start int) (byte, error) {
	checksum := binary.LittleEndian.Uint32(r.buf[start+0 : start+4])
	length := binary.LittleEndian.Uint16(r.buf[start+4 : start+6])
	chunkType := r.buf[start+6]

	if checksum == 0 && length == 0 && chunkType == 0 {
		return 0, errZeroChunk
	}

	r.i = start + headerSize
	r.j = start + headerSize + int(length)
	r.nextChunkStart = startOfChunkAfter(r.j)

	switch {
	case r.j > blockSize:
		return 0, fmt.Errorf("leveldb/record: chunk too long (%d)", length)
	case r.j > r.n:
		return 0, io.ErrUnexpectedEOF
	case checksum != r.crc(r.buf[r.i-1:r.j]):
		return 0, errors.New("leveldb/record: invalid chunk (checksum mismatch)")
	}

	r.last = chunkType == fullChunkType || chunkType == lastChunkType
	r.recovering = false
	return chunkType, nil
}

// startOfChunkAfter returns the starting offset of the next chunk after
// the chunk ending at the given offset in a block.
//
// This requires a special case for padded blocks: if another chunk wouldn't fit
// into the same block, then the next chunk starts in the next block.
func startOfChunkAfter(chunkEnd int) int {
	// Only full-size blocks can be padded because the only non-full block
	// is the final block, so this logic only depends on the blockSize constant
	// and not the current reader state.
	if chunkEnd+headerSize <= blockSize {
		return chunkEnd
	} else {
		return blockSize
	}
}

// readBlock reads the next block into r.buf.
//
// Assumes that the current block consists of the bytes starting from
// blockOffset and going up to blockOffset + n.
//
// Returns EOF if the current block is not full, in which case it must be final.
func (r *Reader) readBlock() error {
	if r.isShortBlock() {
		return io.EOF
	}

	prevBlockSize := r.n
	nextBlockOffset := r.blockOffset + int64(prevBlockSize)
	n, err := io.ReadFull(r.r, r.buf[:])

	// If n == 0, then err == io.EOF.
	// It's OK if 0 < n < blockSize, in which case err == ErrUnexpectedEOF.
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) {
		return err
	}

	r.blockOffset = nextBlockOffset
	r.i, r.j, r.n = 0, 0, n
	r.nextChunkStart -= prevBlockSize
	return nil
}

// isShortBlock returns true if there is a block in memory and it is
// shorter than the blockSize, in which case it must be a final block.
func (r *Reader) isShortBlock() bool {
	return 0 < r.n && r.n < blockSize
}

// VerifyWandbHeader checks for a W&B header with the correct version.
//
// The reader must be positioned at the start.
//
// The error wraps EOF if there's no data at all and ErrUnexpectedEOF
// if there's not enough data to hold a header.
func (r *Reader) VerifyWandbHeader(expectedVersion byte) error {
	if r.blockOffset != 0 {
		return errors.New("leveldb/record: reader not in first block")
	}

	if r.n == 0 {
		if r.err = r.readBlock(); r.err != nil {
			return r.err
		}
	}

	if r.n < wandbHeaderLength {
		return io.ErrUnexpectedEOF
	}

	identBytes, magicBytes, version := r.buf[0:4], r.buf[4:6], r.buf[6]

	if string(identBytes) != wandbHeaderIdent {
		return fmt.Errorf(
			"leveldb/record: invalid W&B identifier: %X (%q)",
			identBytes, identBytes)
	}

	magic := uint16(magicBytes[0]) + uint16(magicBytes[1])<<8
	if magic != wandbHeaderMagic {
		return fmt.Errorf("leveldb/record: invalid W&B magic: %X", magic)
	}

	if version != expectedVersion {
		return fmt.Errorf(
			"leveldb/record: expected W&B version %d but got %d",
			expectedVersion, version)
	}

	return nil
}

// NextOffset returns the offset from which Next() will start to read.
//
// This offset can be passed to SeekRecord to return to the same record in the
// underlying file. If the underlying reader is not seekable or did not start
// at position 0, then the offset is not usable.
func (r *Reader) NextOffset() int64 {
	return r.blockOffset + int64(r.nextChunkStart)
}

// Next returns a reader for the next record.
//
// The second return value is the offset of the record, which can be passed
// to SeekRecord to return to this record in the underlying file. If the
// underlying reader is not seekable or did not start at position 0, then
// the offset is not usable.
//
// The error wraps io.EOF if there are no more records and ErrUnexpectedEOF
// if there's less data than expected based on the first chunk's header.
// The reader does the same. In general, EOF and ErrUnexpectedEOF are returned
// if and only if the error may be resolved by appending more data to the file
// and using SeekRecord to reread the block. Other errors indicate data
// corruption.
//
// The reader becomes stale after the next call to Next() and should no longer
// be used.
func (r *Reader) Next() (io.Reader, error) {
	r.seq++
	if r.err != nil {
		return nil, r.err
	}

	r.err = r.nextChunk(true)
	if r.err != nil {
		return nil, r.err
	}

	return singleReader{r, r.seq}, nil
}

// Recover clears any errors read so far, so that calling Next will start
// reading from the next good 32KiB block. If there are no such blocks, Next
// will return io.EOF. Recover also marks the current reader, the one most
// recently returned by Next, as stale. If Recover is called without any
// prior error, then Recover is a no-op.
func (r *Reader) Recover() {
	if r.err == nil {
		return
	}
	r.recovering = true
	r.err = nil
	// Discard the rest of the current block.
	r.i, r.j, r.last = 0, 0, false
	r.nextChunkStart = r.n
	// Invalidate any outstanding singleReader.
	r.seq++
}

// SeekRecord seeks in the underlying io.Reader such that calling r.Next
// returns the record whose first chunk header starts at the provided offset.
// Its behavior is undefined if the argument given is not such an offset, as
// the bytes at that offset may coincidentally appear to be a valid header.
//
// It returns ErrNotAnIOSeeker if the underlying io.Reader does not implement
// io.Seeker.
//
// SeekRecord will fail and return an error if the Reader previously
// encountered an error, including io.EOF. Such errors can be cleared by
// calling Recover. Calling SeekRecord after Recover will make calling Next
// return the record at the given offset, instead of the record at the next
// good 32KiB block as Recover normally would.
//
// The only other errors possible are those returned by the underlying Seek().
// In particular, for files, Seek() never returns EOF even if seeking past
// the end of a file. In this case, Next() will return EOF.
//
// The offset is always relative to the start of the underlying io.Reader, so
// negative values will result in an error as per io.Seeker.
func (r *Reader) SeekRecord(offset int64) error {
	r.seq++
	if r.err != nil {
		return r.err
	}

	s, ok := r.r.(io.Seeker)
	if !ok {
		return ErrNotAnIOSeeker
	}

	// Clear the state of the internal reader.
	r.i, r.j, r.n = 0, 0, 0
	r.recovering, r.last = false, false

	// Seek to an exact block offset.
	r.nextChunkStart = int(offset & blockSizeMask)
	r.blockOffset = offset &^ blockSizeMask
	_, r.err = s.Seek(r.blockOffset, io.SeekStart)

	return r.err
}

type singleReader struct {
	r   *Reader
	seq int
}

func (x singleReader) Read(p []byte) (int, error) {
	r := x.r
	if r.seq != x.seq {
		return 0, errors.New("leveldb/record: stale reader")
	}
	if r.err != nil {
		return 0, r.err
	}
	for r.i == r.j {
		if r.last {
			return 0, io.EOF
		}

		err := r.nextChunk(false)

		if err != nil {
			// Map EOF to ErrUnexpectedEOF since we expected more chunks.
			if errors.Is(err, io.EOF) {
				r.err = io.ErrUnexpectedEOF
			} else {
				r.err = err
			}
			return 0, r.err
		}
	}
	n := copy(p, r.buf[r.i:r.j])
	r.i += n
	return n, nil
}

// Writer writes records to an underlying io.Writer.
type Writer struct {
	// w is the underlying writer.
	w io.Writer
	// seq is the sequence number of the current record.
	seq int
	// f is w as a flusher.
	f flusher
	// buf[i:j] is the bytes that will become the current chunk.
	// The low bound, i, includes the chunk header.
	i, j int
	// buf[:written] has already been written to w.
	// written is zero unless Flush has been called.
	written int
	// baseOffset is the base offset in w at which writing started. If
	// w implements io.Seeker, it's relative to the start of w, 0 otherwise.
	baseOffset int64
	// blockNumber is the zero based block number currently held in buf.
	blockNumber int64
	// lastRecordOffset is the offset in w where the last record was
	// written (including the chunk header). It is a relative offset to
	// baseOffset, thus the absolute offset of the last record is
	// baseOffset + lastRecordOffset.
	lastRecordOffset int64
	// first is whether the current chunk is the first chunk of the record.
	first bool
	// pending is whether a chunk is buffered but not yet written.
	pending bool
	// err is any accumulated error.
	err error
	// buf is the buffer.
	buf [blockSize]byte
	// CRC function
	crc func([]byte) uint32
}

// NewWriterExt returns a Writer for a new W&B LevelDB file.
//
// W&B LevelDB files start with a W&B header containing a version byte.
func NewWriterExt(w io.Writer, algo CRCAlgo, version byte) *Writer {
	f, _ := w.(flusher)

	var o int64
	if s, ok := w.(io.Seeker); ok {
		var err error
		if o, err = s.Seek(0, io.SeekCurrent); err != nil {
			o = 0
		}
	}
	crc := CRCCustom
	if algo == CRCAlgoIEEE {
		crc = CRCStandard
	}

	writer := &Writer{
		w:                w,
		f:                f,
		baseOffset:       o,
		lastRecordOffset: -1,
		crc:              crc,
	}

	// W&B header: identifier.
	copy(writer.buf[0:4], wandbHeaderIdent)

	// W&B header: little-endian encoding of the magic number.
	writer.buf[4] = wandbHeaderMagic & 0x00FF
	writer.buf[5] = (wandbHeaderMagic & 0xFF00) >> 8

	// W&B header: version.
	writer.buf[6] = version

	// Advance j to indicate that 7 bytes in the buffer contain data.
	writer.j = 7

	return writer
}

// fillHeader fills in the header for the pending chunk.
func (w *Writer) fillHeader(last bool) {
	if w.i+headerSize > w.j || w.j > blockSize {
		panic("leveldb/record: bad writer state")
	}
	if last {
		if w.first {
			w.buf[w.i+6] = fullChunkType
		} else {
			w.buf[w.i+6] = lastChunkType
		}
	} else {
		if w.first {
			w.buf[w.i+6] = firstChunkType
		} else {
			w.buf[w.i+6] = middleChunkType
		}
	}
	binary.LittleEndian.PutUint32(w.buf[w.i+0:w.i+4], w.crc(w.buf[w.i+6:w.j]))
	binary.LittleEndian.PutUint16(w.buf[w.i+4:w.i+6], uint16(w.j-w.i-headerSize))
}

// writeBlock writes the buffered block to the underlying writer, and reserves
// space for the next chunk's header.
func (w *Writer) writeBlock() {
	_, w.err = w.w.Write(w.buf[w.written:])
	w.i = 0
	w.j = headerSize
	w.written = 0
	w.blockNumber++
}

// writePending finishes the current record and writes the buffer to the
// underlying writer.
func (w *Writer) writePending() {
	if w.err != nil {
		return
	}
	if w.pending {
		w.fillHeader(true)
		w.pending = false
	}
	_, w.err = w.w.Write(w.buf[w.written:w.j])
	w.written = w.j
}

// Close finishes the current record and closes the writer.
func (w *Writer) Close() error {
	w.seq++
	w.writePending()
	if w.err != nil {
		return w.err
	}
	w.err = errors.New("leveldb/record: closed Writer")
	return nil
}

// Flush finishes the current record, writes to the underlying writer, and
// flushes it if that writer implements interface{ Flush() error }.
func (w *Writer) Flush() error {
	w.seq++
	w.writePending()
	if w.err != nil {
		return w.err
	}
	if w.f != nil {
		w.err = w.f.Flush()
		return w.err
	}
	return nil
}

// Next returns a writer for the next record. The writer returned becomes stale
// after the next Close, Flush or Next call, and should no longer be used.
func (w *Writer) Next() (io.Writer, error) {
	w.seq++
	if w.err != nil {
		return nil, w.err
	}
	if w.pending {
		w.fillHeader(true)
	}
	w.i = w.j
	w.j += headerSize
	// Check if there is room in the block for the header.
	if w.j > blockSize {
		// Fill in the rest of the block with zeroes.
		for k := w.i; k < blockSize; k++ {
			w.buf[k] = 0
		}
		w.writeBlock()
		if w.err != nil {
			return nil, w.err
		}
	}
	w.lastRecordOffset = w.baseOffset + w.blockNumber*blockSize + int64(w.i)
	w.first = true
	w.pending = true
	return singleWriter{w, w.seq}, nil
}

// LastRecordOffset returns the offset in the underlying io.Writer of the last
// record so far - the one created by the most recent Next call. It is the
// offset of the first chunk header, suitable to pass to Reader.SeekRecord.
//
// If that io.Writer also implements io.Seeker, the return value is an absolute
// offset, in the sense of io.SeekStart, regardless of whether the io.Writer
// was initially at the zero position when passed to NewWriter. Otherwise, the
// return value is a relative offset, being the number of bytes written between
// the NewWriter call and any records written prior to the last record.
//
// If there is no last record, i.e. nothing was written, LastRecordOffset will
// return ErrNoLastRecord.
func (w *Writer) LastRecordOffset() (int64, error) {
	if w.err != nil {
		return 0, w.err
	}
	if w.lastRecordOffset < 0 {
		return 0, ErrNoLastRecord
	}
	return w.lastRecordOffset, nil
}

type singleWriter struct {
	w   *Writer
	seq int
}

func (x singleWriter) Write(p []byte) (int, error) {
	w := x.w
	if w.seq != x.seq {
		return 0, errors.New("leveldb/record: stale writer")
	}
	if w.err != nil {
		return 0, w.err
	}
	n0 := len(p)
	for len(p) > 0 {
		// Write a block, if it is full.
		if w.j == blockSize {
			w.fillHeader(false)
			w.writeBlock()
			if w.err != nil {
				return 0, w.err
			}
			w.first = false
		}
		// Copy bytes into the buffer.
		n := copy(w.buf[w.j:], p)
		w.j += n
		p = p[n:]
	}
	return n0, nil
}
