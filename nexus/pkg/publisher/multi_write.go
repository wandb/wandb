package publisher

import (
	"context"
	"sync"
)

type MultiChannel struct {
	ch chan any
	wg *sync.WaitGroup
}

func (c *MultiChannel) Add() *MultiChannel {
	c.wg.Add(1)
	return c
}

func (c *MultiChannel) Read() <-chan any {
	return c.ch
}

func (c *MultiChannel) Send(ctx context.Context, msg any) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	case c.ch <- msg:
		return nil
	default:
	}
	return nil
}

func (c *MultiChannel) Done() {
	c.wg.Done()
}

func (c *MultiChannel) Close() {
	c.wg.Wait()
	close(c.ch)
}

func NewMultiWrite(ch *chan any) *MultiChannel {
	return &MultiChannel{
		ch: *ch,
		wg: &sync.WaitGroup{},
	}
}
