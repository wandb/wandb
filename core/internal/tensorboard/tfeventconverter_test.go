package tensorboard_test

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
	"github.com/wandb/wandb/core/pkg/observability"
)

func scalarValue(tag string, plugin string, value float32) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_SimpleValue{
			SimpleValue: value,
		},
		Metadata: &tbproto.SummaryMetadata{
			PluginData: &tbproto.SummaryMetadata_PluginData{
				PluginName: plugin,
			},
		},
	}
}

func tensorValue(tag string, plugin string, dims []int, values ...float32) *tbproto.Summary_Value {
	tensor := &tbproto.TensorProto{
		Dtype:    tbproto.DataType_DT_FLOAT,
		FloatVal: values,
	}

	if dims != nil {
		var dimsProto []*tbproto.TensorShapeProto_Dim
		for _, size := range dims {
			dimsProto = append(dimsProto,
				&tbproto.TensorShapeProto_Dim{Size: int64(size)})
		}

		tensor.TensorShape = &tbproto.TensorShapeProto{
			Dim: dimsProto,
		}
	}

	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Tensor{
			Tensor: tensor,
		},
		Metadata: &tbproto.SummaryMetadata{
			PluginData: &tbproto.SummaryMetadata_PluginData{
				PluginName: plugin,
			},
		},
	}
}

func tensorValueStrings(
	tag string,
	plugin string,
	data ...string,
) *tbproto.Summary_Value {
	stringVal := make([][]byte, 0, len(data))
	for _, x := range data {
		stringVal = append(stringVal, []byte(x))
	}

	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Tensor{
			Tensor: &tbproto.TensorProto{
				StringVal: stringVal,
			},
		},
		Metadata: &tbproto.SummaryMetadata{
			PluginData: &tbproto.SummaryMetadata_PluginData{
				PluginName: plugin,
			},
		},
	}
}

func tensorValueBytes(
	tag string,
	plugin string,
	dtype tbproto.DataType,
	data []byte,
) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Tensor{
			Tensor: &tbproto.TensorProto{
				Dtype:         dtype,
				TensorContent: data,
			},
		},
		Metadata: &tbproto.SummaryMetadata{
			PluginData: &tbproto.SummaryMetadata_PluginData{
				PluginName: plugin,
			},
		},
	}
}

func summaryEvent(
	step int64,
	wallTime float64,
	values ...*tbproto.Summary_Value,
) *tbproto.TFEvent {
	return &tbproto.TFEvent{
		Step:     step,
		WallTime: wallTime,
		What: &tbproto.TFEvent_Summary{
			Summary: &tbproto.Summary{
				Value: values,
			},
		},
	}
}

// mockEmitter is a mock of the Emitter interface.
type mockEmitter struct {
	SetTFStepCalls     []mockEmitter_SetTFStep
	SetTFWallTimeCalls []float64
	EmitHistoryCalls   []mockEmitter_EmitHistory
	EmitChartCalls     []mockEmitter_EmitChart
	EmitTableCalls     []mockEmitter_EmitTable
	EmitImageCalls     []mockEmitter_EmitImage
}

type mockEmitter_SetTFStep struct {
	Key  pathtree.TreePath
	Step int64
}

type mockEmitter_EmitHistory struct {
	Key       pathtree.TreePath
	ValueJSON string
}

type mockEmitter_EmitChart struct {
	Key   string
	Chart wbvalue.Chart
}

type mockEmitter_EmitTable struct {
	Key   pathtree.TreePath
	Table wbvalue.Table
}

type mockEmitter_EmitImage struct {
	Key   pathtree.TreePath
	Image wbvalue.Image
}

func (e *mockEmitter) SetTFStep(key pathtree.TreePath, step int64) {
	e.SetTFStepCalls = append(e.SetTFStepCalls,
		mockEmitter_SetTFStep{key, step})
}

func (e *mockEmitter) SetTFWallTime(wallTime float64) {
	e.SetTFWallTimeCalls = append(e.SetTFWallTimeCalls, wallTime)
}

func (e *mockEmitter) EmitHistory(key pathtree.TreePath, valueJSON string) {
	e.EmitHistoryCalls = append(e.EmitHistoryCalls,
		mockEmitter_EmitHistory{key, valueJSON})
}

func (e *mockEmitter) EmitChart(key string, chart wbvalue.Chart) error {
	e.EmitChartCalls = append(e.EmitChartCalls,
		mockEmitter_EmitChart{key, chart})
	return nil
}

func (e *mockEmitter) EmitTable(key pathtree.TreePath, table wbvalue.Table) error {
	e.EmitTableCalls = append(e.EmitTableCalls,
		mockEmitter_EmitTable{key, table})
	return nil
}

func (e *mockEmitter) EmitImage(key pathtree.TreePath, img wbvalue.Image) error {
	e.EmitImageCalls = append(e.EmitImageCalls,
		mockEmitter_EmitImage{key, img})
	return nil
}

func TestConvertStepAndTimestamp(t *testing.T) {
	converter := tensorboard.TFEventConverter{
		Namespace: "train",
	}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(
			123, 0.345,
			scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_SetTFStep{
			{pathtree.PathOf("train/global_step"), 123},
		},
		emitter.SetTFStepCalls)
	assert.Equal(t,
		[]float64{0.345},
		emitter.SetTFWallTimeCalls)
}

func TestConvertScalar(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	doubleTenPointFiveBytes := bytes.NewBuffer([]byte{})
	require.NoError(t,
		binary.Write(doubleTenPointFiveBytes, binary.NativeEndian, 10.5))

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValue("epoch_loss", "scalars", []int{0}, 2.5)),
		observability.NewNoOpLogger(),
	)
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueBytes(
				"epoch_loss",
				"scalars",
				tbproto.DataType_DT_DOUBLE,
				doubleTenPointFiveBytes.Bytes())),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitHistory{
			{pathtree.PathOf("train/epoch_loss"), "0.5"},
			{pathtree.PathOf("train/epoch_loss"), "2.5"},
			{pathtree.PathOf("train/epoch_loss"), "10.5"},
		},
		emitter.EmitHistoryCalls)
}

func TestConvertHistogram(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	expectedHistogramJSON, err := wbvalue.Histogram{
		BinEdges:   []float64{0.0, 0.5, 1.0, 1.5, 2.0, 2.5},
		BinWeights: []float64{7, 5, 10, 11, 4},
	}.HistoryValueJSON()
	require.NoError(t, err)

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValue("my_hist", "histograms",
				[]int{5, 3},
				// left edge, right edge, count
				0.0, 0.5, 7,
				0.5, 1.0, 5,
				1.0, 1.5, 10,
				1.5, 2.0, 11,
				2.0, 2.5, 4)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitHistory{
			{
				Key:       pathtree.PathOf("train/my_hist"),
				ValueJSON: expectedHistogramJSON,
			},
		},
		emitter.EmitHistoryCalls)
}

func TestConvertHistogramRebin(t *testing.T) {
	// A histogram of 100 bins should be rebinned to 32 bins.
	// Sum of weights should remain the same.
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	inputTensor := make([]float32, 100*3)
	for i := 0; i < 100; i++ {
		// Left edge, right edge, weight.
		inputTensor[i*3+0] = float32(i)
		inputTensor[i*3+1] = float32(i + 1)
		inputTensor[i*3+2] = 1
	}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValue("my_hist", "histograms",
				[]int{100, 3}, inputTensor...)),
		observability.NewNoOpLogger(),
	)

	var result map[string]any
	require.NoError(t,
		json.Unmarshal(
			[]byte(emitter.EmitHistoryCalls[0].ValueJSON),
			&result))
	assert.Len(t, result["bins"], 33)
	assert.Len(t, result["values"], 32)
	sumOfWeights := float64(0)
	for _, x := range result["values"].([]any) {
		sumOfWeights += x.(float64)
	}
	assert.EqualValues(t, 100, sumOfWeights)
}

func TestConvertImage(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("my_img", "images",
				"2", "4", "\x89PNG\x0D\x0A\x1A\x0Acontent")),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitImage{
			{
				Key: pathtree.PathOf("train/my_img"),
				Image: wbvalue.Image{
					Width:  2,
					Height: 4,
					PNG:    []byte("\x89PNG\x0D\x0A\x1A\x0Acontent"),
				},
			},
		},
		emitter.EmitImageCalls)
}

func TestConvertImage_NotPNG(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	var logs bytes.Buffer

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("my_img", "images",
				"2", "4", "not a PNG")),
		observability.NewCoreLogger(slog.New(slog.NewTextHandler(&logs, nil))),
	)

	assert.Empty(t, emitter.EmitImageCalls)
	assert.Contains(t, logs.String(), "image is not PNG-encoded")
}

func TestConvertImage_BadDims(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	var logs bytes.Buffer

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("my_img", "images",
				"2a", "4x", "\x89PNG\x0D\x0A\x1A\x0Acontent")),
		observability.NewCoreLogger(slog.New(slog.NewTextHandler(&logs, nil))),
	)

	assert.Empty(t, emitter.EmitImageCalls)
	assert.Contains(t, logs.String(), "couldn't parse image dimensions")
	assert.Contains(t, logs.String(), "2a")
	assert.Contains(t, logs.String(), "4x")
}

func TestConvertImage_UnknownTBFormat(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	var logs bytes.Buffer

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("my_img", "images", "not enough strings")),
		observability.NewCoreLogger(slog.New(slog.NewTextHandler(&logs, nil))),
	)

	assert.Empty(t, emitter.EmitImageCalls)
	assert.Contains(t, logs.String(),
		"expected images tensor string_val to have 3 values, but it has 1")
}

func TestConvertPRCurve(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValue("pr", "pr_curves",
				[]int{2, 3},
				1, 2, 3, // precision
				4, 5, 6)), // recall
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitTable{
			{
				pathtree.PathOf("train/pr"),
				wbvalue.Table{
					ColumnLabels: []string{"recall", "precision"},
					Rows: [][]any{
						{float64(4), float64(1)},
						{float64(5), float64(2)},
						{float64(6), float64(3)},
					},
				},
			},
		},
		emitter.EmitTableCalls)
	assert.Equal(t,
		[]mockEmitter_EmitChart{
			{
				"train/pr",
				wbvalue.Chart{
					Title:    "train/pr Precision v. Recall",
					X:        "recall",
					Y:        "precision",
					TableKey: "train/pr",
				},
			},
		},
		emitter.EmitChartCalls)
}
