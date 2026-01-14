package nfs

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
)

const (
	// TTL for cached data
	typesTTL       = 5 * time.Minute
	collectionsTTL = 1 * time.Minute
	filesTTL       = 5 * time.Minute
	metadataTTL    = 5 * time.Minute
)

// ArtifactFileInfo represents a file in an artifact.
type ArtifactFileInfo struct {
	Name      string
	SizeBytes int64
	DirectURL string // Download URL for file content
	MD5       string // Base64 MD5 hash for cache key
}

// ArtifactMetadata holds metadata for an artifact version.
type ArtifactMetadata struct {
	ID           string     `json:"id"`
	VersionIndex int        `json:"versionIndex"`
	Digest       string     `json:"digest"`
	Size         int64      `json:"size"`
	FileCount    int64      `json:"fileCount"`
	CreatedAt    time.Time  `json:"createdAt"`
	UpdatedAt    *time.Time `json:"updatedAt,omitempty"`
	Description  string     `json:"description,omitempty"`
	State        string     `json:"state"`
}

// ToJSON serializes the metadata to JSON.
func (m *ArtifactMetadata) ToJSON() ([]byte, error) {
	return json.MarshalIndent(m, "", "  ")
}

// cacheEntry holds cached data with expiration.
type cacheEntry[T any] struct {
	data      T
	loadedAt  time.Time
	ttl       time.Duration
	loadErr   error
	loadOnce  sync.Once
	loadMutex sync.Mutex
}

func (e *cacheEntry[T]) isExpired() bool {
	return time.Since(e.loadedAt) > e.ttl
}

// DataCache handles lazy fetching and caching of W&B data.
type DataCache struct {
	mu      sync.RWMutex
	client  graphql.Client
	project *ProjectPath
	lister  *Lister

	// Cache for artifact types
	types *cacheEntry[[]string]

	// Cache for collections by type name
	collections map[string]*cacheEntry[[]CollectionInfo]

	// Cache for files by artifact ID
	files map[string]*cacheEntry[[]ArtifactFileInfo]

	// Cache for metadata by artifact ID
	metadata map[string]*cacheEntry[*ArtifactMetadata]
}

// NewDataCache creates a new data cache.
func NewDataCache(client graphql.Client, project *ProjectPath) *DataCache {
	return &DataCache{
		client:      client,
		project:     project,
		lister:      NewLister(client),
		collections: make(map[string]*cacheEntry[[]CollectionInfo]),
		files:       make(map[string]*cacheEntry[[]ArtifactFileInfo]),
		metadata:    make(map[string]*cacheEntry[*ArtifactMetadata]),
	}
}

// GetTypes returns all artifact types in the project.
func (c *DataCache) GetTypes(ctx context.Context) ([]string, error) {
	c.mu.Lock()
	if c.types == nil {
		c.types = &cacheEntry[[]string]{ttl: typesTTL}
	}
	entry := c.types
	c.mu.Unlock()

	entry.loadMutex.Lock()
	defer entry.loadMutex.Unlock()

	if entry.loadErr == nil && len(entry.data) > 0 && !entry.isExpired() {
		return entry.data, nil
	}

	// Fetch from API
	types, err := c.lister.listArtifactTypes(ctx, c.project)
	if err != nil {
		entry.loadErr = err
		return nil, err
	}

	entry.data = types
	entry.loadedAt = time.Now()
	entry.loadErr = nil
	return types, nil
}

// GetCollections returns all collections for a specific artifact type.
func (c *DataCache) GetCollections(ctx context.Context, typeName string) ([]CollectionInfo, error) {
	c.mu.Lock()
	entry, ok := c.collections[typeName]
	if !ok {
		entry = &cacheEntry[[]CollectionInfo]{ttl: collectionsTTL}
		c.collections[typeName] = entry
	}
	c.mu.Unlock()

	entry.loadMutex.Lock()
	defer entry.loadMutex.Unlock()

	if entry.loadErr == nil && len(entry.data) > 0 && !entry.isExpired() {
		return entry.data, nil
	}

	// Fetch from API
	collections, err := c.lister.listCollectionsForType(ctx, c.project, typeName)
	if err != nil {
		entry.loadErr = err
		return nil, err
	}

	entry.data = collections
	entry.loadedAt = time.Now()
	entry.loadErr = nil
	return collections, nil
}

// GetAllCollections returns all collections across all types.
func (c *DataCache) GetAllCollections(ctx context.Context) ([]CollectionInfo, error) {
	types, err := c.GetTypes(ctx)
	if err != nil {
		return nil, err
	}

	var allCollections []CollectionInfo
	for _, typeName := range types {
		collections, err := c.GetCollections(ctx, typeName)
		if err != nil {
			return nil, fmt.Errorf("listing collections for type %s: %w", typeName, err)
		}
		allCollections = append(allCollections, collections...)
	}
	return allCollections, nil
}

// GetFiles returns all files for an artifact.
func (c *DataCache) GetFiles(ctx context.Context, artifactID string) ([]ArtifactFileInfo, error) {
	c.mu.Lock()
	entry, ok := c.files[artifactID]
	if !ok {
		entry = &cacheEntry[[]ArtifactFileInfo]{ttl: filesTTL}
		c.files[artifactID] = entry
	}
	c.mu.Unlock()

	entry.loadMutex.Lock()
	defer entry.loadMutex.Unlock()

	if entry.loadErr == nil && len(entry.data) > 0 && !entry.isExpired() {
		return entry.data, nil
	}

	// Fetch from API
	files, err := c.fetchFiles(ctx, artifactID)
	if err != nil {
		entry.loadErr = err
		return nil, err
	}

	entry.data = files
	entry.loadedAt = time.Now()
	entry.loadErr = nil
	return files, nil
}

// fetchFiles fetches artifact files from the API.
func (c *DataCache) fetchFiles(ctx context.Context, artifactID string) ([]ArtifactFileInfo, error) {
	var files []ArtifactFileInfo
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSArtifactFiles(ctx, c.client, artifactID, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Artifact == nil || resp.Artifact.Files == nil {
			break
		}

		for _, edge := range resp.Artifact.Files.Edges {
			if edge.Node == nil {
				continue
			}
			md5 := ""
			if edge.Node.Md5 != nil {
				md5 = *edge.Node.Md5
			}
			files = append(files, ArtifactFileInfo{
				Name:      edge.Node.Name,
				SizeBytes: edge.Node.SizeBytes,
				DirectURL: edge.Node.DirectUrl,
				MD5:       md5,
			})
		}

		if !resp.Artifact.Files.PageInfo.HasNextPage {
			break
		}
		cursor = resp.Artifact.Files.PageInfo.EndCursor
	}

	return files, nil
}

// GetMetadata returns metadata for an artifact.
func (c *DataCache) GetMetadata(ctx context.Context, artifactID string) (*ArtifactMetadata, error) {
	c.mu.Lock()
	entry, ok := c.metadata[artifactID]
	if !ok {
		entry = &cacheEntry[*ArtifactMetadata]{ttl: metadataTTL}
		c.metadata[artifactID] = entry
	}
	c.mu.Unlock()

	entry.loadMutex.Lock()
	defer entry.loadMutex.Unlock()

	if entry.loadErr == nil && entry.data != nil && !entry.isExpired() {
		return entry.data, nil
	}

	// Fetch from API
	metadata, err := c.fetchMetadata(ctx, artifactID)
	if err != nil {
		entry.loadErr = err
		return nil, err
	}

	entry.data = metadata
	entry.loadedAt = time.Now()
	entry.loadErr = nil
	return metadata, nil
}

// fetchMetadata fetches artifact metadata from the API.
func (c *DataCache) fetchMetadata(ctx context.Context, artifactID string) (*ArtifactMetadata, error) {
	resp, err := gql.NFSArtifactMetadata(ctx, c.client, artifactID)
	if err != nil {
		return nil, err
	}
	if resp.Artifact == nil {
		return nil, fmt.Errorf("artifact not found: %s", artifactID)
	}

	versionIndex := 0
	if resp.Artifact.VersionIndex != nil {
		versionIndex = *resp.Artifact.VersionIndex
	}

	description := ""
	if resp.Artifact.Description != nil {
		description = *resp.Artifact.Description
	}

	return &ArtifactMetadata{
		ID:           resp.Artifact.Id,
		VersionIndex: versionIndex,
		Digest:       resp.Artifact.Digest,
		Size:         resp.Artifact.Size,
		FileCount:    resp.Artifact.FileCount,
		CreatedAt:    resp.Artifact.CreatedAt,
		UpdatedAt:    resp.Artifact.UpdatedAt,
		Description:  description,
		State:        string(resp.Artifact.State),
	}, nil
}

// FileContentCache handles disk-based caching of artifact file content.
// Uses the same cache structure as Python SDK for cache sharing.
type FileContentCache struct {
	cacheDir string
	client   *http.Client
	mu       sync.Mutex
}

// NewFileContentCache creates a new file content cache.
// Cache location: ~/.cache/wandb/artifacts/obj/md5/{first2}/{rest}
func NewFileContentCache() *FileContentCache {
	homeDir, _ := os.UserHomeDir()
	return &FileContentCache{
		cacheDir: filepath.Join(homeDir, ".cache", "wandb", "artifacts"),
		client:   &http.Client{Timeout: 10 * time.Minute},
	}
}

// GetOrDownload returns the path to a cached file, downloading if necessary.
// md5B64 is the base64-encoded MD5 hash of the file content.
func (c *FileContentCache) GetOrDownload(ctx context.Context, md5B64, directURL string, size int64) (string, error) {
	if md5B64 == "" || directURL == "" {
		return "", fmt.Errorf("missing md5 or directURL")
	}

	// Convert base64 MD5 to hex
	md5Hex, err := b64ToHex(md5B64)
	if err != nil {
		return "", fmt.Errorf("invalid md5 hash: %w", err)
	}

	// Cache path: ~/.cache/wandb/artifacts/obj/md5/{first2}/{rest}
	cachePath := filepath.Join(c.cacheDir, "obj", "md5", md5Hex[:2], md5Hex[2:])

	// Check if already cached with correct size
	if info, err := os.Stat(cachePath); err == nil && info.Size() == size {
		return cachePath, nil
	}

	// Download to cache
	return c.download(ctx, directURL, cachePath)
}

// download downloads a file from URL to the cache path atomically.
func (c *FileContentCache) download(ctx context.Context, url, destPath string) (string, error) {
	slog.Info("downloading artifact file",
		"destPath", destPath,
		"urlPrefix", url[:min(80, len(url))]+"...")

	// Create parent directories
	if err := os.MkdirAll(filepath.Dir(destPath), 0o755); err != nil {
		return "", fmt.Errorf("creating cache directory: %w", err)
	}

	// Create temp file in the same directory for atomic rename
	tmpFile, err := os.CreateTemp(filepath.Dir(destPath), ".download-*")
	if err != nil {
		return "", fmt.Errorf("creating temp file: %w", err)
	}
	tmpPath := tmpFile.Name()

	// Ensure cleanup on failure
	success := false
	defer func() {
		if !success {
			os.Remove(tmpPath)
		}
	}()

	// Download the file
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		tmpFile.Close()
		return "", fmt.Errorf("creating request: %w", err)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		tmpFile.Close()
		slog.Error("HTTP request failed", "error", err)
		return "", fmt.Errorf("downloading file: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		tmpFile.Close()
		slog.Error("download failed",
			"status", resp.StatusCode,
			"statusText", resp.Status)
		if resp.StatusCode == http.StatusForbidden {
			return "", fmt.Errorf("download failed: HTTP 403 Forbidden (URL may have expired, try re-listing the directory)")
		}
		return "", fmt.Errorf("download failed: HTTP %d %s", resp.StatusCode, resp.Status)
	}

	// Copy to temp file
	if _, err := io.Copy(tmpFile, resp.Body); err != nil {
		tmpFile.Close()
		return "", fmt.Errorf("writing file: %w", err)
	}

	if err := tmpFile.Close(); err != nil {
		return "", fmt.Errorf("closing temp file: %w", err)
	}

	// Atomic rename to final location
	if err := os.Rename(tmpPath, destPath); err != nil {
		return "", fmt.Errorf("renaming to cache: %w", err)
	}

	success = true
	return destPath, nil
}

// b64ToHex converts a base64-encoded string to hex.
func b64ToHex(b64 string) (string, error) {
	data, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(data), nil
}
