package fs

import (
	"io"
)

type StorageNode interface {
	Id() uint64
	Reader() io.Reader
	Size() int
}

type Storage interface {
	Create(io.Reader) (uint64, error)
	Update(uint64, io.Reader) (bool, error)
	Delete(uint64) bool
	Get(uint64) StorageNode
	Size(uint64) int
}
