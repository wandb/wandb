package tensorboard

import (
	"errors"
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/internal/wbvalue"
	"github.com/wandb/wandb/core/pkg/observability"
)

// TFEventConverter converts TF events into W&B requests.
type TFEventConverter struct {
	// Namespace is a prefix to add to all events.
	Namespace string

	// pluginNameByTag tracks the plugin name for each summary value tag.
	//
	// tfevents files may only contain a `metadata` field on the first
	// occurrence of each tag to save space.
	//
	// See also the comment on the `metadata` field of the `Summary` proto.
	pluginNameByTag map[string]string
}

// ConvertNext returns zero or more W&B requests corresponding to a TF event.
//
// This should be called on events in the order they are read from
// tfevents files.
//
// Returns an empty slice if there's no relevant history data in the event.
// Errors are logged via the logger and the corresponding data is ignored.
func (h *TFEventConverter) ConvertNext(
	emitter Emitter,
	event *tbproto.TFEvent,
	logger *observability.CoreLogger,
) {
	stepKey, err := h.withNamespace("global_step")
	if err != nil {
		logger.CaptureError(fmt.Errorf("tensorboard: global_step: %v", err))
	} else {
		emitter.SetTFStep(pathtree.PathOf(stepKey), event.Step)
		emitter.SetTFWallTime(event.WallTime)
	}

	for _, value := range event.GetSummary().GetValue() {
		tag, err := h.withNamespace(value.GetTag())
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: invalid tag: %v", err))
			continue
		}

		switch h.rememberPluginName(tag, value) {
		case "scalars":
			processScalars(emitter, tag, value, logger)

		case "pr_curves":
			processPRCurves(emitter, tag, value, logger)
		}
	}
}

// rememberPluginName returns the plugin name associated to the value.
//
// This returns the name stored in the value, or else the name stored most
// recently for the tag.
func (h *TFEventConverter) rememberPluginName(
	namespacedTag string,
	value *tbproto.Summary_Value,
) string {
	if h.pluginNameByTag == nil {
		h.pluginNameByTag = make(map[string]string)
	}

	if name := value.GetMetadata().GetPluginData().GetPluginName(); name != "" {
		h.pluginNameByTag[namespacedTag] = name
		return name
	}

	return h.pluginNameByTag[namespacedTag]
}

// processScalars processes data logged with `tf.summary.scalar()`.
func processScalars(
	emitter Emitter,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) {
	switch value := value.GetValue().(type) {
	case *tbproto.Summary_Value_SimpleValue:
		emitter.EmitHistory(
			pathtree.PathOf(tag),
			fmt.Sprintf("%v", value.SimpleValue))

	case *tbproto.Summary_Value_Tensor:
		tensor, err := tensorFromProto(value.Tensor)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error parsing tensor: %v", err))
			return
		}

		str, err := tensor.ToHistogramJSON(32)
		if err != nil {
			logger.CaptureError(
				fmt.Errorf("tensorboard: error serializing tensor: %v", err))
			return
		}

		emitter.EmitHistory(pathtree.PathOf(tag), str)

	default:
		logger.CaptureError(
			fmt.Errorf(
				"tensorboard: unexpected scalars value type: %T",
				value))
	}
}

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

// withNamespace prefixes the key with the namespace, if there is one.
func (h *TFEventConverter) withNamespace(key string) (string, error) {
	if len(key) == 0 {
		return "", errors.New("empty key")
	}

	if h.Namespace == "" {
		return key, nil
	} else {
		return fmt.Sprintf("%s/%s", h.Namespace, key), nil
	}
}
