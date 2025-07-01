package tensorboard

import (
	"errors"
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
)

// processImages processes data logged with `tf.summary.image()`.
func processImages(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	switch x := value.GetValue().(type) {
	case *tbproto.Summary_Value_Tensor:
		processImagesTensor(emitter, tag, x.Tensor, logger)

	case *tbproto.Summary_Value_Image:
		processImagesProto(emitter, tag, x.Image, logger)

	default:
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected images summary to use 'image'"+
					" or 'tensor' field but its type is %T",
				value.GetValue()))
	}
}

// processImagesTensor processes a summary with an image in the 'tensor' field.
func processImagesTensor(
	emitter Emitter,
	tag string,
	tensorValue *tbproto.TensorProto,
	logger *observability.CoreLogger,
) {
	if len(tensorValue.StringVal) < 3 {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected images tensor string_val"+
					" to have at least 3 values, but it has %d",
				len(tensorValue.StringVal)))
		return
	}

	// Format: https://github.com/tensorflow/tensorboard/blob/b56c65521cbccf3097414cbd7e30e55902e08cab/tensorboard/plugins/image/summary.py#L17-L18
	width, err1 := strconv.Atoi(string(tensorValue.StringVal[0]))
	height, err2 := strconv.Atoi(string(tensorValue.StringVal[1]))
	if err1 != nil || err2 != nil {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: couldn't parse image dimensions: %v",
				errors.Join(err1, err2)))
		return
	}

	// The remaining values are encoded images.
	images := tensorValue.StringVal[2:]
	emitImages(width, height, images, emitter, tag, logger)
}

// processImagesProto processes a summary with the 'image' field.
func processImagesProto(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Image,
	logger *observability.CoreLogger,
) {
	emitImages(
		int(value.Width),
		int(value.Height),
		[][]byte{value.EncodedImageString},
		emitter,
		tag,
		logger,
	)
}

func emitImages(
	width int,
	height int,
	images [][]byte,
	emitter Emitter,
	tag string,
	logger *observability.CoreLogger,
) {
	wbImages := []wbvalue.Image{}

	for _, encodedData := range images {
		image, err := wbvalue.ImageFromData(width, height, encodedData)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: failed to read image: %v", err))
		} else {
			wbImages = append(wbImages, image)
		}
	}

	if len(wbImages) != 0 {
		err := emitter.EmitImages(pathtree.PathOf(tag), wbImages)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: couldn't emit image: %v", err))
		}
	}
}
