package publisher

import (
	"fmt"
	"sync"
)

type Publisher struct {
	ch chan interface{}

	closingCh      chan interface{}
	writersWG      sync.WaitGroup
	writersWGMutex sync.Mutex
}

func NewPublisher() *Publisher {
	return &Publisher{
		ch:        make(chan interface{}),
		closingCh: make(chan interface{}),
	}
}

func (p *Publisher) Read() <-chan interface{} {
	return p.ch
}

func (p *Publisher) Write(data interface{}) {
	go func(data interface{}) {
		p.writersWGMutex.Lock()
		p.writersWG.Add(1)
		p.writersWGMutex.Unlock()

		fmt.Println("writing data", data)
		defer p.writersWG.Done()

		select {
		case <-p.closingCh:
			return
		default:
		}

		select {
		case <-p.closingCh:
		case p.ch <- data:
		}
	}(data)
}

func (p *Publisher) Close() {
	close(p.closingCh)

	p.writersWGMutex.Lock()
	p.writersWG.Wait()
	p.writersWGMutex.Unlock()

	close(p.ch)
}
