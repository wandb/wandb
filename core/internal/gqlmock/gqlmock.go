// Package gqlmock provides utilities to mock a GraphQL API for tests.
package gqlmock

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
)

// MockClient is a mock implementation of the genqlient Client interface.
//
// Use `StubOnce` to tell it what response to return for a given request.
// The mock client returns an error by default for unstubbed requests.
//
// Use `AllStubsUsed` to check that all stubbed requests were made.
type MockClient struct {
	mu       *sync.Mutex
	stubs    []*stubbedRequest
	requests []*graphql.Request
}

func NewMockClient() *MockClient {
	return &MockClient{
		mu:    &sync.Mutex{},
		stubs: make([]*stubbedRequest, 0),
	}
}

// StubOnce registers a response for a specific request.
//
// The `query` argument is a function that uses the given client to make the
// expected GraphQL request. The next time such a request is made, the
// `responseJSON` is used to fill in the response.
func (c *MockClient) StubOnce(
	query func(client graphql.Client),
	responseJSON string,
) {
	c.mu.Lock()
	defer c.mu.Unlock()

	recorder := &recorderClient{}
	query(recorder)
	c.stubs = append(
		c.stubs,
		&stubbedRequest{
			gomock.Eq(recorder.Request),
			handlerReturningJSON(responseJSON),
		})
}

// StubMatchOnce registers a response for a matching request.
//
// The next time a request matching `requestMatcher` is made, the
// `responseJSON` is used to fill in the response.
func (c *MockClient) StubMatchOnce(
	requestMatcher gomock.Matcher,
	responseJSON string,
) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.stubs = append(c.stubs,
		&stubbedRequest{
			requestMatcher,
			handlerReturningJSON(responseJSON),
		})
}

// StubAnyOnce registers a response for the next request.
func (c *MockClient) StubAnyOnce(responseJSON string) {
	c.StubMatchOnce(gomock.Any(), responseJSON)
}

func handlerReturningJSON(
	responseJSON string,
) func(*graphql.Request, *graphql.Response) error {
	return func(_ *graphql.Request, resp *graphql.Response) error {
		// Return the JSON error to make it easier to tell if a test's
		// JSON is incorrect.
		return json.Unmarshal([]byte(responseJSON), resp.Data)
	}
}

// AllStubsUsed reports whether every stubbed response was matched.
func (c *MockClient) AllStubsUsed() bool {
	c.mu.Lock()
	defer c.mu.Unlock()

	return len(c.stubs) == 0
}

// AllRequests returns all requests made to the mock client.
func (c *MockClient) AllRequests() []*graphql.Request {
	c.mu.Lock()
	defer c.mu.Unlock()

	return slices.Clone(c.requests)
}

func (c *MockClient) MakeRequest(
	ctx context.Context,
	req *graphql.Request,
	resp *graphql.Response,
) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.requests = append(c.requests, req)

	if stub := c.stubFor(req); stub != nil {
		return stub.Handle(req, resp)
	}

	return &notStubbedError{req}
}

// A stubbedRequest is a request matcher and a response function.
type stubbedRequest struct {
	gomock.Matcher
	Handle func(*graphql.Request, *graphql.Response) error
}

// stubFor pops and returns the first stub that matches the request.
//
// If there is no stub for the request, nil is returned.
func (c *MockClient) stubFor(req *graphql.Request) *stubbedRequest {
	for i, stub := range c.stubs {
		if stub.Matches(req) {
			c.stubs = slices.Delete(c.stubs, i, i+1)
			return stub
		}
	}

	return nil
}

// recorderClient is a GraphQL Client that records the most recent request.
type recorderClient struct {
	Request *graphql.Request
}

func (c *recorderClient) MakeRequest(
	ctx context.Context,
	req *graphql.Request,
	resp *graphql.Response,
) error {
	c.Request = req
	return nil
}

// notStubbedError is returned by MakeRequest when no response stub exists.
type notStubbedError struct {
	req *graphql.Request
}

func (e *notStubbedError) Error() string {
	return fmt.Sprintf(
		"gqlmock: no stub for request with query '%v' and with variables '%v'",
		e.req.Query,
		jsonMarshallToMap(e.req.Variables),
	)
}
