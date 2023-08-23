package publisher

import "sync"

type Group[T any] struct {
	ch       chan T
	wgWaiter *sync.WaitGroup
	wgReader *sync.WaitGroup
}

func NewGroup[T any](size int) *Group[T] {
	return &Group[T]{
		ch:       make(chan T, size),
		wgWaiter: &sync.WaitGroup{},
		wgReader: &sync.WaitGroup{},
	}
}

func (g *Group[T]) GoWriter(f func(chan<- T)) {
	g.wgWaiter.Add(1)
	go func() {
		f(g.ch)
		g.wgWaiter.Done()
	}()
}

func (g *Group[T]) GoReader(f func(<-chan T)) {
	g.wgReader.Add(1)
	go func() {
		f(g.ch)
		g.wgReader.Done()
	}()
}

func (g *Group[T]) Close() {
	g.wgWaiter.Wait()
	close(g.ch)
	g.wgReader.Wait()
}
