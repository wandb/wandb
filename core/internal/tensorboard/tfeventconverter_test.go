package tensorboard_test

import (
	"bytes"
	"encoding/binary"
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

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345, scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitHistory{
			{pathtree.PathOf("train/epoch_loss"), "0.5"},
		},
		emitter.EmitHistoryCalls)
}

func TestConvertTensor(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	doubleOneTwoBytes := bytes.NewBuffer([]byte{})
	require.NoError(t,
		binary.Write(doubleOneTwoBytes, binary.NativeEndian, float64(1)))
	require.NoError(t,
		binary.Write(doubleOneTwoBytes, binary.NativeEndian, float64(2)))

	emitter := &mockEmitter{}
	converter.ConvertNext(
		emitter,
		summaryEvent(123, 0.345,
			tensorValue("point-five", "scalars", nil, 0.5),
			tensorValueBytes("one-two", "scalars",
				tbproto.DataType_DT_DOUBLE, doubleOneTwoBytes.Bytes()),
			tensorValue("three-four", "scalars", nil, 3, 4)),
		observability.NewNoOpLogger(),
	)

	assert.Equal(t,
		[]mockEmitter_EmitHistory{
			{pathtree.PathOf("train/point-five"), "0.5"},
			{pathtree.PathOf("train/one-two"), "[1,2]"},
			{pathtree.PathOf("train/three-four"), "[3,4]"},
		},
		emitter.EmitHistoryCalls)
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
