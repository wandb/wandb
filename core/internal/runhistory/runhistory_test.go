package runhistory_test

import (
	"math"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSetFromRecord_NestedKey(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&spb.HistoryItem{
		NestedKey: []string{"a", "b"},
		ValueJson: "1",
	})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t, `{"a": {"b": 1}}`, string(encoded))
}

func TestSetRecord_NestedValue(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&spb.HistoryItem{
		Key:       "a",
		ValueJson: `{"b": 1, "c": {"d": 2.5, "e": "e", "f": false}}`,
	})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{"a": {"b": 1, "c": {"d": 2.5, "e": "e", "f": false}}}`,
		string(encoded))
}

func TestSetRecord_UnmarshalError(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&spb.HistoryItem{
		Key:       "a",
		ValueJson: "invalid",
	})

	assert.ErrorContains(t, err, "failed to unmarshal")
}

func TestNaN(t *testing.T) {
	rh := runhistory.New()

	_ = rh.SetFromRecord(&spb.HistoryItem{Key: "+inf", ValueJson: "Infinity"})
	_ = rh.SetFromRecord(&spb.HistoryItem{Key: "-inf", ValueJson: "-Infinity"})
	_ = rh.SetFromRecord(&spb.HistoryItem{Key: "nan", ValueJson: "NaN"})

	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	asMap, err := simplejsonext.UnmarshalObject(encoded)
	require.NoError(t, err)
	assert.Equal(t, asMap["+inf"], math.Inf(1))
	assert.Equal(t, asMap["-inf"], math.Inf(-1))
	assert.True(t, math.IsNaN(asMap["nan"].(float64))) // NaN != NaN
}

func TestForEachNumber(t *testing.T) {
	rh := runhistory.New()
	rh.SetInt(pathtree.PathOf("the", "number", "five"), 5)
	_ = rh.SetFromRecord(
		&spb.HistoryItem{
			Key: "x",
			ValueJson: `{
				"a": 1,
				"b": 2.5,
				"c": Infinity,
				"d": -Infinity,
				"e": NaN,
				"f": "ignored",
				"g": [5, 7, 8]
			}`,
		})

	numbers := make(map[string]float64)
	rh.ForEachNumber(func(path pathtree.TreePath, value float64) bool {
		numbers[strings.Join(path.Labels(), ".")] = value
		return true
	})

	assert.Len(t, numbers, 6)
	assert.Equal(t, 5.0, numbers["the.number.five"])
	assert.Equal(t, 1.0, numbers["x.a"])
	assert.Equal(t, 2.5, numbers["x.b"])
	assert.Equal(t, math.Inf(1), numbers["x.c"])
	assert.Equal(t, math.Inf(-1), numbers["x.d"])
	assert.True(t, math.IsNaN(numbers["x.e"])) // NaN != NaN
}

func typedItem(key string, value *spb.HistoryValue) *spb.HistoryItem {
	return &spb.HistoryItem{Key: key, Value: value}
}

func TestSetFromRecord_TypedValueKinds(t *testing.T) {
	tests := []struct {
		name  string
		value *spb.HistoryValue
		want  string
	}{
		{
			"null",
			&spb.HistoryValue{Kind: spb.HistoryValue_KIND_NULL},
			`{"a": null}`,
		},
		{
			"float",
			&spb.HistoryValue{
				Kind:       spb.HistoryValue_KIND_FLOAT,
				FloatValue: 2.5,
			},
			`{"a": 2.5}`,
		},
		{
			"int",
			&spb.HistoryValue{
				Kind:     spb.HistoryValue_KIND_INT,
				IntValue: -7,
			},
			`{"a": -7}`,
		},
		{
			"bool",
			&spb.HistoryValue{
				Kind:      spb.HistoryValue_KIND_BOOL,
				BoolValue: true,
			},
			`{"a": true}`,
		},
		{
			"string",
			&spb.HistoryValue{
				Kind:        spb.HistoryValue_KIND_STRING,
				StringValue: "hi",
			},
			`{"a": "hi"}`,
		},
		{
			// An object keeps its tree structure, so that a nested key
			// reads the same through either form.
			"json object",
			&spb.HistoryValue{
				Kind:      spb.HistoryValue_KIND_JSON,
				JsonValue: `{"b": 1, "c": {"d": 2.5}}`,
			},
			`{"a": {"b": 1, "c": {"d": 2.5}}}`,
		},
		{
			"json array",
			&spb.HistoryValue{
				Kind:      spb.HistoryValue_KIND_JSON,
				JsonValue: `[1, 2]`,
			},
			`{"a": [1, 2]}`,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			rh := runhistory.New()

			require.NoError(t, rh.SetFromRecord(typedItem("a", test.value)))

			encoded, err := rh.ToExtendedJSON()
			require.NoError(t, err)
			assert.JSONEq(t, test.want, string(encoded))
		})
	}
}

func TestSetFromRecord_TypedValuePreferredOverValueJson(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&spb.HistoryItem{
		Key: "a",
		Value: &spb.HistoryValue{
			Kind:     spb.HistoryValue_KIND_INT,
			IntValue: 1,
		},
		ValueJson: "2",
	})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t, `{"a": 1}`, string(encoded))
}

func TestSetFromRecord_FallsBackToValueJson(t *testing.T) {
	rh := runhistory.New()

	// This is what an older SDK wrote: no typed value at all.
	err := rh.SetFromRecord(&spb.HistoryItem{Key: "a", ValueJson: "2"})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t, `{"a": 2}`, string(encoded))
}

func TestSetFromRecord_TypedNestedKey(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&spb.HistoryItem{
		NestedKey: []string{"a", "b"},
		Value: &spb.HistoryValue{
			Kind:     spb.HistoryValue_KIND_INT,
			IntValue: 1,
		},
	})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t, `{"a": {"b": 1}}`, string(encoded))
}

func TestSetFromRecord_TypedIntKeepsExactValueAbove2To53(t *testing.T) {
	rh := runhistory.New()

	const exact = int64(1)<<53 + 1
	err := rh.SetFromRecord(typedItem("a", &spb.HistoryValue{
		Kind:     spb.HistoryValue_KIND_INT,
		IntValue: exact,
	}))

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.Equal(t, `{"a":9007199254740993}`, string(encoded))
}

func TestSetFromRecord_TypedNonFiniteFloats(t *testing.T) {
	rh := runhistory.New()

	for key, value := range map[string]float64{
		"+inf": math.Inf(1),
		"-inf": math.Inf(-1),
		"nan":  math.NaN(),
	} {
		require.NoError(t, rh.SetFromRecord(typedItem(key, &spb.HistoryValue{
			Kind:       spb.HistoryValue_KIND_FLOAT,
			FloatValue: value,
		})))
	}

	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	asMap, err := simplejsonext.UnmarshalObject(encoded)
	require.NoError(t, err)
	assert.Equal(t, math.Inf(1), asMap["+inf"])
	assert.Equal(t, math.Inf(-1), asMap["-inf"])
	assert.True(t, math.IsNaN(asMap["nan"].(float64))) // NaN != NaN
}

func TestSetFromRecord_TypedUnknownKind(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(typedItem("a", &spb.HistoryValue{
		Kind: spb.HistoryValue_KIND_UNSPECIFIED,
	}))

	assert.ErrorContains(t, err, "unknown history value kind")
}

func TestSetFromRecord_TypedJsonUnmarshalError(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(typedItem("a", &spb.HistoryValue{
		Kind:      spb.HistoryValue_KIND_JSON,
		JsonValue: "invalid",
	}))

	assert.ErrorContains(t, err, "failed to unmarshal typed history item value")
}

func TestSetFromRecord_TypedEmptyKey(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(typedItem("", &spb.HistoryValue{
		Kind: spb.HistoryValue_KIND_NULL,
	}))

	assert.ErrorContains(t, err, "empty history item key")
}
