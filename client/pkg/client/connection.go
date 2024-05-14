package client

import "context"

type Connection struct {
	ctx    context.Context
	cancel context.CancelFunc
}

func NewConnection(ctx context.Context) (*Connection, error) {
	ctx, cancel := context.WithCancel(ctx)
	return &Connection{
		ctx:    ctx,
		cancel: cancel,
	}, nil
}
