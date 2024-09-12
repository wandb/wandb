package artifacts

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	// Fields from the spb.ArtifactManifestEntry proto.
	Digest          string         `json:"digest"`
	Ref             *string        `json:"ref,omitempty"`
	Size            int64          `json:"size"`
	LocalPath       *string        `json:"local_path,omitempty"`
	BirthArtifactID *string        `json:"birthArtifactID,omitempty"`
	SkipCache       bool           `json:"skip_cache"`
	Extra           map[string]any `json:"extra,omitempty"`
	// Added and used during download.
	DownloadURL *string `json:"-"`
}

func NewManifestFromProto(proto *spb.ArtifactManifest) (Manifest, error) {
	manifest := Manifest{
		Version:             proto.Version,
		StoragePolicy:       proto.StoragePolicy,
		StoragePolicyConfig: StoragePolicyConfig{StorageLayout: "V2"},
		Contents:            make(map[string]ManifestEntry),
	}

	if proto.ManifestFilePath != "" {
		contents, err := ManifestContentsFromFile(proto.ManifestFilePath)
		if err != nil {
			return Manifest{}, err
		}
		manifest.Contents = contents
	}
	for _, entry := range proto.Contents {
		extra := make(map[string]any, len(entry.Extra))
		for _, item := range entry.Extra {
			var value any
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

func ManifestContentsFromFile(path string) (map[string]ManifestEntry, error) {
	// Whether or not we successfully decode the manifest, we should clean up the file.
	defer os.Remove(path)

	manifestFile, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("error opening manifest file: %w", err)
	}
	defer manifestFile.Close()

	// The file is gzipped and needs to be decompressed.
	gzReader, err := gzip.NewReader(manifestFile)
	if err != nil {
		return nil, fmt.Errorf("error opening manifest file: %w", err)
	}
	defer gzReader.Close()

	// Read the individual lines (each line is a json object).
	scanner := bufio.NewScanner(gzReader)
	contents := make(map[string]ManifestEntry)

	for scanner.Scan() {
		var entry ManifestEntry
		var record map[string]any
		line := scanner.Bytes()
		if err := json.Unmarshal(line, &record); err != nil {
			return nil, fmt.Errorf("could not unmarshal json: %w", err)
		}

		path, ok := record["path"].(string)
		if !ok {
			return nil, fmt.Errorf("record missing 'path' key or not a string")
		}
		entry.Digest, ok = record["digest"].(string)
		if !ok {
			return nil, fmt.Errorf("record missing 'digest' key or not a string")
		}
		size, ok := record["size"].(float64)
		if !ok {
			entry.Size = 0
		} else {
			entry.Size = int64(size)
		}
		ref, ok := record["ref"].(string)
		if !ok || ref == "" {
			entry.Ref = nil
		} else {
			entry.Ref = &ref
		}
		localPath, ok := record["local_path"].(string)
		if !ok || localPath == "" {
			entry.LocalPath = nil
		} else {
			entry.LocalPath = &localPath
		}
		birthArtifactID, ok := record["birthArtifactID"].(string)
		if !ok || birthArtifactID == "" {
			entry.BirthArtifactID = nil
		} else {
			entry.BirthArtifactID = &birthArtifactID
		}
		entry.SkipCache, ok = record["skip_cache"].(bool)
		if !ok {
			entry.SkipCache = false
		}

		// "extra" is itself a JSON object.
		entry.Extra, ok = record["extra"].(map[string]any)
		if !ok {
			entry.Extra = make(map[string]any)
		}
		contents[path] = entry
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("error scanning file: %w", err)
	}
	return contents, nil
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
	client := retryablehttp.NewClient()
	client.Logger = observability.NewNoOpLogger()
	resp, err := client.Get(url)

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
