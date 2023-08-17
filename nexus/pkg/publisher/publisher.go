package publisher

import (
	"context"
)

type Channel interface {
	Send(ctx context.Context, msg any) error
	Read() <-chan any
	Close()
}
