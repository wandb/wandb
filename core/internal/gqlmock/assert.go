package gqlmock

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/stretchr/testify/assert"
)

// AssertMatches asserts that a GQL request matches a gomock Matcher.
func AssertRequest(t *testing.T, expected gomock.Matcher, req *graphql.Request) {
	assert.True(t, expected.Matches(req),
		"expected <%v> but got query\n====\n%v\n====\nwith variables %v",
		expected,
		req.Query,
		jsonMarshallToMap(req.Variables))
}
