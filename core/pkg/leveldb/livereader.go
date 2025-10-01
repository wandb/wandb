package leveldb

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
)

// LiveReader reads records from a W&B LevelDB-style log that may be actively written.
// It is NOT safe for concurrent use.
type LiveReader struct {
	// f is the underlying LevelDB-style log.
	f io.ReaderAt
	// Cyclic redundancy check function.
	crc func([]byte) uint32
	// nextOff is the absolute position where we expect the next record's first chunk header.
	nextOff int64
	// processedFirstBlock indicates whether the first block has been read and validated.
	// The first block needs special handling because of the W&B header.
	processedFirstBlock bool
}

func NewLiveReader(r *os.File, algo CRCAlgo) *LiveReader {
	crc := CRCCustom
	if algo == CRCAlgoIEEE {
		crc = CRCStandard
	}
	return &LiveReader{f: r, crc: crc}
}

// VerifyWandbHeader validates the 7-byte W&B file header and positions the reader
// to the first chunk (offset = 7). After success, Next() starts from there.
func (r *LiveReader) VerifyWandbHeader(expectedVersion byte) error {
	if r.processedFirstBlock {
		return nil
	}
	var hdr [wandbHeaderLength]byte

	n, err := r.f.ReadAt(hdr[:], 0)
	if err != nil && !errors.Is(err, io.EOF) {
		return fmt.Errorf("livereader: reading W&B header: %w", err)
	}
	if n < wandbHeaderLength {
		// File exists but is not fully initialized yet; treat as incomplete.
		return io.EOF
	}

	ident := string(hdr[0:4])
	magic := uint16(hdr[4]) | uint16(hdr[5])<<8
	version := hdr[6]

	if ident != wandbHeaderIdent {
		return fmt.Errorf("livereader: invalid W&B ident: %X (%q)", ident, ident)
	}
	if magic != wandbHeaderMagic {
		return fmt.Errorf("livereader: invalid W&B magic: 0x%X", magic)
	}
	if version != expectedVersion {
		return fmt.Errorf("livereader: expected W&B version %d, got %d", expectedVersion, version)
	}

	r.nextOff = wandbHeaderLength
	r.processedFirstBlock = true
	return nil
}

// Next returns an io.Reader for the next complete record. If no complete record
// is available *yet* (the file is still being written), it returns io.EOF WITHOUT
// advancing r.nextOff. Call again when the file grows.
//
//gocyclo:ignore
func (r *LiveReader) Next() (io.Reader, error) {
	if !r.processedFirstBlock {
		if err := r.VerifyWandbHeader(0); err != nil {
			return nil, err
		}
	}

	// cur is a transient cursor; commit to nextOff ONLY after we fully build a record.
	cur := r.nextOff

	var rec bytes.Buffer
	wantFirst := true

	for {
		// If not enough bytes for a header in this block, skip to next block boundary.
		inblock := int(cur & blockSizeMask)
		if inblock+headerSize > blockSize {
			cur = (cur &^ int64(blockSizeMask)) + blockSize
			continue
		}

		// Read header.
		var h [headerSize]byte
		if err := r.readAtExactly(h[:], cur); err != nil {
			return nil, err
		}
		checksum := binary.LittleEndian.Uint32(h[0:4])
		length := binary.LittleEndian.Uint16(h[4:6])
		ctype := h[6]

		// Zeroed header often means unused block space (padding) or not-yet-written area.
		if checksum == 0 && length == 0 && ctype == 0 {
			// Move to next block boundary (do not commit nextOff).
			cur = (cur &^ int64(blockSizeMask)) + blockSize
			continue
		}

		// Validate chunk type expectations.
		if wantFirst && ctype != fullChunkType && ctype != firstChunkType {
			// We expected FULL or FIRST at the start of a record. Since we only ever
			// start reading at a committed nextOff, this is very unlikely unless the
			// writer was mid-write. Treat as incomplete.
			return nil, io.EOF
		}

		// Check block overflow.
		blockEnd := (cur &^ int64(blockSizeMask)) + blockSize
		maxLen := int(blockEnd - (cur + headerSize))
		if int(length) > maxLen {
			// A valid writer never produces this. If we see it at the tail, assume incomplete.
			return nil, io.EOF
		}

		// Ensure payload fully available in the file.
		payloadOff := cur + headerSize
		payloadEnd := payloadOff + int64(length)

		// Read payload.
		buf := make([]byte, length)
		if err := r.readAtExactly(buf, payloadOff); err != nil {
			return nil, err
		}

		// CRC over [type || payload].
		crcInput := append([]byte{ctype}, buf...)
		got := r.crc(crcInput)
		if got != checksum {
			// Near the tail this often means "writer hasn't finished"; treat as incomplete.
			return nil, io.EOF
		}

		// Accumulate and advance.
		rec.Write(buf)
		cur = payloadEnd

		switch ctype {
		case fullChunkType:
			// Commit and return.
			r.nextOff = cur
			return bytes.NewReader(rec.Bytes()), nil

		case firstChunkType:
			wantFirst = false
			// Continue to MIDDLE/LAST.

		case middleChunkType:
			// Only valid after FIRST.
			if wantFirst {
				// Unexpected; treat as incomplete.
				return nil, io.EOF
			}

		case lastChunkType:
			// Record finished; commit and return.
			r.nextOff = cur
			return bytes.NewReader(rec.Bytes()), nil

		default:
			// Unknown type; near the tail, assume incomplete.
			return nil, io.EOF
		}
	}
}

func (r *LiveReader) readAtExactly(p []byte, off int64) error {
	n, err := r.f.ReadAt(p, off)
	switch {
	case n == len(p):
		return nil
	case errors.Is(err, io.ErrUnexpectedEOF):
		// An EOF is never unexpected: we assume the file may be incomplete.
		return io.EOF
	case err != nil:
		return err
	default:
		// By the contract of ReadAt, this is not possible:
		// err must be non-nil if n != len(p).
		return errors.New("ReadAt was short but err was nil")
	}
}
