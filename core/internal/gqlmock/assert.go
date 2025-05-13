package gqlmock

import (
	"testing"

	"github.com/Khan/genqlient/graphql"
	"github.com/stretchr/testify/require"
)

// AssertVariables asserts that a GQL request's variables match the expected
// values.
func AssertVariables(
	t *testing.T,
	req *graphql.Request,
	varMatchers ...*gqlVarMatcher,
) {
	t.Helper()

	varmap := jsonMarshallToMap(req.Variables)
	require.NotNil(t, varmap)

	for _, variable := range varMatchers {
		value, found := variable.Extract(varmap)

		if !found {
			t.Logf(
				"Variable %s not in the request.",
				variable.Path)
			t.Fail()
		} else if !variable.Value.Matches(value) {
			t.Logf(
				"Expected variable %s to match <%v> but got %#v",
				variable.Path,
				variable.Value,
				value)
			t.Fail()
		}
	}
}
