package transactionlog

import (
	"io"
	"slices"
)

// BufferedReadSeeker wraps an io.ReadSeeker to buffer data near its end
// to allow for efficient rereading.
type BufferedReadSeeker struct {
	reader io.ReadSeeker

	// buf contains the data from the end of the reader.
	buf []byte

	// bufStart and bufEnd define the range of bytes in the reader that
	// is buffered in buf. Their difference equals the length of buf.
	bufStart, bufEnd int64

	// pos <= readerEnd store the reading position and the reader's actual
	// position.
	//
	// If pos is not between bufStart and bufEnd, then it equals readerEnd.
	pos, readerEnd int64
}

func NewBufferedReadSeeker(
	reader io.ReadSeeker,
	readerPos int64,
) *BufferedReadSeeker {
	return &BufferedReadSeeker{
		reader:    reader,
		bufStart:  readerPos,
		bufEnd:    readerPos,
		pos:       readerPos,
		readerEnd: readerPos,
	}
}

// SetSeekCutoff indicates the data before the offset will not be sought
// and need not be buffered.
//
// This may free some buffer capacity.
//
// Seeking to before the offset is still allowed but may not benefit from
// buffering.
func (r *BufferedReadSeeker) SetSeekCutoff(offset int64) {
	newStart := min(offset, r.bufEnd)
	if newStart <= r.bufStart || newStart > r.pos {
		return
	}

	// Amortize discarding similarly to how append() amortizes allocations.
	nDiscard := int(newStart - r.bufStart)
	if 2*nDiscard < len(r.buf) {
		return
	}

	r.buf = slices.Clone(r.buf[nDiscard:])
	r.bufStart = newStart
}

// Read implements io.Reader.Read.
func (r *BufferedReadSeeker) Read(p []byte) (n int, err error) {
	// Return buffered data if we're in the buffered region.
	if r.bufStart <= r.pos && r.pos < r.bufEnd {
		start := int(r.pos - r.bufStart)
		n = copy(p, r.buf[start:])
		r.pos += int64(n)
		return
	}

	// Ensure bufEnd == readerEnd so that we can append new data to the buffer.
	if r.bufEnd != r.readerEnd {
		r.buf = nil
		r.bufStart, r.bufEnd = r.readerEnd, r.readerEnd
	}

	n, err = r.reader.Read(p)

	// Since pos was not inside the buffered region, pos == readerEnd.
	r.readerEnd += int64(n)
	r.pos = r.readerEnd

	// Append new data to the buffer.
	r.buf = append(r.buf, p[:n]...)
	r.bufEnd = r.readerEnd

	return
}

// Seek implements io.Seeker.Seek.
func (r *BufferedReadSeeker) Seek(offset int64, whence int) (int64, error) {
	var targetOffset int64
	switch whence {
	case io.SeekStart:
		targetOffset = offset
	case io.SeekCurrent:
		targetOffset = r.readerEnd + offset
	case io.SeekEnd:
		targetOffset = r.readerEnd - offset
	}

	// Skip IO when seeking to a buffered region.
	if r.bufStart <= targetOffset && targetOffset <= r.bufEnd {
		r.pos = targetOffset
		return r.pos, nil
	}

	o, err := r.reader.Seek(offset, whence)
	r.pos = o
	r.readerEnd = o
	return r.pos, err
}

// Close implements io.Closer.Close.
func (r *BufferedReadSeeker) Close() error {
	if closer, ok := r.reader.(io.Closer); ok {
		return closer.Close()
	}

	return nil
}
