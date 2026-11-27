package transfermanager

import (
	"context"
	"fmt"
)

type bytesBufferPool interface {
	Get(context.Context) ([]byte, error)
	Put([]byte)
	Close()
}

type defaultSlicePool struct {
	slices chan []byte
}

func newDefaultSlicePool(sliceSize int64, capacity int) *defaultSlicePool {
	p := &defaultSlicePool{}

	slices := make(chan []byte, capacity)
	for range capacity {
		slices <- make([]byte, sliceSize)
	}

	p.slices = slices
	return p
}

var errZeroCapacity = fmt.Errorf("get called on zero capacity pool")

func (p *defaultSlicePool) Get(ctx context.Context) ([]byte, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}

	for {
		select {
		case bs, ok := <-p.slices:
			if !ok {
				return nil, errZeroCapacity
			}
			return bs, nil
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}

func (p *defaultSlicePool) Put(bs []byte) {
	p.slices <- bs
}

func (p *defaultSlicePool) Close() {
	close(p.slices)
	for range p.slices {
		// drain channel
	}
	p.slices = nil
}
