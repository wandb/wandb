package core

import (
	"sync"
)

type MapData map[string]interface{}

type PartialData struct {
	index int
	data  map[int]MapData
	mutex sync.Mutex
}

func NewPartialData() *PartialData {
	return &PartialData{
		// arbitrary number to start counting from
		index: 42,
		data:  make(map[int]MapData),
	}
}

func (p *PartialData) Get(num int) MapData {
	return p.data[num]
}

func (p *PartialData) Remove(num int) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	delete(p.data, num)
}

func (p *PartialData) Create() int {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	num := p.index
	p.index += 1
	p.data[num] = make(map[string]interface{})
	return num
}
