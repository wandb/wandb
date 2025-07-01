package artifacts

import (
	"context"
	"fmt"
	"log/slog"
	"maps"
	"path/filepath"
	"slices"
	"strconv"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
)

const (
	BATCH_SIZE  int = 5000
	MAX_BACKLOG int = 5000
)

type ArtifactDownloader struct {
	// Resources
	Ctx             context.Context
	GraphqlClient   graphql.Client
	DownloadManager filetransfer.FileTransferManager
	FileCache       Cache
	// Input
	ArtifactID             string
	DownloadRoot           string
	AllowMissingReferences bool   // Currently unused
	SkipCache              bool   // Currently unused
	PathPrefix             string // Currently unused
}

func NewArtifactDownloader(
	ctx context.Context,
	graphQLClient graphql.Client,
	downloadManager filetransfer.FileTransferManager,
	artifactID string,
	downloadRoot string,
	allowMissingReferences bool,
	skipCache bool,
	pathPrefix string,
) *ArtifactDownloader {
	var fileCache Cache
	if !skipCache {
		fileCache = NewFileCache(UserCacheDir())
	} else {
		fileCache = NewHashOnlyCache()

	}
	return &ArtifactDownloader{
		Ctx:                    ctx,
		GraphqlClient:          graphQLClient,
		DownloadManager:        downloadManager,
		ArtifactID:             artifactID,
		DownloadRoot:           downloadRoot,
		AllowMissingReferences: allowMissingReferences,
		SkipCache:              skipCache,
		PathPrefix:             pathPrefix,
		FileCache:              fileCache,
	}
}

func (ad *ArtifactDownloader) getArtifactManifest(artifactID string) (manifest Manifest, rerr error) {
	response, err := gql.ArtifactManifest(
		ad.Ctx,
		ad.GraphqlClient,
		artifactID,
	)
	if err != nil {
		return Manifest{}, err
	} else if response == nil {
		return Manifest{}, fmt.Errorf("could not get manifest for artifact")
	}
	artifact := response.Artifact
	if artifact == nil {
		return Manifest{}, fmt.Errorf("could not access artifact")
	}
	artifactManifest := artifact.CurrentManifest
	if artifactManifest == nil {
		return Manifest{}, fmt.Errorf("could not access manifest for artifact")
	}
	directURL := artifactManifest.GetFile().DirectUrl
	manifest, err = loadManifestFromURL(directURL)
	if err != nil {
		return Manifest{}, err
	}
	return manifest, nil
}

// getBatchEntriesWithFileUrls fetches file urls for the entries in
// entriesToFetch and returns a list of the formatted manifest entries to
// download in the current batch.
func (ad *ArtifactDownloader) getBatchEntriesWithFileUrls(
	artifactID string,
	entriesToFetch []gql.ArtifactManifestEntryInput,
	manifest Manifest,
	manifestEntries map[string]ManifestEntry,
	nameToScheduledTime map[string]time.Time,
) ([]ManifestEntry, error) {
	var entries []ManifestEntry
	now := time.Now()
	response, err := gql.ArtifactFileURLsByManifestEntries(
		ad.Ctx,
		ad.GraphqlClient,
		artifactID,
		entriesToFetch,
		manifest.StoragePolicyConfig.StorageLayout,
		strconv.Itoa(int(manifest.Version)),
		nil,
	)
	if err != nil {
		return nil, err
	}
	for _, edge := range response.GetArtifact().GetFilesByManifestEntries().Edges {
		filePath := edge.GetNode().Name
		entry, err := manifest.GetManifestEntryFromArtifactFilePath(filePath)
		if err != nil {
			return nil, err
		}
		node := edge.GetNode()
		if node == nil {
			return nil, fmt.Errorf("error reading entry from fetched file urls")
		}
		entry.DownloadURL = &node.DirectUrl
		entry.LocalPath = &filePath
		nameToScheduledTime[*entry.LocalPath] = now
		entries = append(entries, entry)
		delete(manifestEntries, filePath)
	}
	return entries, nil
}

// addEntriesToBatch fetches file urls for the entries in entriesToFetch and returns the formatted manifest entries to
// download in the current batch, the number of entries skipped, and a boolean indicating if there are more pages to fetch.
func (ad *ArtifactDownloader) addEntriesToBatch(
	artifactID string,
	manifest Manifest,
	manifestEntriesCopy map[string]ManifestEntry,
	nameToScheduledTime map[string]time.Time,
) ([]ManifestEntry, int, bool, error) {
	curBatchSize, numSkipped := 0, 0
	var entriesToFetch []gql.ArtifactManifestEntryInput
	for filePath, entry := range manifestEntriesCopy {
		if _, ok := nameToScheduledTime[filePath]; ok {
			continue
		}
		if entry.Ref != nil {
			// Reference artifacts will temporarily be handled by the python user process
			numSkipped++
			delete(manifestEntriesCopy, filePath)
			continue
		} else {
			entryInput := gql.ArtifactManifestEntryInput{
				Name:            filePath,
				Digest:          entry.Digest,
				BirthArtifactID: entry.BirthArtifactID,
				Size:            &entry.Size,
			}
			entriesToFetch = append(entriesToFetch, entryInput)
		}
		curBatchSize += 1
		if curBatchSize >= BATCH_SIZE {
			break
		}
	}
	entries := []ManifestEntry{}
	if len(entriesToFetch) > 0 {
		var err error
		entries, err = ad.getBatchEntriesWithFileUrls(
			artifactID,
			entriesToFetch,
			manifest,
			manifestEntriesCopy,
			nameToScheduledTime,
		)
		if err != nil {
			return nil, 0, false, err
		}
	}
	hasNextPage := len(manifestEntriesCopy) > 0
	return entries, numSkipped, hasNextPage, nil
}

// addEntriesToBatchLegacy is the legacy implementation of addEntriesToBatch.
// It fetches file urls for the entries in entriesToFetch and returns the formatted manifest entries to
// download in the current batch, the number of entries skipped, a boolean indicating if there are more pages to fetch,
// and the cursor for the next page.
func (ad *ArtifactDownloader) addEntriesToBatchLegacy(
	artifactID string,
	manifest Manifest,
	manifestEntriesCopy map[string]ManifestEntry,
	nameToScheduledTime map[string]time.Time,
	cursor *string,
) ([]ManifestEntry, int, bool, *string, error) {
	batchSize := BATCH_SIZE
	numSkipped := 0
	now := time.Now()
	entries := []ManifestEntry{}
	response, err := gql.ArtifactFileURLs(
		ad.Ctx,
		ad.GraphqlClient,
		artifactID,
		cursor,
		&batchSize,
	)
	if err != nil {
		return nil, 0, false, nil, err
	}
	hasNextPage := response.Artifact.Files.PageInfo.HasNextPage
	cursor = response.Artifact.Files.PageInfo.EndCursor
	for _, edge := range response.GetArtifact().GetFiles().Edges {
		filePath := edge.GetNode().Name
		entry, err := manifest.GetManifestEntryFromArtifactFilePath(filePath)
		if err != nil {
			return nil, 0, false, nil, err
		}
		if _, ok := nameToScheduledTime[filePath]; ok {
			continue
		}
		// Reference artifacts will temporarily be handled by the python user process
		if entry.Ref != nil {
			numSkipped++
			continue
		}
		node := edge.GetNode()
		if node == nil {
			return nil, 0, false, nil, fmt.Errorf("error reading entry from fetched file urls")
		}
		entry.DownloadURL = &node.DirectUrl
		entry.LocalPath = &filePath
		nameToScheduledTime[*entry.LocalPath] = now
		entries = append(entries, entry)
	}
	return entries, numSkipped, hasNextPage, cursor, nil
}

func (ad *ArtifactDownloader) downloadFiles(artifactID string, manifest Manifest) error {
	// retrieve from "WANDB_ARTIFACT_FETCH_FILE_URL_BATCH_SIZE"?
	batchSize := BATCH_SIZE

	type TaskResult struct {
		Path string
		Err  error
		Name string
	}

	// Fetch URLs and download files in batches
	manifestEntries := manifest.Contents
	numInProgress, numDone := 0, 0
	nameToScheduledTime := map[string]time.Time{}
	taskResultsChan := make(chan TaskResult, MAX_BACKLOG)
	manifestEntriesBatch := make([]ManifestEntry, 0, batchSize)
	manifestEntriesCopy := map[string]ManifestEntry{}
	maps.Copy(manifestEntriesCopy, manifestEntries)

	artifactFieldNames, err := GetGraphQLFields(ad.Ctx, ad.GraphqlClient, "Artifact")
	if err != nil {
		return err
	}
	canFetchFilesByManifestEntry := slices.Contains(artifactFieldNames, "filesByManifestEntries")

	for numDone < len(manifestEntries) {
		var cursor *string
		hasNextPage := true
		for hasNextPage {
			// Prepare a batch
			manifestEntriesBatch = manifestEntriesBatch[:0]

			var entries []ManifestEntry
			var numSkipped int
			var err error
			if canFetchFilesByManifestEntry {
				entries, numSkipped, hasNextPage, err = ad.addEntriesToBatch(
					artifactID,
					manifest,
					manifestEntriesCopy,
					nameToScheduledTime,
				)
			} else {
				entries, numSkipped, hasNextPage, cursor, err = ad.addEntriesToBatchLegacy(
					artifactID,
					manifest,
					manifestEntriesCopy,
					nameToScheduledTime,
					cursor,
				)
			}
			if err != nil {
				return err
			}
			manifestEntriesBatch = append(manifestEntriesBatch, entries...)
			numDone += numSkipped

			// Schedule downloads
			if len(manifestEntriesBatch) > 0 {
				for _, entry := range manifestEntriesBatch {
					// Add function that returns download path?
					downloadLocalPath := filepath.Join(ad.DownloadRoot, *entry.LocalPath)
					// If we're skipping the cache, the HashOnlyCache still checks the destination
					// and returns true if the file is there and has the correct hash.
					if success := ad.FileCache.RestoreTo(entry, downloadLocalPath); success {
						numDone++
						continue
					}
					if entry.Ref != nil {
						task := &filetransfer.ReferenceArtifactDownloadTask{
							FileKind:     filetransfer.RunFileKindArtifact,
							PathOrPrefix: downloadLocalPath,
							Reference:    *entry.Ref,
							Digest:       entry.Digest,
							Size:         entry.Size,
						}
						versionId, ok := entry.Extra["versionID"]
						if ok {
							err := task.SetVersionID(versionId)
							if err != nil {
								return fmt.Errorf("error setting version id: %v", err)
							}
						}

						task.OnComplete = func() {
							taskResultsChan <- TaskResult{downloadLocalPath, task.Err, *entry.LocalPath}
						}
						ad.DownloadManager.AddTask(task)
					} else {
						task := &filetransfer.DefaultDownloadTask{
							FileKind: filetransfer.RunFileKindArtifact,
							Path:     downloadLocalPath,
							Url:      *entry.DownloadURL,
							Size:     entry.Size,
						}

						task.OnComplete = func() {
							taskResultsChan <- TaskResult{downloadLocalPath, task.Err, *entry.LocalPath}
						}
						ad.DownloadManager.AddTask(task)
					}
					numInProgress++
				}
			}
			// Wait for downloader to catch up. If there's nothing more to schedule, wait for all in progress tasks.
			for numInProgress > MAX_BACKLOG || (len(manifestEntriesBatch) == 0 && numInProgress > 0) {
				numInProgress--
				result := <-taskResultsChan
				if result.Err != nil {
					// We want to retry when the signed URL expires. However, distinguishing that error from others is not
					// trivial. As a heuristic, we retry if the request failed more than an hour after we fetched the URL.
					if time.Since(nameToScheduledTime[result.Name]) < 1*time.Hour {
						return result.Err
					}
					delete(nameToScheduledTime, result.Name) // retry
					continue
				}
				numDone++
				digest := manifest.Contents[result.Name].Digest
				go func() {
					err := ad.FileCache.AddFileAndCheckDigest(result.Path, digest)
					if err != nil {
						slog.Error("Error adding file to cache", "err", err)
					}
				}()
			}
		}
	}
	return nil
}

func (ad *ArtifactDownloader) Download() (rerr error) {
	artifactManifest, err := ad.getArtifactManifest(ad.ArtifactID)
	if err != nil {
		return err
	}

	if err := ad.downloadFiles(ad.ArtifactID, artifactManifest); err != nil {
		return err
	}
	return nil
}
