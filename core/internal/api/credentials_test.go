package api_test

import "net/http"

type MockCredentialProvider struct {
	CallCount int
	ApplyFunc func(req *http.Request) error
}

func (m *MockCredentialProvider) Apply(req *http.Request) error {
	m.CallCount++
	if m.ApplyFunc != nil {
		return m.Apply(req)
	}
	return nil
}
