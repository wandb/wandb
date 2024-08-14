package tensorboard

import (
	"bytes"
	"encoding/binary"
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
)

// toHistogramJSON returns a JSON string that summarizes the contents of
// a tensor for logging to a run.
func toHistogramJSON(proto *tbproto.TensorProto) (string, error) {
	switch proto.Dtype {
	case tbproto.DataType_DT_FLOAT:
		return tensorFieldToHistogramJSON(proto, proto.FloatVal, 4)

	case tbproto.DataType_DT_DOUBLE:
		return tensorFieldToHistogramJSON(proto, proto.DoubleVal, 8)

	case tbproto.DataType_DT_INT32:
		// TODO: Handle DT_INT16, DT_UINT16, DT_INT8, DT_UINT8
		return tensorFieldToHistogramJSON(proto, proto.IntVal, 4)

	case tbproto.DataType_DT_INT64:
		return tensorFieldToHistogramJSON(proto, proto.Int64Val, 8)
	}

	return "", fmt.Errorf("unsupported tensor dtype: %v", proto.Dtype)
}

type numeric interface {
	float32 | float64 |
		int32 | int64
}

// tensorFieldToHistgramJSON processes either the `tensor_content` field of
// a tensor proto or a type-specific field.
//
// `directField` is the value of the type-specific field on the proto.
// `byteCount` is the number of bytes per value of T in `tensor_content`.
func tensorFieldToHistogramJSON[T numeric](
	proto *tbproto.TensorProto,
	directField []T,
	byteCount int,
) (string, error) {
	if len(proto.TensorContent) > 0 {
		if len(proto.TensorContent)%byteCount != 0 {
			return "", fmt.Errorf(
				"tensor content has %d bytes, which is not a multiple of %d",
				len(proto.TensorContent),
				byteCount)
		}

		data := make([]T, len(proto.TensorContent)/byteCount)

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
			&data,
		); err != nil {
			return "", err
		}

		return numbersToHistogramJSON(data)
	} else {
		return numbersToHistogramJSON(directField)
	}
}

func numbersToHistogramJSON[T numeric](data []T) (string, error) {
	if data == nil {
		return "null", nil
	}

	switch {
	case len(data) == 1:
		return fmt.Sprintf("%v", data[0]), nil
	case len(data) <= 32:
		// simplejsonext encodes +-Infinity and NaN, which we must support.
		result, err := simplejsonext.Marshal(data)

		// Impossible: we should always be able to marshal a slice of numbers.
		if err != nil {
			return "", err
		}

		return string(result), nil
	default:
		// TODO: implement numbersToHistogramJSON for >32 entries
		return "", fmt.Errorf("numbersToHistogramJSON for >32 entries unimplemented")
	}
}
