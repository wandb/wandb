package artifacts

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

type Manifest struct {
	Version             int32                    `json:"version"`
	StoragePolicy       string                   `json:"storagePolicy"`
	StoragePolicyConfig StoragePolicyConfig      `json:"storagePolicyConfig"`
	Contents            map[string]ManifestEntry `json:"contents"`
}

type StoragePolicyConfig struct {
	StorageLayout string `json:"storageLayout"`
}

type ManifestEntry struct {
	// Fields from the service.ArtifactManifestEntry proto.
	Digest          string                 `json:"digest"`
	Ref             *string                `json:"ref,omitempty"`
	Size            int64                  `json:"size"`
	LocalPath       *string                `json:"-"`
	BirthArtifactID *string                `json:"birthArtifactID"`
	SkipCache       bool                   `json:"-"`
	Extra           map[string]interface{} `json:"extra,omitempty"`
	// Added and used during download.
	DownloadURL *string `json:"-"`
}

func NewManifestFromProto(proto *service.ArtifactManifest) (Manifest, error) {
	manifest := Manifest{
		Version:             proto.Version,
		StoragePolicy:       proto.StoragePolicy,
		StoragePolicyConfig: StoragePolicyConfig{StorageLayout: "V2"},
		Contents:            make(map[string]ManifestEntry),
	}
	for _, entry := range proto.Contents {
		extra := map[string]interface{}{}
		for _, item := range entry.Extra {
			var value interface{}
			err := json.Unmarshal([]byte(item.ValueJson), &value)
			if err != nil {
				return Manifest{}, fmt.Errorf(
					"manifest entry extra json.Unmarshal: %w", err,
				)
			}
			extra[item.Key] = value
		}
		manifest.Contents[entry.Path] = ManifestEntry{
			Digest:          entry.Digest,
			Ref:             utils.NilIfZero(entry.Ref),
			Size:            entry.Size,
			LocalPath:       utils.NilIfZero(entry.LocalPath),
			BirthArtifactID: utils.NilIfZero(entry.BirthArtifactId),
			SkipCache:       entry.SkipCache,
			Extra:           extra,
		}
	}
	return manifest, nil
}

func (m *Manifest) WriteToFile() (filename string, digest string, size int64, rerr error) {
	return utils.WriteJsonToFileWithDigest(m)
}

func (m *Manifest) GetManifestEntryFromArtifactFilePath(path string) (ManifestEntry, error) {
	manifestEntries := m.Contents
	manifestEntry, ok := manifestEntries[path]
	if !ok {
		return ManifestEntry{}, fmt.Errorf("path not contained in artifact: %s", path)
	}
	return manifestEntry, nil
}

func loadManifestFromURL(url string) (Manifest, error) {
	resp, err := retryablehttp.NewClient().Get(url)

	if err != nil {
		return Manifest{}, err
	}
	defer resp.Body.Close()
	manifest := Manifest{}
	if resp.StatusCode != http.StatusOK {
		return Manifest{}, fmt.Errorf("request to get manifest from url failed with status code: %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return Manifest{}, fmt.Errorf("error reading response body: %v", err)
	}
	err = json.Unmarshal(body, &manifest)
	if err != nil {
		return Manifest{}, nil
	}
	return manifest, nil
}
