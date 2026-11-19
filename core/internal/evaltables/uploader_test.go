package evaltables_test

import (
	"math"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/evaltables"
	"github.com/wandb/wandb/core/internal/runbranch"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var testRunPath = runbranch.RunPath{
	Entity:  "test-entity",
	Project: "test-project",
	RunID:   "test-run",
}

func encode(
	t *testing.T,
	request *spb.EvalTableData,
) (*evaltables.EncodedTable, error) {
	t.Helper()
	return evaltables.Encode(request, testRunPath)
}

func boolValue(v bool) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_BoolValue{BoolValue: v}}
}

func intValue(v int64) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_IntValue{IntValue: v}}
}

func numberValue(v float64) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_NumberValue{NumberValue: v}}
}

func stringValue(v string) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_StringValue{StringValue: v}}
}

func jsonValue(v string) *spb.EvalTableValue {
	return &spb.EvalTableValue{Value: &spb.EvalTableValue_JsonValue{JsonValue: v}}
}

func mediaValue(v string) *spb.EvalTableValue {
	return &spb.EvalTableValue{
		Value: &spb.EvalTableValue_WandbMediaJson{WandbMediaJson: v},
	}
}

// nullValue returns an unset value, which is null.
func nullValue() *spb.EvalTableValue {
	return &spb.EvalTableValue{}
}

func values(v ...*spb.EvalTableValue) *spb.EvalTableRowValues {
	return &spb.EvalTableRowValues{Values: v}
}

var outputFieldX = []*spb.EvalTableField{
	{Source: "output", Name: "x", ValueType: "string"},
}

func TestEncode_AllValueTypes(t *testing.T) {
	table, err := encode(t, &spb.EvalTableData{
		Name: "my-table",
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "flag", ValueType: "boolean"},
			{Source: "input", Name: "count", ValueType: "integer"},
			{Source: "input", Name: "temperature", ValueType: "number"},
			{Source: "input", Name: "prompt", ValueType: "string"},
			{Source: "input", Name: "config", ValueType: "json"},
			{Source: "input", Name: "note", ValueType: "string"},
			{Source: "output", Name: "answer", ValueType: "string"},
		},
		Scorers: []*spb.EvalTableScorer{
			{Name: "passed", ValueType: "boolean"},
			{Name: "votes", ValueType: "integer"},
			{Name: "accuracy", ValueType: "number"},
			{Name: "rank", ValueType: "number"},
			{Name: "grade", ValueType: "string"},
		},
		Rows: []*spb.EvalTableRow{
			{
				Input: values(
					boolValue(true),
					intValue(9007199254740993),
					numberValue(0.25),
					stringValue("draw <a> cat & dog"),
					jsonValue(`{"seed":7,"tags":["a","b"]}`),
					nullValue(),
				),
				Output: values(stringValue("a cat")),
				Scores: []*spb.EvalTableValue{
					boolValue(false),
					intValue(3),
					numberValue(0.5),
					intValue(2),
					stringValue("B"),
				},
			},
			{
				Scores: []*spb.EvalTableValue{
					nullValue(), nullValue(), nullValue(), nullValue(), nullValue(),
				},
				ExampleKey: "2",
			},
		},
	})

	require.NoError(t, err)
	assert.JSONEq(t, `{
		"dataset_fields": [
			{"source": "input", "name": "flag", "value_type": "boolean"},
			{"source": "input", "name": "count", "value_type": "integer"},
			{"source": "input", "name": "temperature", "value_type": "number"},
			{"source": "input", "name": "prompt", "value_type": "string"},
			{"source": "input", "name": "config", "value_type": "json"},
			{"source": "input", "name": "note", "value_type": "string"},
			{"source": "output", "name": "answer", "value_type": "string"}
		],
		"scorers": [
			{"name": "passed", "value_type": "boolean"},
			{"name": "votes", "value_type": "integer"},
			{"name": "accuracy", "value_type": "number"},
			{"name": "rank", "value_type": "number"},
			{"name": "grade", "value_type": "string"}
		]
	}`, table.ColumnsJSON(t))
	// Compare bytes, since JSONEq would decode the large integer as float64.
	assert.Equal(t,
		`[`+
			`{"input":{`+
			`"flag":true,`+
			`"count":9007199254740993,`+
			`"temperature":0.25,`+
			`"prompt":"draw \u003ca\u003e cat \u0026 dog",`+
			`"config":{"seed":7,"tags":["a","b"]},`+
			`"note":null`+
			`},`+
			`"output":{"answer":"a cat"},`+
			`"scores":{"passed":false,"votes":3,"accuracy":0.5,"rank":2,"grade":"B"}},`+
			`{"input":null,"output":null,`+
			`"scores":{"passed":null,"votes":null,"accuracy":null,"rank":null,"grade":null},`+
			`"example_key":"2"}`+
			`]`,
		table.CESRowsJSON(t))
}

func TestEncode_RejectsUnknownColumnTypes(t *testing.T) {
	testCases := []struct {
		name    string
		request *spb.EvalTableData
		wantErr string
	}{
		{
			name: "source",
			request: &spb.EvalTableData{
				DatasetFields: []*spb.EvalTableField{
					{Source: "metadata", Name: "a", ValueType: "string"},
				},
			},
			wantErr: `field "a" has unknown source "metadata"`,
		},
		{
			name: "field value type",
			request: &spb.EvalTableData{
				DatasetFields: []*spb.EvalTableField{
					{Source: "input", Name: "a", ValueType: "float"},
				},
			},
			wantErr: `field "a" has unknown value type "float"`,
		},
		{
			name: "scorer value type",
			request: &spb.EvalTableData{
				Scorers: []*spb.EvalTableScorer{{Name: "a", ValueType: "json"}},
			},
			wantErr: `scorer "a" has unknown value type "json"`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, tc.request)

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}

func TestEncode_RejectsDuplicateColumns(t *testing.T) {
	testCases := []struct {
		name    string
		table   *spb.EvalTableData
		wantErr string
	}{
		{
			name: "field",
			table: &spb.EvalTableData{
				DatasetFields: []*spb.EvalTableField{
					{Source: "input", Name: "a", ValueType: "string"},
					{Source: "input", Name: "a", ValueType: "integer"},
				},
			},
			wantErr: `duplicate input field "a"`,
		},
		{
			name: "scorer",
			table: &spb.EvalTableData{
				Scorers: []*spb.EvalTableScorer{
					{Name: "a", ValueType: "number"},
					{Name: "a", ValueType: "boolean"},
				},
			},
			wantErr: `duplicate scorer "a"`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, tc.table)

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}

func TestEncode_RejectsOversizedColumns(t *testing.T) {
	// Each "<" is escaped to 6 bytes, so the name alone exceeds the limit.
	name := strings.Repeat("<", 3<<20)
	_, err := encode(t, &spb.EvalTableData{
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: name, ValueType: "string"},
		},
	})

	assert.ErrorContains(t, err, "columns request is")
}

func TestEncode_RejectsRowsThatDontFitColumns(t *testing.T) {
	testCases := []struct {
		name    string
		field   *spb.EvalTableField
		row     *spb.EvalTableRow
		wantErr string
	}{
		{
			name:    "too few input values",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "string"},
			row:     &spb.EvalTableRow{Input: values()},
			wantErr: "row has 0 input values, expected 1 (row 0)",
		},
		{
			name:    "too many output values",
			field:   &spb.EvalTableField{Source: "output", Name: "a", ValueType: "string"},
			row:     &spb.EvalTableRow{Output: values(nullValue(), nullValue())},
			wantErr: "row has 2 output values, expected 1 (row 0)",
		},
		{
			name:    "score without scorer",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "string"},
			row:     &spb.EvalTableRow{Scores: []*spb.EvalTableValue{intValue(1)}},
			wantErr: "row has 1 score values, expected 0 (row 0)",
		},
		{
			name:    "string in integer column",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "integer"},
			row:     &spb.EvalTableRow{Input: values(stringValue("1"))},
			wantErr: `field "a": string value in "integer" column`,
		},
		{
			name:    "number in integer column",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "integer"},
			row:     &spb.EvalTableRow{Input: values(numberValue(1))},
			wantErr: `field "a": number value in "integer" column`,
		},
		{
			name:    "W&B media in JSON column",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "json"},
			row:     &spb.EvalTableRow{Input: values(mediaValue(`{}`))},
			wantErr: `field "a": W&B media value in "json" column`,
		},
		{
			name: "JSON in media column",
			field: &spb.EvalTableField{
				Source:         "input",
				Name:           "a",
				ValueType:      "json",
				WandbMediaType: "image-file",
			},
			row:     &spb.EvalTableRow{Input: values(jsonValue(`{}`))},
			wantErr: `field "a": JSON value in image-file column`,
		},
		{
			name:    "invalid JSON",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "json"},
			row:     &spb.EvalTableRow{Input: values(jsonValue(`{"a":`))},
			wantErr: `field "a": invalid JSON`,
		},
		{
			name:    "NaN",
			field:   &spb.EvalTableField{Source: "input", Name: "a", ValueType: "number"},
			row:     &spb.EvalTableRow{Input: values(numberValue(math.NaN()))},
			wantErr: `field "a": json: unsupported value: NaN`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, &spb.EvalTableData{
				DatasetFields: []*spb.EvalTableField{tc.field},
				Rows:          []*spb.EvalTableRow{tc.row},
			})

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}

func TestEncode_RejectsOversizedRow(t *testing.T) {
	// Each "\n" is escaped to 2 bytes, so the encoded row exceeds 16 MiB.
	_, err := encode(t, &spb.EvalTableData{
		DatasetFields: outputFieldX,
		Rows: []*spb.EvalTableRow{
			{Output: values(stringValue(strings.Repeat("\n", 8<<20)))},
		},
	})

	assert.ErrorContains(t, err, "row is")
	assert.ErrorContains(t, err, "(row 0)")
}

func TestEncode_ConvertsMedia(t *testing.T) {
	// W&B media JSON, as from Python's Media.to_json.
	image := `{` +
		`"_type":"image-file",` +
		`"path":"media/eval_tables/images/eval/cat.png",` +
		`"sha256":"aaa",` +
		`"size":1024,` +
		`"format":"png",` +
		`"width":32,` +
		`"height":24,` +
		`"caption":"a cat",` +
		`"grouping":1,` +
		`"boxes":{"predictions":{` +
		`"_type":"boxes2D",` +
		`"path":"media/eval_tables/boxes/eval/cat.boxes2D.json",` +
		`"sha256":"bbb",` +
		`"size":10` +
		`}},` +
		`"masks":{"truth":{` +
		`"_type":"mask",` +
		`"artifact_path":"wandb-artifact://_id/abc/mask.png",` +
		`"sha256":"ccc",` +
		`"size":20` +
		`}}` +
		`}`
	audio := `{` +
		`"_type":"audio-file",` +
		`"artifact_path":"wandb-artifact://_id/def/meow.wav",` +
		`"_latest_artifact_path":"wandb-artifact://entity/project/sounds:latest/meow.wav",` +
		`"sha256":"ddd",` +
		`"size":2048,` +
		`"caption":"meow"` +
		`}`
	video := `{` +
		`"_type":"video-file",` +
		`"path":"media/eval tables/videos/cat#1.mp4",` +
		`"sha256":"eee",` +
		`"size":4096,` +
		`"width":64,` +
		`"height":48` +
		`}`

	table, err := encode(t, &spb.EvalTableData{
		Name: "my-table",
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "prompt", ValueType: "string"},
			{Source: "output", Name: "answer", ValueType: "string"},
			{Source: "output", Name: "image", ValueType: "json", WandbMediaType: "image-file"},
			{Source: "output", Name: "audio", ValueType: "json", WandbMediaType: "audio-file"},
			{Source: "output", Name: "video", ValueType: "json", WandbMediaType: "video-file"},
		},
		Rows: []*spb.EvalTableRow{{
			Input: values(stringValue("draw a cat")),
			Output: values(
				stringValue("a cat"),
				mediaValue(image),
				mediaValue(audio),
				mediaValue(video),
			),
		}},
	})

	require.NoError(t, err)
	assert.JSONEq(t, `{
		"dataset_fields": [
			{"source": "input", "name": "prompt", "value_type": "string"},
			{"source": "output", "name": "answer", "value_type": "string"},
			{
				"source": "output",
				"name": "image",
				"value_type": "json",
				"extension_type": "wandb-image",
				"extension_schema_version": 1
			},
			{
				"source": "output",
				"name": "audio",
				"value_type": "json",
				"extension_type": "wandb-audio",
				"extension_schema_version": 1
			},
			{
				"source": "output",
				"name": "video",
				"value_type": "json",
				"extension_type": "wandb-video",
				"extension_schema_version": 1
			}
		],
		"scorers": []
	}`, table.ColumnsJSON(t))
	assert.JSONEq(t, `[{
		"input": {"prompt": "draw a cat"},
		"output": {
			"answer": "a cat",
			"image": {
				"extension_type": "wandb-image",
				"schema_version": 1,
				"wb_media_type": "image-file",
				"format": "png",
				"sha256": "aaa",
				"size": 1024,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/images/eval/cat.png",
				"width": 32,
				"height": 24,
				"caption": "a cat",
				"boxes": {"predictions": {
					"_type": "boxes2D",
					"sha256": "bbb",
					"size": 10,
					"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval_tables/boxes/eval/cat.boxes2D.json"
				}},
				"masks": {"truth": {
					"_type": "mask",
					"sha256": "ccc",
					"size": 20,
					"uri": "wandb-artifact://_id/abc/mask.png"
				}}
			},
			"audio": {
				"extension_type": "wandb-audio",
				"schema_version": 1,
				"wb_media_type": "audio-file",
				"sha256": "ddd",
				"size": 2048,
				"uri": "wandb-artifact://_id/def/meow.wav",
				"caption": "meow"
			},
			"video": {
				"extension_type": "wandb-video",
				"schema_version": 1,
				"wb_media_type": "video-file",
				"sha256": "eee",
				"size": 4096,
				"uri": "wandb-run-file://test-entity/test-project/test-run/media/eval%20tables/videos/cat%231.mp4",
				"width": 64,
				"height": 48
			}
		},
		"scores": {}
	}]`, table.CESRowsJSON(t))
}

func TestEncode_KeepsNullMedia(t *testing.T) {
	table, err := encode(t, &spb.EvalTableData{
		DatasetFields: []*spb.EvalTableField{
			{Source: "input", Name: "image", ValueType: "json", WandbMediaType: "image-file"},
			{Source: "output", Name: "image", ValueType: "json", WandbMediaType: "image-file"},
		},
		Rows: []*spb.EvalTableRow{
			{Input: values(nullValue())},
			{Output: values(nullValue())},
		},
	})

	require.NoError(t, err)
	assert.Equal(t,
		`[`+
			`{"input":{"image":null},"output":null,"scores":{}},`+
			`{"input":null,"output":{"image":null},"scores":{}}`+
			`]`,
		table.CESRowsJSON(t))
}

func TestEncode_RejectsInvalidMedia(t *testing.T) {
	testCases := []struct {
		name      string
		mediaType string
		media     string
		wantErr   string
	}{
		{
			name:      "unknown media type",
			mediaType: "html-file",
			media:     `{"_type":"html-file","path":"a.html","sha256":"a","size":1}`,
			wantErr:   `field "media" has unknown media type "html-file"`,
		},
		{
			name:      "mismatched media type",
			mediaType: "image-file",
			media:     `{"_type":"audio-file","path":"a.wav","sha256":"a","size":1}`,
			wantErr:   `field "media": expected image-file media, got "audio-file"`,
		},
		{
			name:      "no file",
			mediaType: "audio-file",
			media:     `{"_type":"audio-file","sha256":"a","size":1}`,
			wantErr:   `field "media": media has no path or artifact path`,
		},
		{
			name:      "overlay without file",
			mediaType: "image-file",
			media: `{"_type":"image-file","path":"a.png","format":"png",` +
				`"sha256":"a","size":1,"boxes":{"b":{"_type":"boxes2D"}}}`,
			wantErr: `field "media": boxes "b": media has no path or artifact path`,
		},
		{
			name:      "invalid JSON",
			mediaType: "image-file",
			media:     `{"_type":`,
			wantErr:   `field "media": invalid media`,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := encode(t, &spb.EvalTableData{
				DatasetFields: []*spb.EvalTableField{{
					Source:         "output",
					Name:           "media",
					ValueType:      "json",
					WandbMediaType: tc.mediaType,
				}},
				Rows: []*spb.EvalTableRow{{Output: values(mediaValue(tc.media))}},
			})

			assert.ErrorContains(t, err, tc.wantErr)
			assert.True(t, evaltables.IsUsageError(err))
		})
	}
}
