package tensorboard

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"

	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
)

// Tensor is a multi-dimensional array of real numbers.
type Tensor struct {
	rowMajorData []float64

	// Shape is the size of each dimension of the tensor.
	//
	// If the shape has no elements, the tensor is rank-0 and has exactly one
	// element.
	Shape []int
}

// Row returns a view of a row of the tensor if it is rank-2.
//
// If the index is negative, it is an offset from the total number of rows.
//
// It is an error if the tensor is not rank-2, or if the index is
// out of bounds.
func (t *Tensor) Row(i int) ([]float64, error) {
	if rank := len(t.Shape); rank != 2 {
		return nil, fmt.Errorf("expected rank-2 tensor, but rank is %d", rank)
	}

	if i < 0 {
		i += t.Shape[0]
	}

	rowLen := t.Shape[1]
	start := i * rowLen
	end := (i + 1) * rowLen

	if start < 0 || start >= len(t.rowMajorData) ||
		end < start || end > len(t.rowMajorData) {
		return nil, fmt.Errorf("row index out of bounds: %d", i)
	}

	return t.rowMajorData[start:end], nil
}

// Col returns a column of the tensor if it is rank-2.
//
// This is like Row, but it allocates a new slice since tensors are stored
// in row-major order.
func (t *Tensor) Col(i int) ([]float64, error) {
	if rank := len(t.Shape); rank != 2 {
		return nil, fmt.Errorf("expected rank-2 tensor, but rank is %d", rank)
	}

	if i < 0 {
		i += t.Shape[1]
	}

	// Ensure slice accesses below cannot panic.
	if i < 0 || t.Shape[1]*(t.Shape[0]-1)+i >= len(t.rowMajorData) {
		return nil, fmt.Errorf("col index out of bounds: %d", i)
	}

	column := make([]float64, t.Shape[0])
	for rowIdx := 0; rowIdx < t.Shape[0]; rowIdx++ {
		column[rowIdx] = t.rowMajorData[rowIdx*t.Shape[1]+i]
	}

	return column, nil
}

// Scalar returns the single numeric value stored in the tensor.
//
// Returns an error if the tensor does not have exactly one value.
func (t *Tensor) Scalar() (float64, error) {
	if len(t.rowMajorData) != 1 {
		return 0, fmt.Errorf(
			"tensor has %d elements, not 1",
			len(t.rowMajorData))
	}

	return t.rowMajorData[0], nil
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
	dims := make([]int, len(proto.TensorShape.GetDim()))
	for i, dim := range proto.TensorShape.GetDim() {
		dims[i] = int(dim.Size)

		if dim.Size == -1 {
			return nil, errors.New("tensor has unknown shape")
		}
	}

	if len(proto.TensorContent) == 0 {
		return &Tensor{
			rowMajorData: toFloat64Slice(directField),
			Shape:        dims,
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

	return &Tensor{
		rowMajorData: toFloat64Slice(rawData),
		Shape:        dims,
	}, nil
}

func toFloat64Slice[T numeric](data []T) []float64 {
	result := make([]float64, len(data))
	for i, x := range data {
		result[i] = float64(x)
	}
	return result
}
