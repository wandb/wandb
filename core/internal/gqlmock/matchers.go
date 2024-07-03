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

// GQLVar matches a query variable with the right name and value.
type GQLVarMatcher struct {
	Name  string
	Value gomock.Matcher
}

func GQLVar(name string, value gomock.Matcher) *GQLVarMatcher {
	return &GQLVarMatcher{Name: name, Value: value}
}

func (m *GQLVarMatcher) String() string {
	return fmt.Sprintf("variable '%v' %v", m.Name, m.Value)
}

// WithVariables matches any GraphQL request with the given variables.
func WithVariables(varMatchers ...*GQLVarMatcher) gomock.Matcher {
	return &queryVariablesMatcher{varMatchers}
}

type queryVariablesMatcher struct {
	varMatchers []*GQLVarMatcher
}

func (m *queryVariablesMatcher) Matches(x any) bool {
	req, ok := x.(*graphql.Request)
	if !ok {
		return false
	}

	varmap := jsonMarshallToMap(req.Variables)
	if varmap == nil {
		return false
	}

	for _, variable := range m.varMatchers {
		if !variable.Value.Matches(varmap[variable.Name]) {
			return false
		}
	}

	return true
}

func (m *queryVariablesMatcher) String() string {
	return fmt.Sprintf("has variables %v", m.varMatchers)
}
