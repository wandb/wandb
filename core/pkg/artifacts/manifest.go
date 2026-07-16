package artifacts

import (
	"bufio"
	"compress/gzip"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"sync"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/hashencode"
	"github.com/wandb/wandb/core/internal/nullify"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"golang.org/x/sync/errgroup"
)

type Manifest struct {
	Version             int32                    `json:"version"`
	StoragePolicy       string                   `json:"storagePolicy"`
	StoragePolicyConfig StoragePolicyConfig      `json:"storagePolicyConfig"`
	Contents            map[string]ManifestEntry `json:"contents"`
}

type StoragePolicyConfig struct {
	StorageLayout string  `json:"storageLayout"`
	StorageRegion *string `json:"storageRegion,omitempty"`
}

type ManifestEntry struct {
	// Fields from the spb.ArtifactManifestEntry proto.
	Digest          string         `json:"digest"`
	DigestAlgorithm *string        `json:"digestAlgorithm,omitempty"`
	Ref             *string        `json:"ref,omitempty"`
	Size            int64          `json:"size"`
	LocalPath       *string        `json:"local_path,omitempty"`
	BirthArtifactID *string        `json:"birthArtifactID,omitempty"`
	SkipCache       bool           `json:"skip_cache"`
	Extra           map[string]any `json:"extra,omitempty"`
	// Added and used during download.
	DownloadURL *string `json:"-"`
}

// NewManifestFromProto is used by [ArtifactSaver] to decode manifest sent
// from python process. If the manifest JSON is too big for proto, python
// side will save it as a local file and read using [ManifestContentsFromFile].
func NewManifestFromProto(proto *spb.ArtifactManifest) (Manifest, error) {
	if proto == nil {
		return Manifest{}, errors.New("nil ArtifactManifest proto")
	}

	manifest := Manifest{
		Version:             proto.Version,
		StoragePolicy:       proto.StoragePolicy,
		StoragePolicyConfig: StoragePolicyConfig{StorageLayout: "V2"},
		Contents:            make(map[string]ManifestEntry),
	}
	// TODO: why are we doing `json.dumps` on python side when sending the config?
	for _, cfg := range proto.StoragePolicyConfig {
		if cfg.Key == "storageRegion" {
			var s string
			if err := json.Unmarshal([]byte(cfg.ValueJson), &s); err != nil {
				return Manifest{}, fmt.Errorf("error unmarshalling storageRegion: %w", err)
			}
			manifest.StoragePolicyConfig.StorageRegion = &s
		}
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
			DigestAlgorithm: nullify.NilIfZero(entry.DigestAlgorithm),
			Ref:             nullify.NilIfZero(entry.Ref),
			Size:            entry.Size,
			LocalPath:       nullify.NilIfZero(entry.LocalPath),
			BirthArtifactID: nullify.NilIfZero(entry.BirthArtifactId),
			SkipCache:       entry.SkipCache,
			Extra:           extra,
		}
	}
	return manifest, nil
}

func ManifestContentsFromFile(path string) (map[string]ManifestEntry, error) {
	// Whether or not we successfully decode the manifest, we should clean up the file.
	defer func() {
		_ = os.Remove(path)
	}()

	manifestFile, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("error opening manifest file: %w", err)
	}
	defer func() {
		_ = manifestFile.Close()
	}()

	// The file is gzipped and needs to be decompressed.
	gzReader, err := gzip.NewReader(manifestFile)
	if err != nil {
		return nil, fmt.Errorf("error opening manifest file: %w", err)
	}
	defer func() {
		_ = gzReader.Close()
	}()

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
		digestAlgorithm, ok := record["digestAlgorithm"].(string)
		if !ok || digestAlgorithm == "" {
			entry.DigestAlgorithm = nil
		} else {
			entry.DigestAlgorithm = &digestAlgorithm
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

// WriteToFile serializes the manifest to a uniquely named temporary file inside
// dir (an empty dir uses the OS default temp directory). The caller chooses
// dir. See WriteJSONToTempFileWithMetadata.
func (m *Manifest) WriteToFile(
	dir string,
) (filename, digest string, size int64, rerr error) {
	return WriteJSONToTempFileWithMetadata(m, dir)
}

func (m *Manifest) GetManifestEntryFromArtifactFilePath(path string) (ManifestEntry, error) {
	manifestEntries := m.Contents
	manifestEntry, ok := manifestEntries[path]
	if !ok {
		return ManifestEntry{}, fmt.Errorf("path not contained in artifact: %s", path)
	}
	return manifestEntry, nil
}

// HashContentsWithMd5 hashes the contents of the manifest with MD5.
func (m *Manifest) HashContentsWithMd5() error {
	type pathDigest struct {
		path   string
		digest string
	}

	var mu sync.Mutex
	md5DigestAlgorithm := string(gql.ArtifactDigestAlgorithmManifestMd5)
	toHash := make([]struct {
		path  string
		localPath string
	}, 0, len(m.Contents))

	for path, entry := range m.Contents {
		if entry.LocalPath == nil || entry.DigestAlgorithm == nil || *entry.DigestAlgorithm == string(gql.ArtifactDigestAlgorithmManifestMd5) {
			continue
		}
		toHash = append(toHash, struct {
			path  string
			localPath string
		}{path: path, localPath: *entry.LocalPath})
	}

	// Hash files in parallel.
	g, _ := errgroup.WithContext(context.Background())
	for _, item := range toHash {
		g.Go(func() error {
			md5Hash, err := hashencode.ComputeFileB64MD5(item.localPath)
			if err != nil {
				return fmt.Errorf("ArtifactSaver.hashArtifactWithMd5: %w", err)
			}

			mu.Lock()
			entry := m.Contents[item.path]
			entry.Digest = md5Hash
			entry.DigestAlgorithm = &md5DigestAlgorithm
			m.Contents[item.path] = entry
			mu.Unlock()
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return err
	}

	return nil
}

func (m *Manifest) ArtifactDigest(digestAlgorithm gql.ArtifactDigestAlgorithm) (string, error) {
	if digestAlgorithm != gql.ArtifactDigestAlgorithmManifestMd5 {
		return "", fmt.Errorf("unsupported digest algorithm: %s", digestAlgorithm)
	}

	sortedPaths := make([]string, 0, len(m.Contents))
	for path := range m.Contents {
		sortedPaths = append(sortedPaths, path)
	}
	sort.Slice(sortedPaths, func(i, j int) bool {
		return sortedPaths[i] < sortedPaths[j]
	})

	data := []byte("wandb-artifact-manifest-v1\n")
	for _, path := range sortedPaths {
		entry := m.Contents[path]
		data = append(data, []byte(path + ":" + entry.Digest + "\n")...)
	}
	return hashencode.ComputeHexMD5(data), nil
}
