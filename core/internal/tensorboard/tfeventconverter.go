package tensorboard

import (
	"fmt"
	"strings"

	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// TFEventConverter converts TF events into W&B history records.
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

// tagAndJSON is a tag and a JSON representation of a value.
type tagAndJSON struct {
	tag  string
	json string
}

// Convert returns a W&B history record corresponding to a TF event.
//
// Returns nil if there's no relevant history data in the event.
// Errors are logged via the logger and the corresponding data is ignored.
func (h *TFEventConverter) Convert(
	event *tbproto.TFEvent,
	logger *observability.CoreLogger,
) *service.HistoryRecord {
	// Maps slash-separated tags to JSON values.
	jsonData := make([]tagAndJSON, 0, len(event.GetSummary().GetValue()))

	for _, value := range event.GetSummary().GetValue() {
		tag := h.withNamespace(value.GetTag())

		if h.rememberPluginName(tag, value) == "scalars" {
			jsonData = processScalars(jsonData, tag, value, logger)
		}
	}

	if len(jsonData) == 0 {
		return nil
	}

	return h.toHistoryRecord(
		jsonData,
		event.Step,
		event.WallTime,
	)
}

// rememberPluginName returns the plugin name associated to the value.
//
// This returns the name stored in the value, or else the name stored most
// recently for the tag.
func (h *TFEventConverter) rememberPluginName(tag string, value *tbproto.Summary_Value) string {
	if h.pluginNameByTag == nil {
		h.pluginNameByTag = make(map[string]string)
	}

	if name := value.GetMetadata().GetPluginData().GetPluginName(); name != "" {
		h.pluginNameByTag[tag] = name
		return name
	}

	return h.pluginNameByTag[tag]
}

// processScalars processes a value associated to the "scalars" plugin.
//
// Takes ownership of the jsonData slice and returns the amended slice.
func processScalars(
	jsonData []tagAndJSON,
	tag string,
	value *tbproto.Summary_Value,
	logger *observability.CoreLogger,
) []tagAndJSON {
	switch value := value.GetValue().(type) {
	case *tbproto.Summary_Value_SimpleValue:
		return append(jsonData,
			tagAndJSON{
				tag:  tag,
				json: fmt.Sprintf("%v", value.SimpleValue),
			})

	case *tbproto.Summary_Value_Tensor:
		str, err := toHistogramJSON(value.Tensor)

		if err != nil {
			logger.CaptureError("tensorboard: error serializing a tensor", err)
			return jsonData
		} else {
			return append(jsonData, tagAndJSON{tag: tag, json: str})
		}

	default:
		return jsonData
	}
}

// toHistoryRecord creates a history record with the given data.
func (h *TFEventConverter) toHistoryRecord(
	jsonData []tagAndJSON,
	step int64,
	timestamp float64,
) *service.HistoryRecord {
	items := []*service.HistoryItem{
		// The "global_step" key is magic that W&B automatically uses
		// as the X axis in charts.
		{
			NestedKey: strings.Split(h.withNamespace("global_step"), "/"),
			ValueJson: fmt.Sprintf("%v", step),
		},
		{Key: "_timestamp", ValueJson: fmt.Sprintf("%v", timestamp)},
	}

	for _, tagAndJSON := range jsonData {
		items = append(items, &service.HistoryItem{
			NestedKey: strings.Split(tagAndJSON.tag, "/"),
			ValueJson: tagAndJSON.json,
		})
	}

	return &service.HistoryRecord{Item: items}
}

// withNamespace prefixes the key with the namespace, if there is one.
func (h *TFEventConverter) withNamespace(key string) string {
	if h.Namespace == "" {
		return key
	} else {
		return fmt.Sprintf("%s/%s", h.Namespace, key)
	}
}
