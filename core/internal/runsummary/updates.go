package runsummary

import (
	"errors"
	"fmt"
	"strings"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/pathtree"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Updates is a collection of updates to a run's summary.
//
// A nil value acts like no updates but cannot be mutated with Merge.
type Updates struct {
	// update contains values to add to or change in the summary.
	//
	// Leaves in the tree are JSON-encoded values (supporting +-Infinity
	// and NaN).
	update *pathtree.PathTree[string]

	// remove contains paths to remove from the summary.
	//
	// None of the paths appear in 'update'.
	remove *pathtree.PathTree[struct{}]
}

// IsEmpty returns whether the Updates instance contains any changes.
//
// Returns true given nil.
func (u *Updates) IsEmpty() bool {
	return u == nil || (u.update.IsEmpty() && u.remove.IsEmpty())
}

// NoUpdates returns a mutable Updates instance that makes no changes.
func NoUpdates() *Updates {
	return &Updates{
		update: pathtree.New[string](),
		remove: pathtree.New[struct{}](),
	}
}

// FromProto makes Updates from a SummaryRecord.
func FromProto(record *spb.SummaryRecord) *Updates {
	u := NoUpdates()

	for _, item := range record.GetUpdate() {
		path := keyPath(item)
		u.update.Set(path, item.GetValueJson())
	}

	for _, item := range record.GetRemove() {
		path := keyPath(item)
		u.remove.Set(path, struct{}{})
		u.update.Remove(path)
	}

	return u
}

// Merge merges the given Updates into this Updates instance,
// so that `u1.Apply(rs); u2.Apply(rs)` has the same effect on `rs` as
// `u1.Merge(u2); u1.Apply(rs)`.
func (u *Updates) Merge(newUpdates *Updates) {
	if newUpdates == nil {
		return
	}

	newUpdates.update.ForEachLeaf(
		func(path pathtree.TreePath, valueJSON string) bool {
			u.remove.Remove(path)
			u.update.Set(path, valueJSON)
			return true
		})

	newUpdates.remove.ForEachLeaf(
		func(path pathtree.TreePath, _ struct{}) bool {
			u.remove.Set(path, struct{}{})
			u.update.Remove(path)
			return true
		})
}

// Apply modifies the summary with these updates.
//
// A partial success is possible if some values' JSON strings cannot be
// unmarshaled.
func (u *Updates) Apply(rs *RunSummary) error {
	if u == nil {
		return nil
	}

	var errs []error

	u.update.ForEachLeaf(
		func(path pathtree.TreePath, valueJSON string) bool {
			value, err := simplejsonext.UnmarshalString(valueJSON)

			if err != nil {
				errs = append(errs,
					fmt.Errorf("error in path %s: %v", toDottedPath(path), err))
			} else {
				rs.Set(path, value)
			}

			return true
		})

	u.remove.ForEachLeaf(
		func(path pathtree.TreePath, _ struct{}) bool {
			rs.Remove(path)
			return true
		})

	if len(errs) > 0 {
		return fmt.Errorf(
			"runsummary: failed to update some keys: %v",
			errors.Join(errs...))
	}

	return nil
}

// toDottedPath escapes dots in the path components and concatenates them
// using dots.
func toDottedPath(path pathtree.TreePath) string {
	var escapedLabels []string

	for _, label := range path.Labels() {
		escapedLabels = append(escapedLabels,
			strings.ReplaceAll(label, ".", "\\."))
	}

	return strings.Join(escapedLabels, ".")
}

// keyPath returns the key on the summary item as a path.
func keyPath(item *spb.SummaryItem) pathtree.TreePath {
	if len(item.GetNestedKey()) > 0 {
		return pathtree.PathOf(
			item.GetNestedKey()[0],
			item.GetNestedKey()[1:]...,
		)
	}
	return pathtree.PathOf(item.GetKey())
}
