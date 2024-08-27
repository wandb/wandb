package tensorboard

import (
	"errors"
	"fmt"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
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

// ConvertNext adds data from a TF event to the run.
//
// This should be called on events in the order they are read from
// tfevents files.
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

		case "histograms":
			processHistograms(emitter, tag, value, logger)

		case "images":
			processImages(emitter, tag, value, logger)

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
