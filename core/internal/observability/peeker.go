package observability

import (
	"bytes"
	"io"
	"net/http"
	"sync"

	"github.com/wandb/wandb/core/internal/api"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Peeker stores HTTP responses for failed requests.
type Peeker struct {
	sync.Mutex
	responses []*spb.HttpResponse
}

// Read returns the buffered responses and clears the buffer.
func (p *Peeker) Read() []*spb.HttpResponse {
	p.Lock()
	defer p.Unlock()

	responses := p.responses
	p.responses = make([]*spb.HttpResponse, 0)

	return responses
}

var _ api.Peeker = &Peeker{}

func (p *Peeker) Peek(_ *http.Request, resp *http.Response) {
	if resp == nil || resp.Body == nil {
		return
	}

	// If the status code is not a success code (2xx), we need to send the response to
	// the user so they can see what happened.
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		// We need to read the response body to send it to the user
		buf, _ := io.ReadAll(resp.Body)

		p.Lock()
		p.responses = append(p.responses, &spb.HttpResponse{
			HttpStatusCode:   int32(resp.StatusCode),
			HttpResponseText: string(buf),
		})
		p.Unlock()

		// Restore the body so it can be read again
		reader := io.NopCloser(bytes.NewReader(buf))
		resp.Body = reader
	}
}
