package validator

import (
	//nolint:revive
	. "github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/gqlerror"
)

type AddErrFunc func(options ...ErrorOption)

type ruleFunc func(observers *Events, addError AddErrFunc)

type rule struct {
	name string
	rule ruleFunc
}

var rules []rule

// addRule to rule set.
// f is called once each time `Validate` is executed.
func AddRule(name string, f ruleFunc) {
	rules = append(rules, rule{name: name, rule: f})
}

func Validate(schema *Schema, doc *QueryDocument) gqlerror.List {
	var errs gqlerror.List
	if schema == nil {
		errs = append(errs, gqlerror.Errorf("cannot validate as Schema is nil"))
	}
	if doc == nil {
		errs = append(errs, gqlerror.Errorf("cannot validate as QueryDocument is nil"))
	}
	if len(errs) > 0 {
		return errs
	}
	observers := &Events{}
	for i := range rules {
		rule := rules[i]
		rule.rule(observers, func(options ...ErrorOption) {
			err := &gqlerror.Error{
				Rule: rule.name,
			}
			for _, o := range options {
				o(err)
			}
			errs = append(errs, err)
		})
	}

	Walk(schema, doc, observers)
	return errs
}
