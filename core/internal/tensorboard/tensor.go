package tensorboard

import (
	"bytes"
	"encoding/binary"
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
)

// Tensor is a multi-dimensional array of real numbers.
type Tensor struct {
	rowMajorData []float64
}

// ToHistogramJSON returns a W&B histogram of the numbers in the tensor.
func (t *Tensor) ToHistogramJSON(nbins int) (string, error) {
	switch {
	case len(t.rowMajorData) == 1:
		return fmt.Sprintf("%v", t.rowMajorData[0]), nil
	case len(t.rowMajorData) <= nbins:
		// simplejsonext allows NaN and +-Infinity which we must support.
		result, err := simplejsonext.Marshal(t.rowMajorData)

		// Impossible: we should always be able to marshal a slice of numbers.
		if err != nil {
			return "", err
		}

		return string(result), nil
	default:
		// TODO: implement numbersToHistogramJSON for >nbins entries
		return "", fmt.Errorf("numbersToHistogramJSON for >nbins entries unimplemented")
	}
}

// tensorFromProto converts a TensorProto into a Tensor.
func tensorFromProto(proto *tbproto.TensorProto) (*Tensor, error) {
	switch proto.Dtype {
	case tbproto.DataType_DT_FLOAT:
		return tensorFieldToTensor(proto, proto.FloatVal, 4)

	case tbproto.DataType_DT_DOUBLE:
		return tensorFieldToTensor(proto, proto.DoubleVal, 8)

	case tbproto.DataType_DT_INT32:
		// TODO: Handle DT_INT16, DT_UINT16, DT_INT8, DT_UINT8
		return tensorFieldToTensor(proto, proto.IntVal, 4)

	case tbproto.DataType_DT_INT64:
		return tensorFieldToTensor(proto, proto.Int64Val, 8)
	}

	return nil, fmt.Errorf("unsupported tensor dtype: %v", proto.Dtype)
}

type numeric interface {
	float32 | float64 |
		int32 | int64
}

// tensorFieldToTensor creates a Tensor from either the `tensor_content`
// field of a tensor proto or a type-specific field.
//
// `directField` is the value of the type-specific field on the proto.
// `byteCount` is the number of bytes per value of T in `tensor_content`.
func tensorFieldToTensor[T numeric](
	proto *tbproto.TensorProto,
	directField []T,
	byteCount int,
) (*Tensor, error) {
	if len(proto.TensorContent) == 0 {
		return &Tensor{
			rowMajorData: toFloat64Slice(directField),
		}, nil
	}

	if len(proto.TensorContent)%byteCount != 0 {
		return nil, fmt.Errorf(
			"tensor content has %d bytes, which is not a multiple of %d",
			len(proto.TensorContent),
			byteCount)
	}

	rawData := make([]T, len(proto.TensorContent)/byteCount)

	// This might be a bug in TensorBoard, but its Python implementation
	// reads data using the NumPy `frombuffer` function and a dtype
	// without an explicit byte order, so the tensor content is
	// interpreted with the native byte order.
	//
	// It's not clear what byte order is used to serialize tensors in C
	// and C++, but it's possible it's the native byte order.
	//
	// tesnor_content conversion: https://github.com/tensorflow/tensorboard/blob/ae7d0b9250f5986dd0f0c238fcaf3c8d7f4312ca/tensorboard/util/tensor_util.py#L513-L523
	if err := binary.Read(
		bytes.NewBuffer(proto.TensorContent),
		binary.NativeEndian,
		&rawData,
	); err != nil {
		return nil, err
	}

	return &Tensor{rowMajorData: toFloat64Slice(rawData)}, nil
}

func toFloat64Slice[T numeric](data []T) []float64 {
	result := make([]float64, len(data))
	for i, x := range data {
		result[i] = float64(x)
	}
	return result
}
