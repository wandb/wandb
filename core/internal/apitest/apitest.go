package apitest

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"sync"

	"github.com/wandb/wandb/core/internal/api"
)

// FakeClient is a fake [api.Client] meant for testing.
//
// It allows stubbing out responses and records all requests sent.
//
// Since the [api.Client] contract is very simple, it's not useful to use
// a real object in tests.
type FakeClient struct {
	sync.Mutex

	baseURL  *url.URL
	requests []RequestCopy

	response    *http.Response
	responseErr error
}

type RequestCopy struct {
	Method string
	URL    *url.URL
	Body   []byte
	Header http.Header
}

func NewFakeClient(baseURLString string) *FakeClient {
	baseURL, err := url.Parse(baseURLString)
	if err != nil {
		panic(err)
	}

	return &FakeClient{
		baseURL:     baseURL,
		requests:    make([]RequestCopy, 0),
		responseErr: fmt.Errorf("apitest: no response"),
	}
}

// TestResponse is an easy-to-use [http.Response] for tests.
type TestResponse struct {
	StatusCode int
}

// SetResponse configures the client's response to all requests.
func (c *FakeClient) SetResponse(resp *TestResponse, err error) {
	c.Lock()
	defer c.Unlock()

	c.responseErr = err
	if resp == nil {
		c.response = nil
	} else {
		c.response = &http.Response{}
		c.response.StatusCode = resp.StatusCode
		c.response.Status = fmt.Sprintf("%d TEST", resp.StatusCode)
		c.response.Body = io.NopCloser(strings.NewReader(""))
	}
}

// GetRequests returns all requests made to the fake client.
func (c *FakeClient) GetRequests() []RequestCopy {
	c.Lock()
	defer c.Unlock()
	return slices.Clone(c.requests)
}

var _ api.Client = &FakeClient{}

func (c *FakeClient) Send(req *api.Request) (*http.Response, error) {
	httpReq, err := http.NewRequest(
		req.Method,
		c.baseURL.JoinPath(req.Path).String(),
		bytes.NewReader(req.Body),
	)
	if err != nil {
		panic(err)
	}

	return c.Do(httpReq)
}

func (c *FakeClient) Do(req *http.Request) (*http.Response, error) {
	c.Lock()
	defer c.Unlock()

	body, err := io.ReadAll(req.Body)
	if err != nil {
		panic(err)
	}

	c.requests = append(c.requests, RequestCopy{
		Method: req.Method,
		URL:    req.URL,
		Body:   body,
		Header: req.Header,
	})

	return c.response, c.responseErr
}
