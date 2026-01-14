package nfs

import (
	"context"
	"encoding/json"
	"fmt"
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
			files = append(files, ArtifactFileInfo{
				Name:      edge.Node.Name,
				SizeBytes: edge.Node.SizeBytes,
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
