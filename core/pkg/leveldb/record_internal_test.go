// Copyright 2011 The LevelDB-Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

package leveldb

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"strings"
	"testing"
)

func short(s string) string {
	if len(s) < 64 {
		return s
	}
	return fmt.Sprintf("%s...(skipping %d bytes)...%s", s[:20], len(s)-40, s[len(s)-20:])
}

// big returns a string of length n, composed of repetitions of partial.
func big(partial string, n int) string {
	return strings.Repeat(partial, n/len(partial)+1)[:n]
}

// TestZeroBlocks tests that reading nothing but all-zero blocks gives io.EOF.
// This includes decoding an empty stream.
func TestZeroBlocks(t *testing.T) {
	for i := 0; i < 3; i++ {
		r := NewReader(bytes.NewReader(make([]byte, i*blockSize)))
		if _, err := r.Next(); err != io.EOF {
			t.Fatalf("%d blocks: got %v, want %v", i, err, io.EOF)
		}
	}
}

func testGenerator(t *testing.T, reset func(), gen func() (string, bool)) {
	buf := new(bytes.Buffer)

	reset()
	w := NewWriter(buf)
	for {
		s, ok := gen()
		if !ok {
			break
		}
		ww, err := w.Next()
		if err != nil {
			t.Fatalf("writer.Next: %v", err)
		}
		if _, err := ww.Write([]byte(s)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	reset()
	r := NewReader(buf)
	for {
		s, ok := gen()
		if !ok {
			break
		}
		rr, err := r.Next()
		if err != nil {
			t.Fatalf("reader.Next: %v", err)
		}
		x, err := io.ReadAll(rr)
		if err != nil {
			t.Fatalf("ReadAll: %v", err)
		}
		if string(x) != s {
			t.Fatalf("got %q, want %q", short(string(x)), short(s))
		}
	}
	if _, err := r.Next(); err != io.EOF {
		t.Fatalf("got %v, want %v", err, io.EOF)
	}
}

func testLiterals(t *testing.T, s []string) {
	var i int
	reset := func() {
		i = 0
	}
	gen := func() (string, bool) {
		if i == len(s) {
			return "", false
		}
		i++
		return s[i-1], true
	}
	testGenerator(t, reset, gen)
}

func TestMany(t *testing.T) {
	const n = 1e5
	var i int
	reset := func() {
		i = 0
	}
	gen := func() (string, bool) {
		if i == n {
			return "", false
		}
		i++
		return fmt.Sprintf("%d.", i-1), true
	}
	testGenerator(t, reset, gen)
}

func TestRandom(t *testing.T) {
	const n = 1e2
	var (
		i int
		r *rand.Rand
	)
	reset := func() {
		i, r = 0, rand.New(rand.NewSource(0))
	}
	gen := func() (string, bool) {
		if i == n {
			return "", false
		}
		i++
		return strings.Repeat(string(uint8(i)), r.Intn(2*blockSize+16)), true
	}
	testGenerator(t, reset, gen)
}

func TestBasic(t *testing.T) {
	testLiterals(t, []string{
		strings.Repeat("a", 1000),
		strings.Repeat("b", 97270),
		strings.Repeat("c", 8000),
	})
}

func TestBoundary(t *testing.T) {
	for i := blockSize - 16; i < blockSize+16; i++ {
		s0 := big("abcd", i)
		for j := blockSize - 16; j < blockSize+16; j++ {
			s1 := big("ABCDE", j)
			testLiterals(t, []string{s0, s1})
			testLiterals(t, []string{s0, "", s1})
			testLiterals(t, []string{s0, "x", s1})
		}
	}
}

func TestFlush(t *testing.T) {
	buf := new(bytes.Buffer)
	w := NewWriter(buf)
	// Write a couple of records. Everything should still be held
	// in the record.Writer buffer, so that buf.Len should be 0.
	w0, _ := w.Next()
	_, _ = w0.Write([]byte("0"))
	w1, _ := w.Next()
	_, _ = w1.Write([]byte("11"))
	if got, want := buf.Len(), 0; got != want {
		t.Fatalf("buffer length #0: got %d want %d", got, want)
	}
	// Flush the record.Writer buffer, which should yield 17 bytes.
	// 17 = 2*7 + 1 + 2, which is two headers and 1 + 2 payload bytes.
	if err := w.Flush(); err != nil {
		t.Fatal(err)
	}
	if got, want := buf.Len(), 17; got != want {
		t.Fatalf("buffer length #1: got %d want %d", got, want)
	}
	// Do another write, one that isn't large enough to complete the block.
	// The write should not have flowed through to buf.
	w2, _ := w.Next()
	_, _ = w2.Write(bytes.Repeat([]byte("2"), 10000))
	if got, want := buf.Len(), 17; got != want {
		t.Fatalf("buffer length #2: got %d want %d", got, want)
	}
	// Flushing should get us up to 10024 bytes written.
	// 10024 = 17 + 7 + 10000.
	if err := w.Flush(); err != nil {
		t.Fatal(err)
	}
	if got, want := buf.Len(), 10024; got != want {
		t.Fatalf("buffer length #3: got %d want %d", got, want)
	}
	// Do a bigger write, one that completes the current block.
	// We should now have 32768 bytes (a complete block), without
	// an explicit flush.
	w3, _ := w.Next()
	_, _ = w3.Write(bytes.Repeat([]byte("3"), 40000))
	if got, want := buf.Len(), 32768; got != want {
		t.Fatalf("buffer length #4: got %d want %d", got, want)
	}
	// Flushing should get us up to 50038 bytes written.
	// 50038 = 10024 + 2*7 + 40000. There are two headers because
	// the one record was split into two chunks.
	if err := w.Flush(); err != nil {
		t.Fatal(err)
	}
	if got, want := buf.Len(), 50038; got != want {
		t.Fatalf("buffer length #5: got %d want %d", got, want)
	}
	// Check that reading those records give the right lengths.
	r := NewReader(buf)
	wants := []int64{1, 2, 10000, 40000}
	for i, want := range wants {
		rr, _ := r.Next()
		n, err := io.Copy(io.Discard, rr)
		if err != nil {
			t.Fatalf("read #%d: %v", i, err)
		}
		if n != want {
			t.Fatalf("read #%d: got %d bytes want %d", i, n, want)
		}
	}
}

func TestNonExhaustiveRead(t *testing.T) {
	const n = 100
	buf := new(bytes.Buffer)
	p := make([]byte, 10)
	rnd := rand.New(rand.NewSource(1))

	w := NewWriter(buf)
	for i := 0; i < n; i++ {
		length := len(p) + rnd.Intn(3*blockSize)
		s := string(uint8(i)) + "123456789abcdefgh"
		ww, _ := w.Next()
		_, _ = ww.Write([]byte(big(s, length)))
	}
	if err := w.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	r := NewReader(buf)
	for i := 0; i < n; i++ {
		rr, _ := r.Next()
		_, err := io.ReadFull(rr, p)
		if err != nil {
			t.Fatalf("ReadFull: %v", err)
		}
		want := string(uint8(i)) + "123456789"
		if got := string(p); got != want {
			t.Fatalf("read #%d: got %q want %q", i, got, want)
		}
	}
}

func TestStaleReader(t *testing.T) {
	buf := new(bytes.Buffer)

	w := NewWriter(buf)
	w0, err := w.Next()
	if err != nil {
		t.Fatalf("writer.Next: %v", err)
	}
	_, _ = w0.Write([]byte("0"))
	w1, err := w.Next()
	if err != nil {
		t.Fatalf("writer.Next: %v", err)
	}
	_, _ = w1.Write([]byte("11"))
	if err := w.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}

	r := NewReader(buf)
	r0, err := r.Next()
	if err != nil {
		t.Fatalf("reader.Next: %v", err)
	}
	r1, err := r.Next()
	if err != nil {
		t.Fatalf("reader.Next: %v", err)
	}
	p := make([]byte, 1)
	if _, err := r0.Read(p); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("stale read #0: unexpected error: %v", err)
	}
	if _, err := r1.Read(p); err != nil {
		t.Fatalf("fresh read #1: got %v want nil error", err)
	}
	if p[0] != '1' {
		t.Fatalf("fresh read #1: byte contents: got '%c' want '1'", p[0])
	}
}

func TestStaleWriter(t *testing.T) {
	buf := new(bytes.Buffer)

	w := NewWriter(buf)
	w0, err := w.Next()
	if err != nil {
		t.Fatalf("writer.Next: %v", err)
	}
	w1, err := w.Next()
	if err != nil {
		t.Fatalf("writer.Next: %v", err)
	}
	if _, err := w0.Write([]byte("0")); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("stale write #0: unexpected error: %v", err)
	}
	if _, err := w1.Write([]byte("11")); err != nil {
		t.Fatalf("fresh write #1: got %v want nil error", err)
	}
	if err := w.Flush(); err != nil {
		t.Fatalf("flush: %v", err)
	}
	if _, err := w1.Write([]byte("0")); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("stale write #1: unexpected error: %v", err)
	}
}

type testRecords struct {
	records [][]byte // The raw value of each record.
	offsets []int64  // The offset of each record within buf, derived from writer.LastRecordOffset.
	buf     []byte   // The serialized records form of all records.
}

// makeTestRecords generates test records of specified lengths.
// The first record will consist of repeating 0x00 bytes, the next record of
// 0x01 bytes, and so forth. The values will loop back to 0x00 after 0xff.
func makeTestRecords(recordLengths ...int) (*testRecords, error) {
	ret := &testRecords{}
	ret.records = make([][]byte, len(recordLengths))
	ret.offsets = make([]int64, len(recordLengths))
	for i, n := range recordLengths {
		ret.records[i] = bytes.Repeat([]byte{byte(i)}, n)
	}

	buf := new(bytes.Buffer)
	w := NewWriter(buf)
	for i, rec := range ret.records {
		wRec, err := w.Next()
		if err != nil {
			return nil, err
		}

		// Alternate between one big write and many small writes.
		cSize := 8
		if i&1 == 0 {
			cSize = len(rec)
		}
		for ; len(rec) > cSize; rec = rec[cSize:] {
			if _, err = wRec.Write(rec[:cSize]); err != nil {
				return nil, err
			}
		}
		if _, err = wRec.Write(rec); err != nil {
			return nil, err
		}

		ret.offsets[i], err = w.LastRecordOffset()
		if err != nil {
			return nil, err
		}
	}

	if err := w.Close(); err != nil {
		return nil, err
	}

	ret.buf = buf.Bytes()
	return ret, nil
}

// corruptBlock corrupts the checksum of the record that starts at the
// specified block offset. The number of the block offset is 0 based.
func corruptBlock(buf []byte, blockNum int) {
	// Ensure we always permute at least 1 byte of the checksum.
	if buf[blockSize*blockNum] == 0x00 {
		buf[blockSize*blockNum] = 0xff
	} else {
		buf[blockSize*blockNum] = 0x00
	}

	buf[blockSize*blockNum+1] = 0x00
	buf[blockSize*blockNum+2] = 0x00
	buf[blockSize*blockNum+3] = 0x00
}

func TestRecoverNoOp(t *testing.T) {
	recs, err := makeTestRecords(
		blockSize-headerSize,
		blockSize-headerSize,
		blockSize-headerSize,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	r := NewReader(bytes.NewReader(recs.buf))
	_, err = r.Next()
	if err != nil || r.err != nil {
		t.Fatalf("reader.Next: %v reader.err: %v", err, r.err)
	}

	seq, i, j, n := r.seq, r.i, r.j, r.n

	// Should be a no-op since r.err == nil.
	r.Recover()

	// r.err was nil, nothing should have changed.
	if seq != r.seq || i != r.i || j != r.j || n != r.n {
		t.Fatal("reader.Recover when no error existed, was not a no-op")
	}
}

func TestBasicRecover(t *testing.T) {
	recs, err := makeTestRecords(
		blockSize-headerSize,
		blockSize-headerSize,
		blockSize-headerSize,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	// Corrupt the checksum of the second record r1 in our file.
	corruptBlock(recs.buf, 1)

	underlyingReader := bytes.NewReader(recs.buf)
	r := NewReader(underlyingReader)

	// The first record r0 should be read just fine.
	r0, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}
	r0Data, err := io.ReadAll(r0)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if !bytes.Equal(r0Data, recs.records[0]) {
		t.Fatal("Unexpected output in r0's data")
	}

	// The next record should have a checksum mismatch.
	_, err = r.Next()
	if err == nil {
		t.Fatal("Expected an error while reading a corrupted record")
	}
	if !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("Unexpected error returned: %v", err)
	}

	// Recover from that checksum mismatch.
	r.Recover()
	currentOffset, err := underlyingReader.Seek(0, io.SeekCurrent)
	if err != nil {
		t.Fatalf("current offset: %v", err)
	}
	if currentOffset != blockSize*2 {
		t.Fatalf("current offset: got %d, want %d", currentOffset, blockSize*2)
	}

	// The third record r2 should be read just fine.
	r2, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}
	r2Data, err := io.ReadAll(r2)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if !bytes.Equal(r2Data, recs.records[2]) {
		t.Fatal("Unexpected output in r2's data")
	}
}

func TestRecoverSingleBlock(t *testing.T) {
	// The first record will be blockSize * 3 bytes long. Since each block has
	// a 7 byte header, the first record will roll over into 4 blocks.
	recs, err := makeTestRecords(
		blockSize*3,
		blockSize-headerSize,
		blockSize/2,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	// Corrupt the checksum for the portion of the first record that exists in
	// the 4th block.
	corruptBlock(recs.buf, 3)

	// The first record should fail, but only when we read deeper beyond the
	// first block.
	r := NewReader(bytes.NewReader(recs.buf))
	r0, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}

	// Reading deeper should yield a checksum mismatch.
	_, err = io.ReadAll(r0)
	if err == nil {
		t.Fatal("Expected a checksum mismatch error, got nil")
	}
	if !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("Unexpected error returned: %v", err)
	}

	// Recover from that checksum mismatch.
	r.Recover()

	// All of the data in the second record r1 is lost because the first record
	// r0 shared a partial block with it. The second record also overlapped
	// into the block with the third record r2. Recovery should jump to that
	// block, skipping over the end of the second record and start parsing the
	// third record.
	r2, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}
	r2Data, _ := io.ReadAll(r2)
	if !bytes.Equal(r2Data, recs.records[2]) {
		t.Fatal("Unexpected output in r2's data")
	}
}

func TestRecoverMultipleBlocks(t *testing.T) {
	recs, err := makeTestRecords(
		// The first record will consume 3 entire blocks but a fraction of the 4th.
		blockSize*3,
		// The second record will completely fill the remainder of the 4th block.
		3*(blockSize-headerSize)-2*blockSize-2*headerSize,
		// Consume the entirety of the 5th block.
		blockSize-headerSize,
		// Consume the entirety of the 6th block.
		blockSize-headerSize,
		// Consume roughly half of the 7th block.
		blockSize/2,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	// Corrupt the checksum for the portion of the first record that exists in the 4th block.
	corruptBlock(recs.buf, 3)

	// Now corrupt the two blocks in a row that correspond to recs.records[2:4].
	corruptBlock(recs.buf, 4)
	corruptBlock(recs.buf, 5)

	// The first record should fail, but only when we read deeper beyond the first block.
	r := NewReader(bytes.NewReader(recs.buf))
	r0, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}

	// Reading deeper should yield a checksum mismatch.
	_, err = io.ReadAll(r0)
	if err == nil {
		t.Fatal("Expected a checksum mismatch error, got nil")
	}
	if !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("Unexpected error returned: %v", err)
	}

	// Recover from that checksum mismatch.
	r.Recover()

	// All of the data in the second record is lost because the first
	// record shared a partial block with it. The following two records
	// have corrupted checksums as well, so the call above to r.Recover
	// should result in r.Next() being a reader to the 5th record.
	r4, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}

	r4Data, _ := io.ReadAll(r4)
	if !bytes.Equal(r4Data, recs.records[4]) {
		t.Fatal("Unexpected output in r4's data")
	}
}

// verifyLastBlockRecover reads each record from recs expecting that the
// last record will be corrupted. It will then try Recover and verify that EOF
// is returned.
func verifyLastBlockRecover(recs *testRecords) error {
	r := NewReader(bytes.NewReader(recs.buf))
	// Loop to one element larger than the number of records to verify EOF.
	for i := 0; i < len(recs.records)+1; i++ {
		_, err := r.Next()
		switch i {
		case len(recs.records) - 1:
			if err == nil {
				return errors.New("Expected a checksum mismatch error, got nil")
			}
			r.Recover()
		case len(recs.records):
			if err != io.EOF {
				return fmt.Errorf("Expected io.EOF, got %v", err)
			}
		default:
			if err != nil {
				return fmt.Errorf("Next: %v", err)
			}
		}
	}
	return nil
}

func TestRecoverLastPartialBlock(t *testing.T) {
	recs, err := makeTestRecords(
		// The first record will consume 3 entire blocks but a fraction of the 4th.
		blockSize*3,
		// The second record will completely fill the remainder of the 4th block.
		3*(blockSize-headerSize)-2*blockSize-2*headerSize,
		// Consume roughly half of the 5th block.
		blockSize/2,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	// Corrupt the 5th block.
	corruptBlock(recs.buf, 4)

	// Verify Recover works when the last block is corrupted.
	if err := verifyLastBlockRecover(recs); err != nil {
		t.Fatalf("verifyLastBlockRecover: %v", err)
	}
}

func TestRecoverLastCompleteBlock(t *testing.T) {
	recs, err := makeTestRecords(
		// The first record will consume 3 entire blocks but a fraction of the 4th.
		blockSize*3,
		// The second record will completely fill the remainder of the 4th block.
		3*(blockSize-headerSize)-2*blockSize-2*headerSize,
		// Consume the entire 5th block.
		blockSize-headerSize,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	// Corrupt the 5th block.
	corruptBlock(recs.buf, 4)

	// Verify Recover works when the last block is corrupted.
	if err := verifyLastBlockRecover(recs); err != nil {
		t.Fatalf("verifyLastBlockRecover: %v", err)
	}
}

func TestSeekRecord(t *testing.T) {
	recs, err := makeTestRecords(
		// The first record will consume 3 entire blocks but a fraction of the 4th.
		blockSize*3,
		// The second record will completely fill the remainder of the 4th block.
		3*(blockSize-headerSize)-2*blockSize-2*headerSize,
		// Consume the entirety of the 5th block.
		blockSize-headerSize,
		// Consume the entirety of the 6th block.
		blockSize-headerSize,
		// Consume roughly half of the 7th block.
		blockSize/2,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	r := NewReader(bytes.NewReader(recs.buf))
	// Seek to a valid block offset, but within a multiblock record. This should cause the next call to
	// Next after SeekRecord to return the next valid FIRST/FULL chunk of the subsequent record.
	err = r.SeekRecord(blockSize)
	if err != nil {
		t.Fatalf("SeekRecord: %v", err)
	}
	rec, err := r.Next()
	if err != nil {
		t.Fatalf("Next: %v", err)
	}
	rData, _ := io.ReadAll(rec)
	if !bytes.Equal(rData, recs.records[1]) {
		t.Fatalf("Unexpected output in record 1's data, got %v want %v", rData, recs.records[1])
	}

	// Seek 3 bytes into the second block, which is still in the middle of the first record, but not
	// at a valid chunk boundary. Should result in an error upon calling r.Next.
	err = r.SeekRecord(blockSize + 3)
	if err != nil {
		t.Fatalf("SeekRecord: %v", err)
	}
	if _, err = r.Next(); err == nil {
		t.Fatalf("Expected an error seeking to an invalid chunk boundary")
	}
	r.Recover()

	// Seek to the fifth block and verify all records can be read as appropriate.
	err = r.SeekRecord(blockSize * 4)
	if err != nil {
		t.Fatalf("SeekRecord: %v", err)
	}

	check := func(i int) {
		for ; i < len(recs.records); i++ {
			rec, err := r.Next()
			if err != nil {
				t.Fatalf("Next: %v", err)
			}

			rData, _ := io.ReadAll(rec)
			if !bytes.Equal(rData, recs.records[i]) {
				t.Fatalf("Unexpected output in record #%d's data, got %v want %v", i, rData, recs.records[i])
			}
		}
	}
	check(2)

	// Seek back to the fourth block, and read all subsequent records and verify them.
	err = r.SeekRecord(blockSize * 3)
	if err != nil {
		t.Fatalf("SeekRecord: %v", err)
	}
	check(1)

	// Now seek past the end of the file and verify it causes an error.
	err = r.SeekRecord(1 << 20)
	if err == nil {
		t.Fatalf("Seek past the end of a file didn't cause an error")
	}
	if err != io.EOF {
		t.Fatalf("Seeking past EOF raised unexpected error: %v", err)
	}
	r.Recover() // Verify recovery works.

	// Validate the current records are returned after seeking to a valid offset.
	err = r.SeekRecord(blockSize * 4)
	if err != nil {
		t.Fatalf("SeekRecord: %v", err)
	}
	check(2)
}

func TestLastRecordOffset(t *testing.T) {
	recs, err := makeTestRecords(
		// The first record will consume 3 entire blocks but a fraction of the 4th.
		blockSize*3,
		// The second record will completely fill the remainder of the 4th block.
		3*(blockSize-headerSize)-2*blockSize-2*headerSize,
		// Consume the entirety of the 5th block.
		blockSize-headerSize,
		// Consume the entirety of the 6th block.
		blockSize-headerSize,
		// Consume roughly half of the 7th block.
		blockSize/2,
	)
	if err != nil {
		t.Fatalf("makeTestRecords: %v", err)
	}

	wants := []int64{0, 98332, 131072, 163840, 196608}
	for i, got := range recs.offsets {
		if want := wants[i]; got != want {
			t.Errorf("record #%d: got %d, want %d", i, got, want)
		}
	}
}

func TestNoLastRecordOffset(t *testing.T) {
	buf := new(bytes.Buffer)
	w := NewWriter(buf)

	if _, err := w.LastRecordOffset(); err != ErrNoLastRecord {
		t.Fatalf("Expected ErrNoLastRecord, got: %v", err)
	}

	if err := w.Flush(); err != nil {
		t.Fatal(err)
	}

	if _, err := w.LastRecordOffset(); err != ErrNoLastRecord {
		t.Fatalf("LastRecordOffset: got: %v, want ErrNoLastRecord", err)
	}

	writer, err := w.Next()
	if err != nil {
		t.Fatal(err)
	}

	if _, err := writer.Write([]byte("testrecord")); err != nil {
		t.Fatal(err)
	}

	if off, err := w.LastRecordOffset(); err != nil {
		t.Fatalf("LastRecordOffset: %v", err)
	} else if off != 0 {
		t.Fatalf("LastRecordOffset: got %d, want 0", off)
	}
}

// header read on a short data file just gets an incomplete header
func TestHeaderShort(t *testing.T) {
	data := []byte("hello")
	r := NewReader(bytes.NewReader(data))
	header := make([]byte, 7)
	err := r.ReadHeader(header)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.HasPrefix(header, data) {
		t.Fatalf("header invalid: %+v", header)
	}
}

// add a header and a single chunk o f data, read back header and record
func TestHeaderNormal(t *testing.T) {
	buf := new(bytes.Buffer)
	headerWrite := []byte("header")
	w := NewWriterExt(buf, CRCAlgoIEEE, headerWrite)

	// write a good record
	w1, _ := w.Next()
	_, _ = w1.Write([]byte("junk1"))

	if err := w.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	header := make([]byte, 6)
	r := NewReaderExt(buf, CRCAlgoIEEE)
	if err := r.ReadHeader(header); err != nil {
		t.Fatal(err)
	}
	if !bytes.HasPrefix(header, headerWrite) {
		t.Fatalf("header invalid: %+v", header)
	}

	r1, err := r.Next()
	if err != nil {
		t.Fatal(err)
	}

	p := make([]byte, 10)
	if _, err := r1.Read(p); err != nil {
		t.Fatal(err)
	}

	if !bytes.HasPrefix(p, []byte("junk1")) {
		t.Fatalf("data invalid: %+v", p)
	}

	// No more
	_, err = r.Next()
	if err != io.EOF {
		t.Fatal(err)
	}
}
