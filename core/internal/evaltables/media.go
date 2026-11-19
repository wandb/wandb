package evaltables

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strings"

	ces "github.com/wandb/cwevals-go"

	"github.com/wandb/wandb/core/internal/runbranch"
)

// mediaSchemaVersion is the schema version of the CES extension values
// that mediaConverter produces.
const mediaSchemaVersion = 1

// maxMediaValueBytes is the size of compact JSON at which a media cell's
// CES extension value is too large.
//
// It matches CES's limit on image list values, and the 3.5 MB ClickHouse
// single-row insert limit that Weave adopted after larger rows failed in
// production (wandb/weave#2353, wandb/weave#5448). It bounds each value,
// not the row.
const maxMediaValueBytes = 3_500_000

const (
	imageMediaType = "image-file"
	audioMediaType = "audio-file"
	videoMediaType = "video-file"
)

// mediaExtensionTypes maps the W&B media types that EvalTables support to
// the CES extension types of their values.
var mediaExtensionTypes = map[string]ces.EvalTableColumnNewParamsDatasetFieldsExtensionType{
	imageMediaType: ces.EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbImage,
	audioMediaType: ces.EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbAudio,
	videoMediaType: ces.EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbVideo,
}

// mediaConverter converts W&B media JSON to CES extension values.
type mediaConverter struct {
	runPath runbranch.RunPath
}

// wandbMedia is the W&B media JSON of a value, as produced by its Python
// class's `to_json`.
type wandbMedia struct {
	wandbMediaFile
	Format  string                    `json:"format"`
	Caption *string                   `json:"caption"`
	Width   *int64                    `json:"width"`
	Height  *int64                    `json:"height"`
	Boxes   map[string]wandbMediaFile `json:"boxes"`
	Masks   map[string]wandbMediaFile `json:"masks"`
}

// wandbMediaFile is the part of W&B media JSON that identifies its file.
type wandbMediaFile struct {
	Type         string `json:"_type"`
	Path         string `json:"path"`
	ArtifactPath string `json:"artifact_path"`
	Sha256       string `json:"sha256"`
	Size         int64  `json:"size"`
}

func (c *mediaConverter) convertMedia(
	mediaJSON json.RawMessage,
	mediaType string,
) (json.RawMessage, error) {
	var media wandbMedia
	if err := json.Unmarshal(mediaJSON, &media); err != nil {
		return nil, fmt.Errorf("invalid media: %v", err)
	}
	if media.Type != mediaType {
		return nil, fmt.Errorf("expected %s media, got %q", mediaType, media.Type)
	}

	uri, err := c.uri(media.wandbMediaFile)
	if err != nil {
		return nil, err
	}

	var value any
	switch mediaType {
	case imageMediaType:
		value, err = c.imageValue(media, uri)
	case audioMediaType:
		value = audioValue(media, uri)
	case videoMediaType:
		value = videoValue(media, uri)
	}
	if err != nil {
		return nil, err
	}

	converted, err := appendJSON(nil, value)
	if err != nil {
		return nil, err
	}
	if len(converted) >= maxMediaValueBytes {
		return nil, fmt.Errorf(
			"media value is %d bytes, must be under %d",
			len(converted), maxMediaValueBytes)
	}
	return converted, nil
}

func (c *mediaConverter) imageValue(
	media wandbMedia,
	uri string,
) (ces.WandbImageV1Param, error) {
	value := ces.WandbImageV1Param{
		ExtensionType: ces.F(ces.WandbImageV1ExtensionTypeWandbImage),
		Format:        ces.F(media.Format),
		SchemaVersion: ces.F(ces.WandbImageV1SchemaVersion1),
		Sha256:        ces.F(media.Sha256),
		Size:          ces.F(media.Size),
		Uri:           ces.F(uri),
		WbMediaType:   ces.F(ces.WandbImageV1WbMediaTypeImageFile),
	}
	if media.Caption != nil {
		value.Caption = ces.F(*media.Caption)
	}
	if media.Width != nil {
		value.Width = ces.F(*media.Width)
	}
	if media.Height != nil {
		value.Height = ces.F(*media.Height)
	}

	if media.Boxes != nil {
		boxes := make(map[string]ces.WandbImageBoxesV1Param, len(media.Boxes))
		for key, box := range media.Boxes {
			uri, err := c.uri(box)
			if err != nil {
				return value, fmt.Errorf("boxes %q: %v", key, err)
			}
			boxes[key] = ces.WandbImageBoxesV1Param{
				Sha256: ces.F(box.Sha256),
				Size:   ces.F(box.Size),
				Uri:    ces.F(uri),
				Type:   ces.F(ces.WandbImageBoxesV1_Type(box.Type)),
			}
		}
		value.Boxes = ces.F(boxes)
	}

	if media.Masks != nil {
		masks := make(map[string]ces.WandbImageMaskV1Param, len(media.Masks))
		for key, mask := range media.Masks {
			uri, err := c.uri(mask)
			if err != nil {
				return value, fmt.Errorf("masks %q: %v", key, err)
			}
			masks[key] = ces.WandbImageMaskV1Param{
				Sha256: ces.F(mask.Sha256),
				Size:   ces.F(mask.Size),
				Uri:    ces.F(uri),
				Type:   ces.F(ces.WandbImageMaskV1_Type(mask.Type)),
			}
		}
		value.Masks = ces.F(masks)
	}

	return value, nil
}

func audioValue(media wandbMedia, uri string) ces.WandbAudioV1Param {
	value := ces.WandbAudioV1Param{
		ExtensionType: ces.F(ces.WandbAudioV1ExtensionTypeWandbAudio),
		SchemaVersion: ces.F(ces.WandbAudioV1SchemaVersion1),
		Sha256:        ces.F(media.Sha256),
		Size:          ces.F(media.Size),
		Uri:           ces.F(uri),
		WbMediaType:   ces.F(ces.WandbAudioV1WbMediaTypeAudioFile),
	}
	if media.Caption != nil {
		value.Caption = ces.F(*media.Caption)
	}
	return value
}

func videoValue(media wandbMedia, uri string) ces.WandbVideoV1Param {
	value := ces.WandbVideoV1Param{
		ExtensionType: ces.F(ces.WandbVideoV1ExtensionTypeWandbVideo),
		SchemaVersion: ces.F(ces.WandbVideoV1SchemaVersion1),
		Sha256:        ces.F(media.Sha256),
		Size:          ces.F(media.Size),
		Uri:           ces.F(uri),
		WbMediaType:   ces.F(ces.WandbVideoV1WbMediaTypeVideoFile),
	}
	if media.Caption != nil {
		value.Caption = ces.F(*media.Caption)
	}
	if media.Width != nil {
		value.Width = ces.F(*media.Width)
	}
	if media.Height != nil {
		value.Height = ces.F(*media.Height)
	}
	return value
}

// uri returns the CES URI of a media file: its artifact URI if it's in an
// artifact, and otherwise its run file URI.
func (c *mediaConverter) uri(file wandbMediaFile) (string, error) {
	if strings.HasPrefix(file.ArtifactPath, "wandb-artifact://") {
		return file.ArtifactPath, nil
	}

	if file.Path == "" {
		return "", errors.New("media has no path or artifact path")
	}

	components := []string{c.runPath.Entity, c.runPath.Project, c.runPath.RunID}
	for component := range strings.SplitSeq(file.Path, "/") {
		if component != "" && component != "." {
			components = append(components, component)
		}
	}
	for i, component := range components {
		// PathEscape escapes "/", so a component can't add a path segment.
		components[i] = url.PathEscape(component)
	}

	return "wandb-run-file://" + strings.Join(components, "/"), nil
}
