package leet

import (
	"strconv"
	"strings"
	"unicode"
)

// workspaceRunFilterData is the precomputed searchable metadata for one run in
// the workspace runs sidebar.
type workspaceRunFilterData struct {
	RunKey      string
	DisplayName string
	ID          string
	Project     string

	// ConfigByPath stores flattened config values keyed by canonicalized path.
	ConfigByPath map[string]string
	// ConfigEntries preserves the flattened config for broader "config:<term>"
	// searches that should match either a key or a value.
	ConfigEntries []runFilterConfigEntry
}

// runFilterConfigEntry stores one flattened config path/value pair.
type runFilterConfigEntry struct {
	Path  string
	Value string
}

// runFilterQuery is a disjunction of AND-connected clause groups.
//
// A query matches when any group matches all of its clauses.
type runFilterQuery struct {
	groups []runFilterGroup
}

// runFilterGroup is one AND-connected group inside a runs filter query.
type runFilterGroup struct {
	clauses []runFilterClause
}

// runFilterClause is one atomic predicate with optional negation.
type runFilterClause struct {
	negated bool
	match   func(workspaceRunFilterData) bool
}

// Match evaluates the clause against one run's indexed metadata.
func (c runFilterClause) Match(data workspaceRunFilterData) bool {
	if c.match == nil {
		return true
	}
	matched := c.match(data)
	if c.negated {
		return !matched
	}
	return matched
}

// compileRunFilterQuery parses the runs filter language into an executable
// query.
//
// Bare terms search the default text fields. Whitespace and AND join clauses,
// OR or | starts a new group, NOT negates the next clause, and field operators
// support pattern matching (:), exact matching (=, !=), numeric comparisons,
// and existence checks (has:field).
func compileRunFilterQuery(raw string, mode FilterMatchMode) runFilterQuery {
	tokens := splitRunFilterTerms(raw)
	if len(tokens) == 0 {
		return runFilterQuery{}
	}

	groups := make([]runFilterGroup, 0, 1)
	current := runFilterGroup{}
	pendingNegation := false

	for _, token := range tokens {
		switch {
		case token == "|" || strings.EqualFold(token, "or"):
			pendingNegation = false
			if len(current.clauses) > 0 {
				groups = append(groups, current)
				current = runFilterGroup{}
			}
			continue
		case strings.EqualFold(token, "and"):
			continue
		case strings.EqualFold(token, "not"):
			pendingNegation = !pendingNegation
			continue
		}

		if pendingNegation {
			token = "!" + token
			pendingNegation = false
		}

		clause, ok := parseRunFilterClause(token, mode)
		if !ok {
			continue
		}
		current.clauses = append(current.clauses, clause)
	}

	if len(current.clauses) > 0 {
		groups = append(groups, current)
	}

	return runFilterQuery{groups: groups}
}

// Match reports whether the query matches the indexed metadata for a run.
func (q runFilterQuery) Match(data workspaceRunFilterData) bool {
	if len(q.groups) == 0 {
		return true
	}

	for _, group := range q.groups {
		matched := true
		for _, clause := range group.clauses {
			if !clause.Match(data) {
				matched = false
				break
			}
		}
		if matched {
			return true
		}
	}

	return false
}

// splitRunFilterTerms tokenizes a raw query while preserving quoted phrases and
// backslash escapes inside quotes.
func splitRunFilterTerms(raw string) []string {
	var tokens []string
	var b strings.Builder
	var quote rune
	escaped := false

	flush := func() {
		term := strings.TrimSpace(b.String())
		b.Reset()
		if term != "" {
			tokens = append(tokens, term)
		}
	}

	for _, r := range raw {
		switch {
		case escaped:
			b.WriteRune(r)
			escaped = false
		case quote != 0:
			switch r {
			case '\\':
				escaped = true
			case quote:
				quote = 0
			default:
				b.WriteRune(r)
			}
		case r == '"' || r == '\'':
			quote = r
		case unicode.IsSpace(r):
			flush()
		default:
			b.WriteRune(r)
		}
	}

	flush()
	return tokens
}

// parseRunFilterClause parses one token into either a fielded predicate or a
// bare-text clause.
func parseRunFilterClause(token string, mode FilterMatchMode) (runFilterClause, bool) {
	token = strings.TrimSpace(token)
	if token == "" {
		return runFilterClause{}, false
	}

	negated := false
	for token != "" && (token[0] == '-' || token[0] == '!') {
		negated = !negated
		token = token[1:]
	}

	if token == "" {
		return runFilterClause{}, false
	}

	lhs, rhs, op, ok := splitRunFilterOperation(token)
	if !ok {
		return newBareRunFilterClause(token, mode, negated), true
	}

	if isRunFilterExistsOperator(lhs, op) {
		field, ok := parseRunFilterField(rhs)
		if !ok {
			return newBareRunFilterClause(token, mode, negated), true
		}
		return runFilterClause{
			negated: negated,
			match: func(data workspaceRunFilterData) bool {
				return runFilterFieldExists(data, field)
			},
		}, true
	}

	field, ok := parseRunFilterField(lhs)
	if !ok {
		return newBareRunFilterClause(token, mode, negated), true
	}

	predicate := buildRunFilterPredicate(field, op, rhs, mode)
	if predicate == nil {
		return newBareRunFilterClause(token, mode, negated), true
	}

	return runFilterClause{negated: negated, match: predicate}, true
}

// newBareRunFilterClause searches the default text fields without requiring an
// explicit field qualifier.
func newBareRunFilterClause(term string, mode FilterMatchMode, negated bool) runFilterClause {
	matcher := compileTextMatcher(term, mode)
	return runFilterClause{
		negated: negated,
		match: func(data workspaceRunFilterData) bool {
			return runFilterMatchAny(matcher,
				data.RunKey,
				data.DisplayName,
				data.ID,
				data.Project,
			)
		},
	}
}

// splitRunFilterOperation splits a token at its leftmost supported operator.
//
// Preferring the earliest operator keeps queries like name:^(foo=bar)$ working,
// because the field separator is chosen before operator-like characters that
// appear later in the pattern.
func splitRunFilterOperation(token string) (lhs, rhs, op string, ok bool) {
	operators := []string{">=", "<=", "!=", "=", ">", "<", ":"}
	bestIdx := -1
	bestOp := ""

	for _, candidate := range operators {
		idx := strings.Index(token, candidate)
		if idx <= 0 {
			continue
		}
		if bestIdx == -1 || idx < bestIdx || idx == bestIdx && len(candidate) > len(bestOp) {
			bestIdx = idx
			bestOp = candidate
		}
	}
	if bestIdx == -1 {
		return "", "", "", false
	}

	lhs = strings.TrimSpace(token[:bestIdx])
	rhs = strings.TrimSpace(token[bestIdx+len(bestOp):])
	if lhs == "" {
		return "", "", "", false
	}
	return lhs, rhs, bestOp, true
}

// isRunFilterExistsOperator reports whether lhs:rhs is an existence query such
// as has:project or exists:cfg.dataset.
func isRunFilterExistsOperator(lhs, op string) bool {
	if op != ":" {
		return false
	}
	lhs = strings.ToLower(strings.TrimSpace(lhs))
	return lhs == "has" || lhs == "exists"
}

// runFilterFieldKind identifies the searchable fields supported by the runs
// filter language.
type runFilterFieldKind int

const (
	runFilterFieldInvalid runFilterFieldKind = iota
	runFilterFieldName
	runFilterFieldDisplay
	runFilterFieldKey
	runFilterFieldID
	runFilterFieldProject
	runFilterFieldConfigAny
	runFilterFieldConfigPath
)

// runFilterField names a supported field or a specific flattened config path.
type runFilterField struct {
	kind runFilterFieldKind
	path string
}

// parseRunFilterField resolves field aliases and cfg./config. path selectors.
func parseRunFilterField(raw string) (runFilterField, bool) {
	field := strings.ToLower(strings.TrimSpace(raw))
	if field == "" {
		return runFilterField{}, false
	}

	switch field {
	case "name", "run":
		return runFilterField{kind: runFilterFieldName}, true
	case "display", "display_name":
		return runFilterField{kind: runFilterFieldDisplay}, true
	case "key", "run_key", "path":
		return runFilterField{kind: runFilterFieldKey}, true
	case "id", "run_id":
		return runFilterField{kind: runFilterFieldID}, true
	case "project":
		return runFilterField{kind: runFilterFieldProject}, true
	case "config", "cfg":
		return runFilterField{kind: runFilterFieldConfigAny}, true
	}

	if path, ok := strings.CutPrefix(field, "config."); ok && path != "" {
		return runFilterField{
			kind: runFilterFieldConfigPath,
			path: canonicalRunFilterPath(path),
		}, true
	}
	if path, ok := strings.CutPrefix(field, "cfg."); ok && path != "" {
		return runFilterField{
			kind: runFilterFieldConfigPath,
			path: canonicalRunFilterPath(path),
		}, true
	}

	return runFilterField{}, false
}

// buildRunFilterPredicate builds a field-specific predicate for op and rhs.
func buildRunFilterPredicate(
	field runFilterField,
	op string,
	rhs string,
	mode FilterMatchMode,
) func(workspaceRunFilterData) bool {
	switch op {
	case ":":
		matcher := compileTextMatcher(rhs, mode)
		return func(data workspaceRunFilterData) bool {
			return runFilterPatternMatch(data, field, matcher)
		}
	case "=":
		return func(data workspaceRunFilterData) bool {
			return runFilterExactMatch(data, field, rhs)
		}
	case "!=":
		return func(data workspaceRunFilterData) bool {
			return runFilterExactMismatch(data, field, rhs)
		}
	case ">", ">=", "<", "<=":
		want, ok := parseRunFilterNumber(rhs)
		if !ok {
			return func(workspaceRunFilterData) bool { return false }
		}
		return func(data workspaceRunFilterData) bool {
			return runFilterNumericCompare(data, field, op, want)
		}
	default:
		return nil
	}
}

// runFilterPatternMatch applies a mode-aware text matcher to the selected field.
func runFilterPatternMatch(
	data workspaceRunFilterData,
	field runFilterField,
	matcher func(string) bool,
) bool {
	switch field.kind {
	case runFilterFieldName:
		return runFilterMatchAny(matcher, data.RunKey, data.DisplayName)
	case runFilterFieldDisplay:
		return runFilterMatchAny(matcher, data.DisplayName)
	case runFilterFieldKey:
		return runFilterMatchAny(matcher, data.RunKey)
	case runFilterFieldID:
		return runFilterMatchAny(matcher, data.ID)
	case runFilterFieldProject:
		return runFilterMatchAny(matcher, data.Project)
	case runFilterFieldConfigAny:
		for _, entry := range data.ConfigEntries {
			if matcher(entry.Path) || matcher(entry.Value) || matcher(entry.Path+"="+entry.Value) {
				return true
			}
		}
		return false
	case runFilterFieldConfigPath:
		value, ok := data.ConfigByPath[field.path]
		if !ok {
			return false
		}
		return matcher(value)
	default:
		return false
	}
}

// runFilterExactMatch reports whether any candidate value equals rhs.
func runFilterExactMatch(data workspaceRunFilterData, field runFilterField, rhs string) bool {
	candidates := runFilterExactCandidates(data, field)
	for _, candidate := range candidates {
		if runFilterExactValueEqual(candidate, rhs) {
			return true
		}
	}
	return false
}

// runFilterExactMismatch reports whether all candidate values differ from rhs.
func runFilterExactMismatch(data workspaceRunFilterData, field runFilterField, rhs string) bool {
	candidates := runFilterExactCandidates(data, field)
	if len(candidates) == 0 {
		return false
	}
	for _, candidate := range candidates {
		if runFilterExactValueEqual(candidate, rhs) {
			return false
		}
	}
	return true
}

// runFilterExactCandidates returns the values inspected by exact and inequality
// operations for a field.
func runFilterExactCandidates(data workspaceRunFilterData, field runFilterField) []string {
	switch field.kind {
	case runFilterFieldName:
		return runFilterNonEmptyStrings(data.RunKey, data.DisplayName)
	case runFilterFieldDisplay:
		return runFilterNonEmptyStrings(data.DisplayName)
	case runFilterFieldKey:
		return runFilterNonEmptyStrings(data.RunKey)
	case runFilterFieldID:
		return runFilterNonEmptyStrings(data.ID)
	case runFilterFieldProject:
		return runFilterNonEmptyStrings(data.Project)
	case runFilterFieldConfigAny:
		out := make([]string, 0, len(data.ConfigEntries)*3)
		for _, entry := range data.ConfigEntries {
			out = append(out, entry.Path, entry.Value, entry.Path+"="+entry.Value)
		}
		return out
	case runFilterFieldConfigPath:
		if value, ok := data.ConfigByPath[field.path]; ok {
			return []string{value}
		}
	}
	return nil
}

// runFilterExactValueEqual compares values case-insensitively and numerically
// when both sides parse as numbers.
func runFilterExactValueEqual(got, want string) bool {
	if gotNum, ok := parseRunFilterNumber(got); ok {
		if wantNum, ok := parseRunFilterNumber(want); ok {
			return gotNum == wantNum
		}
	}
	return strings.EqualFold(strings.TrimSpace(got), strings.TrimSpace(want))
}

// runFilterNumericCompare applies a numeric comparison to fields that resolve
// to a single numeric value.
func runFilterNumericCompare(
	data workspaceRunFilterData,
	field runFilterField,
	op string,
	want float64,
) bool {
	value, ok := runFilterSingleValue(data, field)
	if !ok {
		return false
	}
	got, ok := parseRunFilterNumber(value)
	if !ok {
		return false
	}

	switch op {
	case ">":
		return got > want
	case ">=":
		return got >= want
	case "<":
		return got < want
	case "<=":
		return got <= want
	default:
		return false
	}
}

// runFilterSingleValue returns the single value addressable by numeric
// comparison operators.
func runFilterSingleValue(data workspaceRunFilterData, field runFilterField) (string, bool) {
	switch field.kind {
	case runFilterFieldDisplay:
		return data.DisplayName, data.DisplayName != ""
	case runFilterFieldKey:
		return data.RunKey, data.RunKey != ""
	case runFilterFieldID:
		return data.ID, data.ID != ""
	case runFilterFieldProject:
		return data.Project, data.Project != ""
	case runFilterFieldConfigPath:
		value, ok := data.ConfigByPath[field.path]
		return value, ok
	default:
		return "", false
	}
}

// runFilterFieldExists reports whether a field is present in indexed run
// metadata.
func runFilterFieldExists(data workspaceRunFilterData, field runFilterField) bool {
	switch field.kind {
	case runFilterFieldName:
		return data.RunKey != "" || data.DisplayName != ""
	case runFilterFieldDisplay:
		return data.DisplayName != ""
	case runFilterFieldKey:
		return data.RunKey != ""
	case runFilterFieldID:
		return data.ID != ""
	case runFilterFieldProject:
		return data.Project != ""
	case runFilterFieldConfigAny:
		return len(data.ConfigEntries) > 0
	case runFilterFieldConfigPath:
		_, ok := data.ConfigByPath[field.path]
		return ok
	default:
		return false
	}
}

func runFilterMatchAny(matcher func(string) bool, values ...string) bool {
	for _, value := range values {
		if value != "" && matcher(value) {
			return true
		}
	}
	return false
}

func runFilterNonEmptyStrings(values ...string) []string {
	out := make([]string, 0, len(values))
	for _, value := range values {
		if value == "" {
			continue
		}
		out = append(out, value)
	}
	return out
}

// canonicalRunFilterPath normalizes config paths for case-insensitive lookup.
func canonicalRunFilterPath(path string) string {
	return strings.ToLower(strings.TrimSpace(path))
}

// parseRunFilterNumber parses a numeric literal used by exact and comparison
// operators.
func parseRunFilterNumber(raw string) (float64, bool) {
	value, err := strconv.ParseFloat(strings.TrimSpace(raw), 64)
	if err != nil {
		return 0, false
	}
	return value, true
}
