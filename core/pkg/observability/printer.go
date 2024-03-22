package observability

import (
	"bytes"
	"io"
	"net/http"
	"sync"

	"github.com/wandb/wandb/core/pkg/service"
)

type Printer[T any] struct {
	messages []T
	mutex    sync.Mutex
}

func NewPrinter[T any]() *Printer[T] {
	return &Printer[T]{}
}

func (p *Printer[T]) Write(message T) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	p.messages = append(p.messages, message)
}

func (p *Printer[T]) Read() []T {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	polledMessages := p.messages
	p.messages = make([]T, 0)
	return polledMessages
}

// A peeker is a type that can be used to inspect the response of an HTTP request.
// It is used to communicate back to the user about the http responses.
//
// Note: this is a temporary implementation, until we redo our communication of
// to the user about the status of the service.
type Peeker struct {
	*Printer[*service.HttpResponse]
}

func NewPeeker() *Peeker {
	return &Peeker{
		Printer: NewPrinter[*service.HttpResponse](),
	}
}

func (p *Peeker) Peek(_ *http.Request, resp *http.Response) {
	if resp == nil || resp.Body == nil {
		return
	}

	if resp.StatusCode >= http.StatusOK {
		// We need to read the response body to send it to the user
		buf, _ := io.ReadAll(resp.Body)
		p.Printer.Write(&service.HttpResponse{
			HttpStatusCode:   int32(resp.StatusCode),
			HttpResponseText: string(buf),
		})
		// Restore the body so it can be read again
		reader := io.NopCloser(bytes.NewReader(buf))
		resp.Body = reader
	}
}
