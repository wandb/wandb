package rules

import (
	"bytes"
	"fmt"
	"slices"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
	//nolint:staticcheck // Validator rules each use dot imports for convenience.
	. "github.com/vektah/gqlparser/v2/validator/core"
)

var OverlappingFieldsCanBeMergedRule = Rule{
	Name: "OverlappingFieldsCanBeMerged",
	RuleFunc: func(observers *Events, addError AddErrFunc) {
		/**
		 * Algorithm:
		 *
		 * Conflicts occur when two fields exist in a query which will produce the same
		 * response name, but represent differing values, thus creating a conflict.
		 * The algorithm below finds all conflicts via making a series of comparisons
		 * between fields. In order to compare as few fields as possible, this makes
		 * a series of comparisons "within" sets of fields and "between" sets of fields.
		 *
		 * Given any selection set, a collection produces both a set of fields by
		 * also including all inline fragments, as well as a list of fragments
		 * referenced by fragment spreads.
		 *
		 * A) Each selection set represented in the document first compares "within" its
		 * collected set of fields, finding any conflicts between every pair of
		 * overlapping fields.
		 * Note: This is the *only time* that a the fields "within" a set are compared
		 * to each other. After this only fields "between" sets are compared.
		 *
		 * B) Also, if any fragment is referenced in a selection set, then a
		 * comparison is made "between" the original set of fields and the
		 * referenced fragment.
		 *
		 * C) Also, if multiple fragments are referenced, then comparisons
		 * are made "between" each referenced fragment.
		 *
		 * D) When comparing "between" a set of fields and a referenced fragment, first
		 * a comparison is made between each field in the original set of fields and
		 * each field in the referenced set of fields.
		 *
		 * E) Also, if any fragment is referenced in the referenced selection set,
		 * then a comparison is made "between" the original set of fields and the
		 * referenced fragment (recursively referring to step D).
		 *
		 * F) When comparing "between" two fragments, first a comparison is made between
		 * each field in the first referenced set of fields and each field in the the
		 * second referenced set of fields.
		 *
		 * G) Also, any fragments referenced by the first must be compared to the
		 * second, and any fragments referenced by the second must be compared to the
		 * first (recursively referring to step F).
		 *
		 * H) When comparing two fields, if both have selection sets, then a comparison
		 * is made "between" both selection sets, first comparing the set of fields in
		 * the first selection set with the set of fields in the second.
		 *
		 * I) Also, if any fragment is referenced in either selection set, then a
		 * comparison is made "between" the other set of fields and the
		 * referenced fragment.
		 *
		 * J) Also, if two fragments are referenced in both selection sets, then a
		 * comparison is made "between" the two fragments.
		 *
		 */

		m := &overlappingFieldsCanBeMergedManager{
			comparedFieldsAndFragmentPairs: newOrderedPairSet[*sequentialFieldsMap, string](),
			comparedFragmentPairs:          pairSet{pairs: newOrderedPairSet[string, string]()},
			cachedFieldsAndFragmentNames: make(
				map[selectionSetKey]*fieldsAndFragmentNames,
			),
		}

		observers.OnOperation(func(walker *Walker, operation *ast.OperationDefinition) {
			m.walker = walker
			conflicts := m.findConflictsWithinSelectionSet(operation.SelectionSet)
			for _, conflict := range conflicts {
				conflict.addFieldsConflictMessage(addError)
			}
		})
		observers.OnField(func(walker *Walker, field *ast.Field) {
			if walker.CurrentOperation == nil {
				// When checking both Operation and Fragment, errors are duplicated when processing
				// FragmentDefinition referenced from Operation
				return
			}
			m.walker = walker
			conflicts := m.findConflictsWithinSelectionSet(field.SelectionSet)
			for _, conflict := range conflicts {
				conflict.addFieldsConflictMessage(addError)
			}
		})
		observers.OnInlineFragment(func(walker *Walker, inlineFragment *ast.InlineFragment) {
			m.walker = walker
			conflicts := m.findConflictsWithinSelectionSet(inlineFragment.SelectionSet)
			for _, conflict := range conflicts {
				conflict.addFieldsConflictMessage(addError)
			}
		})
		observers.OnFragment(func(walker *Walker, fragment *ast.FragmentDefinition) {
			m.walker = walker
			conflicts := m.findConflictsWithinSelectionSet(fragment.SelectionSet)
			for _, conflict := range conflicts {
				conflict.addFieldsConflictMessage(addError)
			}
		})
	},
}

// orderedPairSet records pairs of things already compared for conflicts, along with
// whether each pair was compared as mutually exclusive. Comparisons are made many
// times over, so memoizing them keeps this rule from re-walking the same fragments.
// The order of a pair matters here; pairSet wraps this for pairs where it does not.
// graphql-js keeps the same two structures.
type orderedPairSet[A comparable, B comparable] struct {
	data map[A]map[B]bool
}

func newOrderedPairSet[A comparable, B comparable]() orderedPairSet[A, B] {
	return orderedPairSet[A, B]{data: make(map[A]map[B]bool)}
}

func (set *orderedPairSet[A, B]) Add(a A, b B, areMutuallyExclusive bool) {
	bs := set.data[a]
	if bs == nil {
		bs = make(map[B]bool)
		set.data[a] = bs
	}
	bs[b] = areMutuallyExclusive
}

func (set *orderedPairSet[A, B]) Has(a A, b B, areMutuallyExclusive bool) bool {
	bs, ok := set.data[a]
	if !ok {
		return false
	}
	result, ok := bs[b]
	if !ok {
		return false
	}

	// areMutuallyExclusive being false is a superset of being true,
	// hence if we want to know if this PairSet "has" these two with no
	// exclusivity, we have to ensure it was added as such.
	if !areMutuallyExclusive {
		return !result
	}

	return true
}

// pairSet records pairs of fragments already compared for conflicts, by name, for
// which the order of the pair does not matter.
type pairSet struct {
	pairs orderedPairSet[string, string]
}

func (pairSet *pairSet) Add(
	a *ast.FragmentSpread,
	b *ast.FragmentSpread,
	areMutuallyExclusive bool,
) {
	pairSet.pairs.Add(a.Name, b.Name, areMutuallyExclusive)
	pairSet.pairs.Add(b.Name, a.Name, areMutuallyExclusive)
}

func (pairSet *pairSet) Has(
	a *ast.FragmentSpread,
	b *ast.FragmentSpread,
	areMutuallyExclusive bool,
) bool {
	return pairSet.pairs.Has(a.Name, b.Name, areMutuallyExclusive)
}

// fieldsAndFragmentNames is one selection set's collected fields and fragment spreads,
// cached so that every lookup of that selection set yields the same
// *sequentialFieldsMap. graphql-js caches the same thing, and the identity it gives is
// what makes the memos above terminate on a fragment cycle.
type fieldsAndFragmentNames struct {
	fieldsMap       *sequentialFieldsMap
	fragmentSpreads []*ast.FragmentSpread
}

// selectionSetKey identifies a selection set for that cache. ast.SelectionSet is a
// slice, so it cannot be a map key itself, and unlike graphql-js's SelectionSetNode
// there is no node wrapping it to key on instead. Two slices that share a first
// element and a length are the same view of the same memory, so they cannot disagree
// about their contents. Every empty selection set collects to the same empty result
// and so shares the zero key: that makes distinct empty selection sets compare equal
// below, which only ever skips comparing an empty set of fields against something,
// and such a comparison reports nothing whether it is made or skipped.
type selectionSetKey struct {
	first *ast.Selection
	n     int
}

type sequentialFieldsMap struct {
	// We can't use map[string][]*ast.Field. because map is not stable...
	seq  []string
	data map[string][]*ast.Field
}

func (m *sequentialFieldsMap) Push(responseName string, field *ast.Field) {
	fields, ok := m.data[responseName]
	if !ok {
		m.seq = append(m.seq, responseName)
	}
	fields = append(fields, field)
	m.data[responseName] = fields
}

func (m *sequentialFieldsMap) Get(responseName string) ([]*ast.Field, bool) {
	fields, ok := m.data[responseName]
	return fields, ok
}

type conflictMessageContainer struct {
	Conflicts []*ConflictMessage
}

type ConflictMessage struct {
	Message      string
	ResponseName string
	Names        []string
	SubMessage   []*ConflictMessage
	Position     *ast.Position
}

func (m *ConflictMessage) String(buf *bytes.Buffer) {
	if len(m.SubMessage) == 0 {
		buf.WriteString(m.Message)
		return
	}

	for idx, subMessage := range m.SubMessage {
		buf.WriteString(`subfields "`)
		buf.WriteString(subMessage.ResponseName)
		buf.WriteString(`" conflict because `)
		subMessage.String(buf)
		if idx != len(m.SubMessage)-1 {
			buf.WriteString(" and ")
		}
	}
}

func (m *ConflictMessage) addFieldsConflictMessage(addError AddErrFunc) {
	var buf bytes.Buffer
	m.String(&buf)
	addError(
		Message(
			`Fields "%s" conflict because %s. Use different aliases on the fields to fetch both if this was intentional.`,
			m.ResponseName,
			buf.String(),
		),
		At(m.Position),
	)
}

type overlappingFieldsCanBeMergedManager struct {
	walker *Walker

	// per walker.
	//
	// comparedFieldsAndFragmentPairs is keyed on the set of fields as well as the
	// fragment name because a fragment reached again while comparing a *different*
	// set of fields is a comparison that still has to happen: nested reuse of one
	// fragment is legal, and memoizing on the fragment name alone drops the
	// comparison that finds a conflict inside the reused fragment. Sets of fields are
	// compared by identity, so that is a memo rather than an unbounded traversal of a
	// fragment cycle only because they come from getFieldsAndFragmentNames.
	comparedFieldsAndFragmentPairs orderedPairSet[*sequentialFieldsMap, string]
	comparedFragmentPairs          pairSet
	cachedFieldsAndFragmentNames   map[selectionSetKey]*fieldsAndFragmentNames
}

func (m *overlappingFieldsCanBeMergedManager) findConflictsWithinSelectionSet(
	selectionSet ast.SelectionSet,
) []*ConflictMessage {
	if len(selectionSet) == 0 {
		return nil
	}

	fieldsMap, fragmentSpreads := m.getFieldsAndFragmentNames(selectionSet)

	var conflicts conflictMessageContainer

	// (A) Find find all conflicts "within" the fieldMap of this selection set.
	// Note: this is the *only place* `collectConflictsWithin` is called.
	m.collectConflictsWithin(&conflicts, fieldsMap)

	for idx, fragmentSpreadA := range fragmentSpreads {
		// (B) Then collect conflicts between these fieldMap and those represented by
		// each spread fragment name found.
		m.collectConflictsBetweenFieldsAndFragment(&conflicts, false, fieldsMap, fragmentSpreadA)

		for _, fragmentSpreadB := range fragmentSpreads[idx+1:] {
			// (C) Then compare this fragment with all other fragments found in this
			// selection set to collect conflicts between fragments spread together.
			// This compares each item in the list of fragment names to every other
			// item in that same list (except for itself).
			m.collectConflictsBetweenFragments(&conflicts, false, fragmentSpreadA, fragmentSpreadB)
		}
	}

	return conflicts.Conflicts
}

func (m *overlappingFieldsCanBeMergedManager) collectConflictsBetweenFieldsAndFragment(
	conflicts *conflictMessageContainer,
	areMutuallyExclusive bool,
	fieldsMap *sequentialFieldsMap,
	fragmentSpread *ast.FragmentSpread,
) {
	// Memoize so a set of fields and a fragment are not compared more than once.
	if m.comparedFieldsAndFragmentPairs.Has(
		fieldsMap,
		fragmentSpread.Name,
		areMutuallyExclusive,
	) {
		return
	}
	m.comparedFieldsAndFragmentPairs.Add(fieldsMap, fragmentSpread.Name, areMutuallyExclusive)

	if fragmentSpread.Definition == nil {
		return
	}

	fieldsMapB, fragmentSpreads := m.getFieldsAndFragmentNames(
		fragmentSpread.Definition.SelectionSet,
	)

	// Do not compare a fragment's fieldMap to itself.
	if fieldsMap == fieldsMapB {
		return
	}

	// (D) First collect any conflicts between the provided collection of fields
	// and the collection of fields represented by the given fragment.
	m.collectConflictsBetween(conflicts, areMutuallyExclusive, fieldsMap, fieldsMapB)

	// (E) Then collect any conflicts between the provided collection of fields
	// and any fragment names found in the given fragment. A fragment reached again
	// with this same collection of fields — a cycle, or this fragment spreading
	// itself — is refused by the memo above, so this recursion terminates.
	for _, fragmentSpread := range fragmentSpreads {
		m.collectConflictsBetweenFieldsAndFragment(
			conflicts,
			areMutuallyExclusive,
			fieldsMap,
			fragmentSpread,
		)
	}
}

func (m *overlappingFieldsCanBeMergedManager) collectConflictsBetweenFragments(
	conflicts *conflictMessageContainer,
	areMutuallyExclusive bool,
	fragmentSpreadA *ast.FragmentSpread,
	fragmentSpreadB *ast.FragmentSpread,
) {
	var check func(fragmentSpreadA *ast.FragmentSpread, fragmentSpreadB *ast.FragmentSpread)
	check = func(fragmentSpreadA *ast.FragmentSpread, fragmentSpreadB *ast.FragmentSpread) {
		if fragmentSpreadA.Name == fragmentSpreadB.Name {
			return
		}

		if m.comparedFragmentPairs.Has(fragmentSpreadA, fragmentSpreadB, areMutuallyExclusive) {
			return
		}
		m.comparedFragmentPairs.Add(fragmentSpreadA, fragmentSpreadB, areMutuallyExclusive)

		if fragmentSpreadA.Definition == nil {
			return
		}
		if fragmentSpreadB.Definition == nil {
			return
		}

		fieldsMapA, fragmentSpreadsA := m.getFieldsAndFragmentNames(
			fragmentSpreadA.Definition.SelectionSet,
		)
		fieldsMapB, fragmentSpreadsB := m.getFieldsAndFragmentNames(
			fragmentSpreadB.Definition.SelectionSet,
		)

		// (F) First, collect all conflicts between these two collections of fields
		// (not including any nested fragments).
		m.collectConflictsBetween(conflicts, areMutuallyExclusive, fieldsMapA, fieldsMapB)

		// (G) Then collect conflicts between the first fragment and any nested
		// fragments spread in the second fragment.
		for _, fragmentSpread := range fragmentSpreadsB {
			check(fragmentSpreadA, fragmentSpread)
		}
		// (G) Then collect conflicts between the second fragment and any nested
		// fragments spread in the first fragment.
		for _, fragmentSpread := range fragmentSpreadsA {
			check(fragmentSpread, fragmentSpreadB)
		}
	}

	check(fragmentSpreadA, fragmentSpreadB)
}

func (m *overlappingFieldsCanBeMergedManager) findConflictsBetweenSubSelectionSets(
	areMutuallyExclusive bool,
	selectionSetA ast.SelectionSet,
	selectionSetB ast.SelectionSet,
) *conflictMessageContainer {
	var conflicts conflictMessageContainer

	fieldsMapA, fragmentSpreadsA := m.getFieldsAndFragmentNames(selectionSetA)
	fieldsMapB, fragmentSpreadsB := m.getFieldsAndFragmentNames(selectionSetB)

	// (H) First, collect all conflicts between these two collections of field.
	m.collectConflictsBetween(&conflicts, areMutuallyExclusive, fieldsMapA, fieldsMapB)

	// (I) Then collect conflicts between the first collection of fields and
	// those referenced by each fragment name associated with the second.
	for _, fragmentSpread := range fragmentSpreadsB {
		m.collectConflictsBetweenFieldsAndFragment(
			&conflicts,
			areMutuallyExclusive,
			fieldsMapA,
			fragmentSpread,
		)
	}

	// (I) Then collect conflicts between the second collection of fields and
	// those referenced by each fragment name associated with the first.
	for _, fragmentSpread := range fragmentSpreadsA {
		m.collectConflictsBetweenFieldsAndFragment(
			&conflicts,
			areMutuallyExclusive,
			fieldsMapB,
			fragmentSpread,
		)
	}

	// (J) Also collect conflicts between any fragment names by the first and
	// fragment names by the second. This compares each item in the first set of
	// names to each item in the second set of names.
	for _, fragmentSpreadA := range fragmentSpreadsA {
		for _, fragmentSpreadB := range fragmentSpreadsB {
			m.collectConflictsBetweenFragments(
				&conflicts,
				areMutuallyExclusive,
				fragmentSpreadA,
				fragmentSpreadB,
			)
		}
	}

	if len(conflicts.Conflicts) == 0 {
		return nil
	}

	return &conflicts
}

func (m *overlappingFieldsCanBeMergedManager) collectConflictsWithin(
	conflicts *conflictMessageContainer,
	fieldsMap *sequentialFieldsMap,
) {
	for _, responseName := range fieldsMap.seq {
		fields := fieldsMap.data[responseName]
		for idx, fieldA := range fields {
			for _, fieldB := range fields[idx+1:] {
				conflict := m.findConflict(false, fieldA, fieldB)
				if conflict != nil {
					conflicts.Conflicts = append(conflicts.Conflicts, conflict)
				}
			}
		}
	}
}

func (m *overlappingFieldsCanBeMergedManager) collectConflictsBetween(
	conflicts *conflictMessageContainer,
	parentFieldsAreMutuallyExclusive bool,
	fieldsMapA *sequentialFieldsMap,
	fieldsMapB *sequentialFieldsMap,
) {
	for _, responseName := range fieldsMapA.seq {
		fieldsA := fieldsMapA.data[responseName]
		fieldsB, ok := fieldsMapB.Get(responseName)
		if !ok {
			continue
		}
		for _, fieldA := range fieldsA {
			for _, fieldB := range fieldsB {
				conflict := m.findConflict(parentFieldsAreMutuallyExclusive, fieldA, fieldB)
				if conflict != nil {
					conflicts.Conflicts = append(conflicts.Conflicts, conflict)
				}
			}
		}
	}
}

func (m *overlappingFieldsCanBeMergedManager) findConflict(
	parentFieldsAreMutuallyExclusive bool,
	fieldA *ast.Field,
	fieldB *ast.Field,
) *ConflictMessage {
	if fieldA.ObjectDefinition == nil || fieldB.ObjectDefinition == nil {
		return nil
	}

	areMutuallyExclusive := parentFieldsAreMutuallyExclusive
	if !areMutuallyExclusive {
		tmp := fieldA.ObjectDefinition.Name != fieldB.ObjectDefinition.Name
		tmp = tmp && fieldA.ObjectDefinition.Kind == ast.Object
		tmp = tmp && fieldB.ObjectDefinition.Kind == ast.Object
		tmp = tmp && fieldA.Definition != nil && fieldB.Definition != nil
		areMutuallyExclusive = tmp
	}

	fieldNameA := fieldA.Name
	if fieldA.Alias != "" {
		fieldNameA = fieldA.Alias
	}

	if !areMutuallyExclusive {
		// Two aliases must refer to the same field.
		if fieldA.Name != fieldB.Name {
			return &ConflictMessage{
				ResponseName: fieldNameA,
				Message: fmt.Sprintf(
					`"%s" and "%s" are different fields`,
					fieldA.Name,
					fieldB.Name,
				),
				Position: fieldB.Position,
			}
		}

		// Two field calls must have the same arguments.
		if !sameArguments(fieldA.Arguments, fieldB.Arguments) {
			return &ConflictMessage{
				ResponseName: fieldNameA,
				Message:      "they have differing arguments",
				Position:     fieldB.Position,
			}
		}
	}

	if fieldA.Definition != nil && fieldB.Definition != nil &&
		doTypesConflict(m.walker, fieldA.Definition.Type, fieldB.Definition.Type) {
		return &ConflictMessage{
			ResponseName: fieldNameA,
			Message: fmt.Sprintf(
				`they return conflicting types "%s" and "%s"`,
				fieldA.Definition.Type.String(),
				fieldB.Definition.Type.String(),
			),
			Position: fieldB.Position,
		}
	}

	// Collect and compare sub-fields. Use the same "visited fragment names" list
	// for both collections so fields in a fragment reference are never
	// compared to themselves.
	conflicts := m.findConflictsBetweenSubSelectionSets(
		areMutuallyExclusive,
		fieldA.SelectionSet,
		fieldB.SelectionSet,
	)
	if conflicts == nil {
		return nil
	}
	return &ConflictMessage{
		ResponseName: fieldNameA,
		SubMessage:   conflicts.Conflicts,
		Position:     fieldB.Position,
	}
}

func sameArguments(args1, args2 []*ast.Argument) bool {
	if len(args1) != len(args2) {
		return false
	}
	for _, arg1 := range args1 {
		var matched bool
		for _, arg2 := range args2 {
			if arg1.Name == arg2.Name && sameValue(arg1.Value, arg2.Value) {
				matched = true
				break
			}
		}
		if !matched {
			return false
		}
	}
	return true
}

// sameValue reports whether two argument values are identical. Input object fields
// are compared in name order because their order is not significant, list elements
// in the order written because theirs is. Both values must be non-nil.
func sameValue(value1, value2 *ast.Value) bool {
	if value1.Kind != value2.Kind {
		return false
	}
	if value1.Raw != value2.Raw {
		return false
	}
	// Objects and lists keep their contents in Children and leave Raw empty, so the
	// comparison above cannot tell two of them apart: without the walk below, every
	// object value looks equal to every other one and fields with differing composite
	// arguments are wrongly allowed to merge.
	if len(value1.Children) != len(value2.Children) {
		return false
	}

	children1, children2 := value1.Children, value2.Children
	if value1.Kind == ast.ObjectValue {
		children1, children2 = childrenSortedByName(children1), childrenSortedByName(children2)
	}
	for i, child1 := range children1 {
		child2 := children2[i]
		if child1.Name != child2.Name || !sameValue(child1.Value, child2.Value) {
			return false
		}
	}
	return true
}

// childrenSortedByName returns the children in name order. It sorts a copy because
// the argument is live AST shared with everything else looking at the query. List
// elements are unnamed, so only object values have anything to sort.
func childrenSortedByName(children ast.ChildValueList) ast.ChildValueList {
	sorted := slices.Clone(children)
	slices.SortStableFunc(sorted, func(child1, child2 *ast.ChildValue) int {
		return strings.Compare(child1.Name, child2.Name)
	})
	return sorted
}

func doTypesConflict(walker *Walker, type1, type2 *ast.Type) bool {
	if type1.Elem != nil {
		if type2.Elem != nil {
			return doTypesConflict(walker, type1.Elem, type2.Elem)
		}
		return true
	}
	if type2.Elem != nil {
		return true
	}
	if type1.NonNull && !type2.NonNull {
		return true
	}
	if !type1.NonNull && type2.NonNull {
		return true
	}

	t1 := walker.Schema.Types[type1.NamedType]
	t2 := walker.Schema.Types[type2.NamedType]
	if (t1.Kind == ast.Scalar || t1.Kind == ast.Enum) &&
		(t2.Kind == ast.Scalar || t2.Kind == ast.Enum) {
		return t1.Name != t2.Name
	}

	return false
}

// getFieldsAndFragmentNames collects a selection set's fields and fragment spreads,
// returning the same values for every later lookup of that same selection set. Those
// values are shared, so callers must only read them. The rule's memos are keyed on
// what it returns, so collecting a selection set afresh each time would defeat them:
// a query that spreads a cyclic fragment in nested selection sets then recurses until
// the stack is gone.
func (m *overlappingFieldsCanBeMergedManager) getFieldsAndFragmentNames(
	selectionSet ast.SelectionSet,
) (*sequentialFieldsMap, []*ast.FragmentSpread) {
	key := selectionSetKey{n: len(selectionSet)}
	if key.n > 0 {
		key.first = &selectionSet[0]
	}
	if cached, ok := m.cachedFieldsAndFragmentNames[key]; ok {
		return cached.fieldsMap, cached.fragmentSpreads
	}

	fieldsMap, fragmentSpreads := collectFieldsAndFragmentNames(selectionSet)
	m.cachedFieldsAndFragmentNames[key] = &fieldsAndFragmentNames{
		fieldsMap:       fieldsMap,
		fragmentSpreads: fragmentSpreads,
	}
	return fieldsMap, fragmentSpreads
}

func collectFieldsAndFragmentNames(
	selectionSet ast.SelectionSet,
) (*sequentialFieldsMap, []*ast.FragmentSpread) {
	fieldsMap := sequentialFieldsMap{
		data: make(map[string][]*ast.Field),
	}
	var fragmentSpreads []*ast.FragmentSpread

	var walk func(selectionSet ast.SelectionSet)
	walk = func(selectionSet ast.SelectionSet) {
		for _, selection := range selectionSet {
			switch selection := selection.(type) {
			case *ast.Field:
				responseName := selection.Name
				if selection.Alias != "" {
					responseName = selection.Alias
				}
				fieldsMap.Push(responseName, selection)

			case *ast.InlineFragment:
				walk(selection.SelectionSet)

			case *ast.FragmentSpread:
				fragmentSpreads = append(fragmentSpreads, selection)
			}
		}
	}
	walk(selectionSet)

	return &fieldsMap, fragmentSpreads
}
