package gqlmock

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"

	"github.com/Khan/genqlient/graphql"
	"go.uber.org/mock/gomock"
)

// WithOpName matches any GraphQL request with the given OpName.
func WithOpName(opName string) gomock.Matcher {
	return &opNameMatcher{opName}
}

// WithVariables matches any GraphQL request with the given variables.
func WithVariables(varMatchers ...*gqlVarMatcher) gomock.Matcher {
	return &queryVariablesMatcher{varMatchers}
}

// GQLVar matches a query variable with the right name and value.
//
// If the name contains periods, it is treated as a path. For example,
// the name "key1.key2" corresponds to the "key2" field of the JSON object
// passed as "key1" to a GQL query.
//
// If the value is expected to be a JSON string, consider using the JSONEq
// matcher. Otherwise, gomock.Eq() is generally appropriate.
//
// Note that array variables in GraphQL are passed with type `[]any`.
func GQLVar(name string, value gomock.Matcher) *gqlVarMatcher {
	return &gqlVarMatcher{Path: name, Value: value}
}

// JSONEq matches a string or pointer to a string that's JSON-equivalent
// to the value.
func JSONEq(valueJSON string) gomock.Matcher {
	var value any

	err := json.Unmarshal([]byte(valueJSON), &value)
	if err != nil {
		panic(fmt.Errorf("could not unmarshal %q as JSON: %v", valueJSON, err))
	}

	marshaled, err := json.Marshal(value)
	if err != nil {
		panic(fmt.Errorf("could not marshal as JSON: %v", err))
	}

	return &jsonMatcher{
		marshaledValue:   string(marshaled),
		unmarshaledValue: value,
	}
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

type gqlVarMatcher struct {
	Path  string
	Value gomock.Matcher
}

// Extract returns the variable's value in the unmarshaled JSON object.
//
// The second return value indicates whether the value was found or not.
func (m *gqlVarMatcher) Extract(varmap map[string]any) (any, bool) {
	parts := strings.Split(m.Path, ".")

	prefix := parts[:len(parts)-1]
	key := parts[len(parts)-1]

	for _, part := range prefix {
		item, exists := varmap[part]

		if !exists {
			return nil, false
		}

		submap, ok := item.(map[string]any)
		if !ok {
			return nil, false
		}

		varmap = submap
	}

	value, found := varmap[key]
	return value, found
}

func (m *gqlVarMatcher) String() string {
	return fmt.Sprintf("variable '%v' %v", m.Path, m.Value)
}

type queryVariablesMatcher struct {
	varMatchers []*gqlVarMatcher
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
		value, found := variable.Extract(varmap)

		if !found || !variable.Value.Matches(value) {
			return false
		}
	}

	return true
}

func (m *queryVariablesMatcher) String() string {
	var matcherDescriptions []string

	for _, matcher := range m.varMatchers {
		matcherDescriptions = append(matcherDescriptions, matcher.String())
	}

	return fmt.Sprintf(
		"has variables [%s]",
		strings.Join(matcherDescriptions, ", "),
	)
}

type jsonMatcher struct {
	marshaledValue   string
	unmarshaledValue any
}

func (m *jsonMatcher) Matches(x any) bool {
	var str string

	switch val := x.(type) {
	case string:
		str = val
	case *string:
		if val == nil {
			return false
		} else {
			str = *val
		}
	}

	var unmarshaled any
	err := json.Unmarshal([]byte(str), &unmarshaled)
	if err != nil {
		return false
	}

	return reflect.DeepEqual(unmarshaled, m.unmarshaledValue)
}

func (m *jsonMatcher) String() string {
	return fmt.Sprintf("is JSON-equivalent to %s", m.marshaledValue)
}
