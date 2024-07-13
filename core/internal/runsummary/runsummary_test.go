package runsummary_test

import (
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestApplyUpdate(t *testing.T) {
	rs := runsummary.New(runsummary.Params{})
	summary := &service.SummaryRecord{
		Update: []*service.SummaryItem{
			{
				Key:       "setting1",
				ValueJson: "69",
			},
			{
				NestedKey: []string{"config", "setting2"},
				ValueJson: `{"value": 42}`,
			},
		},
	}

	rs.ApplyChangeRecord(summary,
		func(err error) {
			t.Error("onError should not be called", err)
		})

	encoded, err := rs.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"setting1": 69,
			"config": {"setting2": {"value": 42}}
		}`,
		string(encoded))
}

func TestApplyRemove(t *testing.T) {
	rs := runsummary.New(runsummary.Params{})
	rs.ApplyChangeRecord(&service.SummaryRecord{
		Update: []*service.SummaryItem{
			{Key: "setting0", ValueJson: "69"},
			{Key: "config", ValueJson: `{"setting1": 42, "setting2": "goodbye"}`},
		},
	}, func(err error) {})
	summary := &service.SummaryRecord{
		Remove: []*service.SummaryItem{
			{
				NestedKey: []string{"config", "setting2"},
			},
		},
	}

	rs.ApplyChangeRecord(summary,
		func(err error) {
			t.Error("onError should not be called", err)
		})

	encoded, err := rs.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"setting0": 69,
			"config": {"setting1": 42}
		}`,
		string(encoded))
}

func key(item *service.SummaryItem) []string {
	if len(item.GetNestedKey()) > 0 {
		return item.GetNestedKey()
	}
	return []string{item.GetKey()}
}

// TestApplyUpdateSpecialValues checks behavior with NaN and Inf values.
// These values are supported by our special json package and should not return an error.
func TestApplyUpdateSpecialValues(t *testing.T) {

	rs := runsummary.New(runsummary.Params{})
	summary := &service.SummaryRecord{
		Update: []*service.SummaryItem{
			{
				Key:       "nan",
				ValueJson: `NaN`,
			},
			{
				Key:       "inf",
				ValueJson: `Infinity`,
			},
			{
				NestedKey: []string{"special", "ninf"},
				ValueJson: `-Infinity`,
			},
		},
	}
	rs.ApplyChangeRecord(summary,
		func(err error) {
			t.Error("onError should not be called", err)
		})

	actualItems, err := rs.Flatten()
	if err != nil {
		t.Fatal("Flatten failed:", err)
	}

	expectedItems := summary.Update

	// Sort slices by joining keys into a single string for comparison
	// (since order is not guaranteed)
	sort.Slice(actualItems, func(i, j int) bool {
		return strings.Join(key(actualItems[i]), ".") <
			strings.Join(key(actualItems[j]), ".")
	})

	sort.Slice(expectedItems, func(i, j int) bool {
		return strings.Join(key(expectedItems[i]), ".") <
			strings.Join(key(expectedItems[j]), ".")
	})

	if !reflect.DeepEqual(actualItems, expectedItems) {
		t.Errorf("Expected %v, got %v", expectedItems, actualItems)
	}
}

func TestSerialize(t *testing.T) {
	rs := runsummary.New(runsummary.Params{})
	rs.ApplyChangeRecord(&service.SummaryRecord{
		Update: []*service.SummaryItem{
			{Key: "config", ValueJson: `{"setting1":"value1"}`},
		},
	}, func(err error) {})
	actualJson, err := rs.Serialize()
	if err != nil {
		t.Fatal("Serialize failed:", err)
	}

	expectedJson := "{\"config\":{\"setting1\":\"value1\"}}"

	if string(actualJson) != expectedJson {
		t.Errorf("Expected %v, got %v", expectedJson, string(actualJson))
	}

}
