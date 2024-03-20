package gqlmock

import (
	"fmt"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
)

// WithOpName matches any GraphQL request with the given OpName.
func WithOpName(opName string) gomock.Matcher {
	return &opNameMatcher{opName}
}

type opNameMatcher struct {
	opName string
}

func (m *opNameMatcher) Matches(x any) bool {
	req, ok := x.(*graphql.Request)
	if !ok {
		return false
	}

	return req.OpName == m.opName
}

func (m *opNameMatcher) String() string {
	return fmt.Sprintf("has OpName '%v'", m.opName)
}
