package artifacts

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/wandb/wandb/nexus/pkg/service"
	"github.com/wandb/wandb/nexus/pkg/utils"
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
	Digest          string                 `json:"digest"`
	BirthArtifactID *string                `json:"birthArtifactID"`
	Ref             *string                `json:"ref,omitempty"`
	Size            int64                  `json:"size"`
	Extra           map[string]interface{} `json:"extra,omitempty"`
	LocalPath       *string                `json:"-"`
	DownloadURL     *string                `json:"-"`
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
			BirthArtifactID: utils.NilIfZero(entry.BirthArtifactId),
			Ref:             utils.NilIfZero(entry.Ref),
			Size:            entry.Size,
			Extra:           extra,
			LocalPath:       utils.NilIfZero(entry.LocalPath),
		}
	}
	return manifest, nil
}

func (m *Manifest) WriteToFile() (filename string, digest string, rerr error) {
	data, rerr := json.Marshal(m)
	if rerr != nil {
		return
	}

	f, rerr := os.CreateTemp("", "tmpfile-")
	if rerr != nil {
		return
	}
	defer f.Close()
	_, rerr = f.Write(data)
	if rerr != nil {
		return
	}
	filename = f.Name()

	digest, rerr = utils.ComputeB64MD5(data)
	return
}

func (m *Manifest) GetManifestEntryFromArtifactFilePath(path string) (ManifestEntry, error) {
	manifestEntries := m.Contents
	manifestEntry, ok := manifestEntries[path]
	if !ok {
		// implement _get_obj_entry
		// For now just return error
		return ManifestEntry{}, fmt.Errorf("Path not contained in artifact: %s", path)
	}
	return manifestEntry, nil
}
