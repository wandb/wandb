package transfermanager

import (
	"bytes"
	"context"
	"fmt"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/middleware"
	"github.com/aws/aws-sdk-go-v2/feature/s3/transfermanager/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"io"
	"sync"
	"sync/atomic"
)

// concurrentReader receives object parts from working goroutines, composes those chunks in order and read
// to user's buffer. ConcurrentReader limits the max number of chunks it could receive and read at the same
// time so getter won't send following parts' request to s3 until user reads all current chunks, which avoids
// too much memory consumption when caching large object parts
type concurrentReader struct {
	ch      chan outChunk
	buf     map[int32]*outChunk
	options Options
	in      *GetObjectInput

	pos          int64
	partsCount   int32
	capacity     int32
	sectionParts int32
	sendCount    int32
	receiveCount int32
	readCount    int32
	totalBytes   int64
	index        int32
	done         bool
	written      int64
	partSize     int64
	invocations  int32
	etag         *string

	ctx context.Context
	m   sync.Mutex
	wg  sync.WaitGroup

	err error
}

// Read implements io.Reader to compose object parts in order and read to p.
// It will receive up to r.capacity chunks, read them to p if any chunk index
// fits into p scope, otherwise it will buffer those chunks and read them in
// following calls
func (r *concurrentReader) Read(p []byte) (int, error) {
	clientOptions := []func(*s3.Options){
		func(o *s3.Options) {
			o.APIOptions = append(o.APIOptions,
				middleware.AddSDKAgentKey(middleware.FeatureMetadata, userAgentKey),
				addFeatureUserAgent,
			)
		}}

	var written int
	var err error
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		written, err = r.read(p)
		if err != nil {
			r.setErr(err)
		}
		r.setDone(true)
	}()

	ch := make(chan getChunk, r.options.Concurrency)
	for i := 0; i < r.options.Concurrency; i++ {
		r.wg.Add(1)
		go r.downloadPart(r.ctx, ch, clientOptions...)
	}

	for r.index < r.partsCount {
		if r.getErr() != nil || r.getDone() {
			break
		}

		if r.index == atomic.LoadInt32(&r.capacity) {
			continue
		}

		if r.options.GetObjectType == types.GetObjectParts {
			ch <- getChunk{part: r.index + 1, index: r.index}
		} else {
			ch <- getChunk{withRange: r.byteRange(), index: r.index}
		}

		r.pos += r.partSize
		r.index++
	}

	close(ch)
	r.wg.Wait()

	if e := r.getErr(); e != nil && e != io.EOF {
		close(r.ch)
	}
	wg.Wait()

	r.written += int64(written)
	r.done = false
	r.invocations++
	return written, r.getErr()
}

func (r *concurrentReader) downloadPart(ctx context.Context, ch chan getChunk, clientOptions ...func(*s3.Options)) {
	defer r.wg.Done()
	for {
		chunk, ok := <-ch
		if !ok {
			break
		}
		if r.getErr() != nil {
			continue
		}
		_, err := r.downloadChunk(ctx, chunk, clientOptions...)
		if err != nil {
			r.setErr(err)
		}
	}
}

// downloadChunk downloads the chunk from s3
func (r *concurrentReader) downloadChunk(ctx context.Context, chunk getChunk, clientOptions ...func(*s3.Options)) (*GetObjectOutput, error) {
	params := r.in.mapGetObjectInput(!r.options.DisableChecksumValidation)
	if chunk.part != 0 {
		params.PartNumber = aws.Int32(chunk.part)
	}
	if chunk.withRange != "" {
		params.Range = aws.String(chunk.withRange)
	}
	if params.VersionId == nil {
		params.IfMatch = r.etag
	}

	out, err := r.options.S3.GetObject(ctx, params, clientOptions...)
	if err != nil {
		return nil, err
	}

	if params.Range != nil && out.ContentRange != nil {
		reqStart, reqEnd, err := getReqRange(aws.ToString(params.Range))
		if err != nil {
			return nil, err
		}
		respStart, respEnd, err := getRespRange(aws.ToString(out.ContentRange))
		if err != nil {
			return nil, err
		}
		// don't validate first chunk since object size is unknown when getting that
		if reqStart != 0 && (reqStart != respStart || reqEnd != respEnd) {
			return nil, fmt.Errorf("range mismatch between request %d-%d and response %d-%d", reqStart, reqEnd, respStart, respEnd)
		}
	}

	defer out.Body.Close()
	buf, err := io.ReadAll(out.Body)

	if err != nil {
		return nil, err
	}
	r.ch <- outChunk{body: bytes.NewReader(buf), index: chunk.index, length: aws.ToInt64(out.ContentLength)}

	output := &GetObjectOutput{}
	output.mapFromGetObjectOutput(out, params.ChecksumMode)
	return output, err
}

// byteRange returns an HTTP Byte-Range header value that should be used by the
// client to request a chunk range.
func (r *concurrentReader) byteRange() string {
	return fmt.Sprintf("bytes=%d-%d", r.pos, min(r.totalBytes-1, r.pos+r.partSize-1))
}

type getChunk struct {
	part      int32
	withRange string

	index int32
}

type outChunk struct {
	body  io.Reader
	index int32

	length int64
	cur    int64
}

func (r *concurrentReader) read(p []byte) (int, error) {
	if cap(p) == 0 {
		return 0, nil
	}

	var written int

	partSize := r.partSize
	minIndex := int32(r.written / partSize)
	maxIndex := min(int32((r.written+int64(cap(p))-1)/partSize), atomic.LoadInt32(&r.capacity)-1)
	for i := minIndex; i <= maxIndex; i++ {
		if e := r.getErr(); e != nil && e != io.EOF {
			r.clean()
			return written, r.getErr()
		}

		c, ok := r.buf[i]
		if ok {
			index := int64(i)*partSize + c.cur - r.written
			n, err := c.body.Read(p[index:])
			c.cur += int64(n)
			written += n
			if err != nil && err != io.EOF {
				r.setErr(err)
				r.clean()
				return written, r.getErr()
			}
			if c.cur >= c.length {
				r.readCount++
				delete(r.buf, i)
				if r.readCount == atomic.LoadInt32(&r.capacity) {
					capacity := min(atomic.LoadInt32(&r.capacity)+r.sectionParts, r.partsCount)
					atomic.StoreInt32(&r.capacity, capacity)
				}
				if r.readCount >= r.partsCount {
					r.setErr(io.EOF)
				}
			}
		}
	}

	for r.receiveCount < atomic.LoadInt32(&r.capacity) {
		if e := r.getErr(); e != nil && e != io.EOF {
			r.clean()
			return written, e
		}

		oc, ok := <-r.ch
		if !ok {
			break
		}

		r.receiveCount++

		index := r.partSize*int64(oc.index) - r.written

		if index < int64(cap(p)) {
			n, err := oc.body.Read(p[index:])
			oc.cur += int64(n)
			written += n
			if err != nil && err != io.EOF {
				r.setErr(err)
				r.clean()
				return written, r.getErr()
			}
		}
		if oc.cur < oc.length {
			r.buf[oc.index] = &oc
		} else {
			r.readCount++
			if r.readCount == atomic.LoadInt32(&r.capacity) {
				capacity := min(atomic.LoadInt32(&r.capacity)+r.sectionParts, r.partsCount)
				atomic.StoreInt32(&r.capacity, capacity)
			}
			if r.readCount >= r.partsCount {
				r.setErr(io.EOF)
			}
		}
	}

	return written, r.getErr()
}

func (r *concurrentReader) setDone(done bool) {
	r.m.Lock()
	defer r.m.Unlock()

	r.done = done
}

func (r *concurrentReader) getDone() bool {
	r.m.Lock()
	defer r.m.Unlock()

	return r.done
}

func (r *concurrentReader) setErr(err error) {
	r.m.Lock()
	defer r.m.Unlock()

	r.err = err
}

func (r *concurrentReader) getErr() error {
	r.m.Lock()
	defer r.m.Unlock()

	return r.err
}

func (r *concurrentReader) clean() {
	r.buf = nil
	for {
		_, ok := <-r.ch
		if !ok {
			break
		}
	}
}
