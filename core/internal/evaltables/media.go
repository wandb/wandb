package evaltables

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	ces "github.com/wandb/cwevals-go"

	"github.com/wandb/wandb/core/internal/runbranch"
)

// mediaSchemaVersion is the schema version of the CES extension values
// that mediaConverter produces.
const mediaSchemaVersion = 1

// mediaExtensionTypes maps the W&B media types that EvalTables support to
// the CES extension types of their values.
var mediaExtensionTypes = map[string]ces.EvalTableColumnNewParamsDatasetFieldsExtensionType{
	"image-file": ces.EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbImage,
	"audio-file": ces.EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbAudio,
	"video-file": ces.EvalTableColumnNewParamsDatasetFieldsExtensionTypeWandbVideo,
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

// convertMedia converts W&B media JSON to a CES extension value.
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
	case "image-file":
		value, err = c.imageValue(media, uri)
	case "audio-file":
		value = audioValue(media, uri)
	case "video-file":
		value = videoValue(media, uri)
	}
	if err != nil {
		return nil, err
	}

	return marshalJSON(value)
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
		components[i] = escapeURIComponent(component)
	}

	return "wandb-run-file://" + strings.Join(components, "/"), nil
}

// escapeURIComponent percent-encodes every byte of s except RFC 3986's
// unreserved characters, so that s can't contain a "/".
func escapeURIComponent(s string) string {
	var b strings.Builder
	for i := range len(s) {
		switch ch := s[i]; {
		case 'A' <= ch && ch <= 'Z', 'a' <= ch && ch <= 'z', '0' <= ch && ch <= '9',
			ch == '-', ch == '.', ch == '_', ch == '~':
			b.WriteByte(ch)
		default:
			fmt.Fprintf(&b, "%%%02X", ch)
		}
	}
	return b.String()
}

// marshalJSON encodes v without escaping HTML characters, which would only
// make rows larger.
func marshalJSON(v any) ([]byte, error) {
	var buf bytes.Buffer
	encoder := json.NewEncoder(&buf)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}
