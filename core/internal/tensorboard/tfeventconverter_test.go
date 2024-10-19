package tensorboard_test

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"log/slog"
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
)

const testPNG2x4 = "" +
	// PNG header
	"\x89PNG\x0D\x0A\x1A\x0A" +
	// Required IHDR chunk
	"\x00\x00\x00\x0DIHDR" + // chunk length, "IHDR" magic
	"\x00\x00\x00\x02" + // image width
	"\x00\x00\x00\x04" + // image height
	"\x01\x00\x00\x00\x00" + // buncha other stuff
	"\x8C\x94\xD3\x94" // CRC-32 of "IHDR" and the chunk data

const testGif1x1 = "" +
	// GIF header
	"GIF89a" +
	// Gif size (1x1)
	"\x01\x00\x01\x00" +
	// random Gif data
	"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

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

func tensorValueImage(
	tag string,
	plugin string,
	width int,
	height int,
	encodedImageData string,
) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Image{
			Image: &tbproto.Summary_Image{
				Height:             int32(height),
				Width:              int32(width),
				EncodedImageString: []byte(encodedImageData),
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
	EmitImagesCalls    []mockEmitter_EmitImages
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

type mockEmitter_EmitImages struct {
	Key    pathtree.TreePath
	Images []wbvalue.Image
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

func (e *mockEmitter) EmitImages(key pathtree.TreePath, images []wbvalue.Image) error {
	e.EmitImagesCalls = append(e.EmitImagesCalls,
		mockEmitter_EmitImages{key, images})
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
			scalarValue("epoch_loss", "scalars", float32(math.Inf(1)))),
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
			{pathtree.PathOf("train/epoch_loss"), "Infinity"},
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

func TestConvertHistogramProto(t *testing.T) {
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
			&tbproto.Summary_Value{
				Tag: "my_hist",
				Value: &tbproto.Summary_Value_Histo{
					Histo: &tbproto.HistogramProto{
						Min:         0,
						BucketLimit: []float64{0.5, 1.0, 1.5, 2.0, 2.5},
						Bucket:      []float64{7, 5, 10, 11, 4},
					},
				},
			}),
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
	// A histogram of 1000 bins should be rebinned to 512 bins.
	// Sum of weights should remain the same.
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	inputTensor := make([]float32, 1000*3)
	for i := 0; i < 1000; i++ {
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
				[]int{1000, 3}, inputTensor...)),
		observability.NewNoOpLogger(),
	)

	var result map[string]any
	require.NoError(t,
		json.Unmarshal(
			[]byte(emitter.EmitHistoryCalls[0].ValueJSON),
			&result))
	assert.Len(t, result["bins"], 513)
	assert.Len(t, result["values"], 512)
	sumOfWeights := float64(0)
	for _, x := range result["values"].([]any) {
		sumOfWeights += x.(float64)
	}
	assert.EqualValues(t, 1000, sumOfWeights)
}

func TestConvertImageNoPluginName(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueImage("my_img", "",
				2, 4, testPNG2x4)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitImages{
			{
				Key: pathtree.PathOf("train/my_img"),
				Images: []wbvalue.Image{{
					Width:       2,
					Height:      4,
					EncodedData: []byte(testPNG2x4),
					Format:      "png",
				}},
			},
		},
		emitter.EmitImagesCalls)
}

func TestConvertImage(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("my_img", "images",
				"2", "4", testPNG2x4)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitImages{
			{
				Key: pathtree.PathOf("train/my_img"),
				Images: []wbvalue.Image{{
					Width:       2,
					Height:      4,
					EncodedData: []byte(testPNG2x4),
					Format:      "png",
				}},
			},
		},
		emitter.EmitImagesCalls)
}

func TestConvertBatchImages(t *testing.T) {
	image := wbvalue.Image{
		Width:       2,
		Height:      4,
		EncodedData: []byte(testPNG2x4),
		Format:      "png",
	}

	converter := tensorboard.TFEventConverter{Namespace: "train"}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("my_img", "images",
				"2", "4", testPNG2x4, testPNG2x4)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitImages{
			{
				Key: pathtree.PathOf("train/my_img"),
				Images: []wbvalue.Image{
					image,
					image,
				},
			},
		},
		emitter.EmitImagesCalls)
}

func TestConvertGif(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValueStrings("test_gif", "images",
				"1", "1", testGif1x1)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitImages{
			{
				Key: pathtree.PathOf("train/test_gif"),
				Images: []wbvalue.Image{{
					Width:       1,
					Height:      1,
					EncodedData: []byte(testGif1x1),
					Format:      "gif",
				}},
			},
		},
		emitter.EmitImagesCalls)
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

	assert.Empty(t, emitter.EmitImagesCalls)
	assert.Contains(t, logs.String(), "failed to parse image format")
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

	assert.Empty(t, emitter.EmitImagesCalls)
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

	assert.Empty(t, emitter.EmitImagesCalls)
	assert.Contains(t, logs.String(),
		"expected images tensor string_val to have at least 3 values, but it has 1")
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
