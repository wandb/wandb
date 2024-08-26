package tensorboard

import (
	"errors"
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
	"github.com/wandb/wandb/core/pkg/observability"
)

// processPRCurves processes data from the "pr_curves" TensorBoard plugin.
//
// In TensorFlow 2, PR curves can be added to the summary like so:
//
//	import tensorboard.summary.v1 as tb_summary
//	import tensorflow as tf
//	tf.summary.experimental.write_raw_pb(
//	  tb_summary.pr_curve(
//		  "pr",
//		  labels=...,
//		  predictions=...,
//		  num_thresholds=...,
//	  ),
//	  step=...,
//	)
//
// https://github.com/tensorflow/tensorboard/issues/2902#issuecomment-551301396
func processPRCurves(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	tensorValue, ok := value.GetValue().(*tbproto.Summary_Value_Tensor)
	if !ok {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: expected pr_curves value to be a Tensor"+
					" but its type is %T",
				value.GetValue()))
		return
	}

	tensor, err := tensorFromProto(tensorValue.Tensor)
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: failed to parse tensor: %v", err))
		return
	}

	precision, err1 := tensor.Row(-2)
	recall, err2 := tensor.Row(-1)
	if err1 != nil || err2 != nil {
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: couldn't read pr_curves row: %v",
				errors.Join(err1, err2)))
		return
	}

	if len(precision) != len(recall) {
		// Shouldn't happen since it's a 2D array.
		logger.CaptureError(
			errors.New("tensorboard: len(precision) != len(recall)"))
		return
	}

	table := wbvalue.Table{
		ColumnLabels: []string{"recall", "precision"},
	}

	for i := 0; i < len(precision); i++ {
		table.Rows = append(table.Rows,
			[]any{recall[i], precision[i]})
	}

	err = emitter.EmitTable(pathtree.PathOf(tag), table)
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: failed to emit pr_curves table: %v", err))
	}

	err = emitter.EmitChart(
		tag,
		wbvalue.Chart{
			Title:    fmt.Sprintf("%s Precision v. Recall", tag),
			X:        "recall",
			Y:        "precision",
			TableKey: tag,
		})
	if err != nil {
		logger.CaptureError(
			fmt.Errorf("tensorboard: failed to emit pr_curves chart: %v", err))
	}
}
