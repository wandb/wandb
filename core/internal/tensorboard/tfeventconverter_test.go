package tensorboard_test

import (
	"bytes"
	"encoding/binary"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
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

func tensorValue(tag string, plugin string, values ...float32) *tbproto.Summary_Value {
	return &tbproto.Summary_Value{
		Tag: tag,
		Value: &tbproto.Summary_Value_Tensor{
			Tensor: &tbproto.TensorProto{
				Dtype:    tbproto.DataType_DT_FLOAT,
				FloatVal: values,
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

func assertProtoEqual(t *testing.T, expected proto.Message, actual proto.Message) {
	assert.True(t,
		proto.Equal(expected, actual),
		"Value is\n\t%v\nbut expected\n\t%v", actual, expected)
}

func TestConvertStepAndTimestamp(t *testing.T) {
	converter := tensorboard.TFEventConverter{
		Namespace: "train",
	}

	result := converter.ConvertNext(
		summaryEvent(
			123, 0.345,
			scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 3)
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "global_step"},
			ValueJson: "123",
		},
		result.Item[0])
	assertProtoEqual(t,
		&spb.HistoryItem{Key: "_timestamp", ValueJson: "0.345"},
		result.Item[1])
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "epoch_loss"},
			ValueJson: "0.5",
		},
		result.Item[2])
}

func TestConvertScalar(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}

	result := converter.ConvertNext(
		summaryEvent(123, 0.345, scalarValue("epoch_loss", "scalars", 0.5)),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 3)
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "epoch_loss"},
			ValueJson: "0.5",
		},
		result.Item[2])
}

func TestConvertTensor(t *testing.T) {
	converter := tensorboard.TFEventConverter{Namespace: "train"}
	doubleOneTwoBytes := bytes.NewBuffer([]byte{})
	require.NoError(t,
		binary.Write(doubleOneTwoBytes, binary.NativeEndian, float64(1)))
	require.NoError(t,
		binary.Write(doubleOneTwoBytes, binary.NativeEndian, float64(2)))

	result := converter.ConvertNext(
		summaryEvent(123, 0.345,
			tensorValue("point-five", "scalars", 0.5),
			tensorValueBytes("one-two", "scalars",
				tbproto.DataType_DT_DOUBLE, doubleOneTwoBytes.Bytes()),
			tensorValue("three-four", "scalars", 3, 4)),
		observability.NewNoOpLogger(),
	)

	require.NotNil(t, result)
	require.Len(t, result.Item, 5)
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "point-five"},
			ValueJson: "0.5",
		},
		result.Item[2])
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "point-five"},
			ValueJson: "0.5",
		},
		result.Item[2])
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "one-two"},
			ValueJson: "[1,2]",
		},
		result.Item[3])
	assertProtoEqual(t,
		&spb.HistoryItem{
			NestedKey: []string{"train", "three-four"},
			ValueJson: "[3,4]",
		},
		result.Item[4])
}
