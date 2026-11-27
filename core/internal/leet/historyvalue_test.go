package leet_test

import (
	"math"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/runmetric"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func typedNone(key string) *spb.HistoryItem {
	return &spb.HistoryItem{
		NestedKey: strings.Split(key, "."),
		Value:     &spb.HistoryItem_None{},
	}
}

func typedBoolean(key string, b bool) *spb.HistoryItem {
	return &spb.HistoryItem{
		NestedKey: strings.Split(key, "."),
		Value:     &spb.HistoryItem_Boolean{Boolean: b},
	}
}

func typedNumber(key string, f float64) *spb.HistoryItem {
	return &spb.HistoryItem{
		NestedKey: strings.Split(key, "."),
		Value:     &spb.HistoryItem_Number{Number: f},
	}
}

func typedInteger(key string, i int64) *spb.HistoryItem {
	return &spb.HistoryItem{
		NestedKey: strings.Split(key, "."),
		Value:     &spb.HistoryItem_Integer{Integer: i},
	}
}

func typedText(key, s string) *spb.HistoryItem {
	return &spb.HistoryItem{
		NestedKey: strings.Split(key, "."),
		Value:     &spb.HistoryItem_Text{Text: s},
	}
}

func typedJSON(key, s string) *spb.HistoryItem {
	return &spb.HistoryItem{
		NestedKey: strings.Split(key, "."),
		Value:     &spb.HistoryItem_Json{Json: s},
	}
}

// parseOneMetric reads a record holding a single metric "m" at step 1.
func parseOneMetric(t *testing.T, item *spb.HistoryItem) (leet.MetricData, bool) {
	t.Helper()

	history := &spb.HistoryRecord{
		Step: &spb.HistoryStep{Num: 1},
		Item: []*spb.HistoryItem{item},
	}

	msg, ok := leet.ParseHistory("run.wandb", history, runmetric.New()).(leet.HistoryMsg)
	if !ok {
		return leet.MetricData{}, false
	}
	md, found := msg.Metrics["m"]
	return md, found
}

func TestParseHistory_PrefersTypedValue(t *testing.T) {
	md, found := parseOneMetric(t, &spb.HistoryItem{
		NestedKey: []string{"m"},
		Value:     typedNumber("m", 0.25).GetValue(),
		ValueJson: "0.75",
	})

	require.True(t, found)
	require.Equal(t, []float64{0.25}, md.Y)
}

func TestParseHistory_FallsBackToValueJSONWhenTypedUnset(t *testing.T) {
	md, found := parseOneMetric(t, &spb.HistoryItem{
		NestedKey: []string{"m"},
		ValueJson: "0.75",
	})

	require.True(t, found)
	require.Equal(t, []float64{0.75}, md.Y)
}

func TestParseHistory_TypedAndJSONAgree(t *testing.T) {
	tests := []struct {
		name      string
		typed     *spb.HistoryItem
		valueJSON string
		wantY     float64
		wantPlot  bool
	}{
		{"float", typedNumber("m", 0.5), "0.5", 0.5, true},
		{"whole float", typedNumber("m", 1), "1.0", 1, true},
		{"negative float", typedNumber("m", -2.5), "-2.5", -2.5, true},
		{"int", typedInteger("m", 3), "3", 3, true},
		{
			// Both forms round the same way above 2^53.
			name:      "int64 above 2^53",
			typed:     typedInteger("m", 9007199254740993),
			valueJSON: "9007199254740993",
			wantY:     9007199254740992,
			wantPlot:  true,
		},
		{"nan", typedNumber("m", math.NaN()), "NaN", math.NaN(), true},
		{"positive infinity", typedNumber("m", math.Inf(1)), "Infinity", math.Inf(1), true},
		{"negative infinity", typedNumber("m", math.Inf(-1)), "-Infinity", math.Inf(-1), true},
		{
			// A string that holds a number plots on both paths.
			name:      "numeric string",
			typed:     typedText("m", "42"),
			valueJSON: `"42"`,
			wantY:     42,
			wantPlot:  true,
		},
		{"text string", typedText("m", "abc"), `"abc"`, 0, false},
		{
			name:      "bool",
			typed:     typedBoolean("m", true),
			valueJSON: "true",
			wantPlot:  false,
		},
		{
			name:      "null",
			typed:     typedNone("m"),
			valueJSON: "null",
			wantPlot:  false,
		},
		{
			name:      "json object",
			typed:     typedJSON("m", `{"a":1}`),
			valueJSON: `{"a":1}`,
			wantPlot:  false,
		},
		{
			name:      "json number",
			typed:     typedJSON("m", "9223372036854775808"),
			valueJSON: "9223372036854775808",
			wantY:     9223372036854775808,
			wantPlot:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			typedMD, typedFound := parseOneMetric(t, &spb.HistoryItem{
				NestedKey: []string{"m"},
				Value:     tt.typed.GetValue(),
			})
			jsonMD, jsonFound := parseOneMetric(t, &spb.HistoryItem{
				NestedKey: []string{"m"},
				ValueJson: tt.valueJSON,
			})

			require.Equal(t, tt.wantPlot, typedFound, "typed form")
			require.Equal(t, tt.wantPlot, jsonFound, "json form")
			if !tt.wantPlot {
				return
			}

			require.Len(t, typedMD.Y, 1)
			require.Len(t, jsonMD.Y, 1)
			if math.IsNaN(tt.wantY) {
				require.True(t, math.IsNaN(typedMD.Y[0]), "typed form")
				require.True(t, math.IsNaN(jsonMD.Y[0]), "json form")
				return
			}
			require.Equal(t, tt.wantY, typedMD.Y[0], "typed form")
			require.Equal(t, tt.wantY, jsonMD.Y[0], "json form")
		})
	}
}

// Check different ways of representing _step in typed form.
func TestParseHistory_TypedStep(t *testing.T) {
	tests := []struct {
		name  string
		step  *spb.HistoryItem
		wantX float64
	}{
		{"int step", typedInteger("_step", 7), 7},
		{"float step", typedNumber("_step", 7), 0},
		{"JSON integer step", typedJSON("_step", "7"), 7},
		{"JSON float step", typedJSON("_step", "7.0"), 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			history := &spb.HistoryRecord{Item: []*spb.HistoryItem{
				tt.step,
				typedNumber("m", 0.5),
			}}

			msg, ok := leet.ParseHistory("run.wandb", history, runmetric.New()).(leet.HistoryMsg)
			require.True(t, ok)
			require.Equal(t, []float64{tt.wantX}, msg.Metrics["m"].X)
		})
	}
}

func TestParseHistory_TypedMediaFields(t *testing.T) {
	runPath := filepath.Join("tmp", "offline-run-123", "run-123.wandb")
	relPath := filepath.Join("media", "images", "sample_7.png")

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			typedInteger("_step", 7),
			typedText("img._type", "image-file"),
			typedText("img.path", relPath),
			typedText("img.format", "png"),
			typedInteger("img.width", 64),
			typedInteger("img.height", 32),
			typedText("img.caption", "step=7"),
		},
	}

	msg, ok := leet.ParseHistory(runPath, history, runmetric.New()).(leet.HistoryMsg)
	require.True(t, ok)
	require.Len(t, msg.Media["img"], 1)

	point := msg.Media["img"][0]
	require.Equal(t, 7.0, point.X)
	require.Equal(t, relPath, point.RelativePath)
	require.Equal(t, "step=7", point.Caption)
	require.Equal(t, "png", point.Format)
	require.Equal(t, 64, point.Width)
	require.Equal(t, 32, point.Height)
}

func TestParseHistory_TypedSeparatedImages(t *testing.T) {
	runPath := filepath.Join("tmp", "offline-run-123", "run-123.wandb")

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			typedInteger("_step", 1),
			typedText("imgs._type", "images/separated"),
			typedJSON("imgs.filenames", `["a.png","b.png"]`),
			typedJSON("imgs.captions", `["first","second"]`),
		},
	}

	msg, ok := leet.ParseHistory(runPath, history, runmetric.New()).(leet.HistoryMsg)
	require.True(t, ok)
	require.Len(t, msg.Media["imgs[0]"], 1)
	require.Len(t, msg.Media["imgs[1]"], 1)
	require.Equal(t, "a.png", msg.Media["imgs[0]"][0].RelativePath)
	require.Equal(t, "first", msg.Media["imgs[0]"][0].Caption)
	require.Equal(t, "second", msg.Media["imgs[1]"][0].Caption)
}
