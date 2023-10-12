package artifacts

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/internal/filetransfer"
	"github.com/wandb/wandb/nexus/internal/gql"
	"github.com/wandb/wandb/nexus/pkg/env"
)

const BATCH_SIZE int = 10000
const MAX_BACKLOG int = 10000

type ArtifactDownloader struct {
	// Resources
	Ctx             context.Context
	GraphqlClient   graphql.Client
	DownloadManager *filetransfer.FileTransferManager
	//Input
	QualifiedName          string
	DownloadRoot           *string
	Recursive              *bool
	AllowMissingReferences *bool
}

func NewArtifactDownloader(
	ctx context.Context,
	graphQLClient graphql.Client,
	downloadManager *filetransfer.FileTransferManager,
	qualifiedName string,
	downloadRoot *string,
	recursive *bool,
	allowMissingReferences *bool,
) ArtifactDownloader {
	return ArtifactDownloader{
		Ctx:                    ctx,
		GraphqlClient:          graphQLClient,
		DownloadManager:        downloadManager,
		QualifiedName:          qualifiedName,
		DownloadRoot:           downloadRoot,
		Recursive:              recursive,
		AllowMissingReferences: allowMissingReferences,
	}
}

func (ad *ArtifactDownloader) getArtifact() (attrs gql.ArtifactByNameProjectArtifact, rerr error) {
	fmt.Printf("\nQualified Name ===> %s\n", ad.QualifiedName)
	entityName, projectName, artifactName, err := parseArtifactQualifiedName(ad.QualifiedName)
	if err != nil {
		return gql.ArtifactByNameProjectArtifact{}, err
	}
	response, err := gql.ArtifactByName(
		ad.Ctx,
		ad.GraphqlClient,
		entityName,
		projectName,
		artifactName,
	)
	if err != nil {
		return gql.ArtifactByNameProjectArtifact{}, err
	}
	return *response.GetProject().GetArtifact(), nil
}

func (ad *ArtifactDownloader) getArtifactManifest() (artifactManifest Manifest, rerr error) {
	entityName, projectName, artifactName, err := parseArtifactQualifiedName(ad.QualifiedName)
	if err != nil {
		return Manifest{}, err
	}
	response, err := gql.ArtifactManifest(
		ad.Ctx,
		ad.GraphqlClient,
		entityName,
		projectName,
		artifactName,
	)
	if err != nil {
		return Manifest{}, err
	} else if response == nil {
		return Manifest{}, fmt.Errorf("Could not get manifest from server")
	}
	directURL := response.GetProject().GetArtifact().GetCurrentManifest().GetFile().DirectUrl
	return loadManifestFromURL(directURL)
}

func (ad *ArtifactDownloader) setDefaultDownloadRoot(artifactAttrs gql.ArtifactByNameProjectArtifact) (rerr error) {
	// set absolute path to source_artifact_name:v{versionIndex} as default root
	sourceArtifactName := artifactAttrs.GetArtifactSequence().Name
	versionIndex := artifactAttrs.GetVersionIndex()
	if versionIndex == nil {
		return fmt.Errorf("Invalid artifact download, missing version index")
	}
	artifactDir, err := env.GetArtifactDir()
	if err != nil {
		return err
	}
	fmt.Printf("\n\n Artifacts_dir ===> %v \n\n", artifactDir)
	downloadRoot := filepath.Join(artifactDir, fmt.Sprintf("%s:v%d", sourceArtifactName, *versionIndex))

	// todo: the utils are not tested. are probably incorrect
	path := CheckExists(downloadRoot)
	if path == nil {
		downloadRoot = SystemPreferredPath(downloadRoot, false)
	}
	ad.DownloadRoot = &downloadRoot
	return nil
}

func (ad *ArtifactDownloader) getArtifactManifestEntries() (map[string]ManifestEntry, error) {
	artifactManifest, err := ad.getArtifactManifest()
	if err != nil {
		return map[string]ManifestEntry{}, err
	}
	fmt.Printf("\n\n manifest ===> %v \n\n", artifactManifest)
	return artifactManifest.Contents, nil
}

func (ad *ArtifactDownloader) ensureDownloadRootDir() error {
	fmt.Printf("\n\n baseDir ===> %v \n\n", ad.DownloadRoot)
	info, err := os.Stat(*ad.DownloadRoot)
	if err == nil && info.IsDir() {
		return nil
	}
	return os.MkdirAll(*ad.DownloadRoot, 0777)
}

func (ad *ArtifactDownloader) downloadFiles(artifactID string, manifestEntries map[string]ManifestEntry) error {
	// retrieve from "WANDB_ARTIFACT_FETCH_FILE_URL_BATCH_SIZE"?
	batchSize := BATCH_SIZE

	// Change to downloader or file_manager
	type TaskResult struct {
		Task *filetransfer.DownloadTask
		Name string
	}

	// Fetch URLs and download files in batches
	numInProgress, numDone := 0, 0
	nameToScheduledTime := map[string]time.Time{}
	taskResultsChan := make(chan TaskResult)
	manifestEntriesBatch := make([]ManifestEntry, 0, batchSize)

	cursor := ""
	hasNextPage := true
	for numDone < len(manifestEntries) {
		// Prepare a batch
		now := time.Now()
		manifestEntriesBatch = manifestEntriesBatch[:0]
		for hasNextPage {
			response, err := gql.ArtifactFileURLs(
				ad.Ctx,
				ad.GraphqlClient,
				artifactID,
				&cursor,
				&batchSize,
			)
			if err != nil {
				return err
			} else if response == nil {
				return fmt.Errorf("Could not fetch artifact file urls for %s", ad.QualifiedName)
			}
			hasNextPage = response.GetArtifact().GetFiles().PageInfo.HasNextPage
			cursor = *response.GetArtifact().GetFiles().PageInfo.EndCursor
			fmt.Printf("\nFetchFileURLs ===> hasNextPage: %v, cursor: %v", hasNextPage, cursor)
			for _, edge := range response.GetArtifact().GetFiles().Edges {
				filePath := edge.GetNode().Name
				entry, err := getManifestEntryFromArtifactFilePath(manifestEntries, filePath)
				if err != nil {
					return err
				}
				entry.DownloadURL = &edge.GetNode().DirectUrl
				if _, ok := nameToScheduledTime[entry.Digest]; ok {
					continue
				}
				nameToScheduledTime[entry.Digest] = now
				manifestEntriesBatch = append(manifestEntriesBatch, entry)
			}
			if len(manifestEntriesBatch) > MAX_BACKLOG {
				break
			}
		}
		// Schedule downloads
		fmt.Printf("\nbatch: %v", manifestEntriesBatch)
		if len(manifestEntriesBatch) > 0 {
			for _, entry := range manifestEntriesBatch {
				name := entry.Digest
				fmt.Printf("\nentry: %v", entry)
				numInProgress++
				// Call function that returns download path?
				task := &filetransfer.DownloadTask{
					Path: filepath.Join(*ad.DownloadRoot, "abc"), // change
					Url:  *entry.DownloadURL,
					CompletionCallback: func(task *filetransfer.DownloadTask) {
						taskResultsChan <- TaskResult{task, name}
					},
					FileType: filetransfer.ArtifactFile,
				}
				ad.DownloadManager.AddTask(task)
			}
		}
		fmt.Printf("\nDebug schedule downloads ===> numInProgress: %d, numDone: %d", numInProgress, numDone)

		// Wait for downloader to catch up. If there's nothing more to schedule, wait for all in progress tasks.
		for numInProgress > MAX_BACKLOG || (len(manifestEntriesBatch) == 0 && numInProgress > 0) {
			fmt.Printf("\nInside catch up loop")
			numInProgress--
			result := <-taskResultsChan
			if result.Task.Err != nil {
				// We want to retry when the signed URL expires. However, distinguishing that error from others is not
				// trivial. As a heuristic, we retry if the request failed more than an hour after we fetched the URL.
				if time.Since(nameToScheduledTime[result.Name]) < 1*time.Hour {
					return result.Task.Err
				}
				// Todo: This might not work for downloads?
				delete(nameToScheduledTime, result.Name) // retry
				continue
			}
			numDone++
		}
		fmt.Printf("\n\nDONE. Debug schedule downloads ===> len_manifest: %d, numInProgress: %d, numDone: %d", len(manifestEntries), numInProgress, numDone)
	}

	return nil
}

func (ad *ArtifactDownloader) Download() (FileDownloadPath string, rerr error) {
	artifactAttrs, err := ad.getArtifact()
	if err != nil {
		return "", err
	}

	if ad.DownloadRoot == nil {
		err = ad.setDefaultDownloadRoot(artifactAttrs)
		if err != nil {
			return "", err
		}
	}
	if err := ad.ensureDownloadRootDir(); err != nil {
		return "", err
	}
	fmt.Printf("\n\n Download root ===> %v \n\n", *ad.DownloadRoot)

	artifactManifestEntries, err := ad.getArtifactManifestEntries()
	if err != nil {
		return "", err
	}
	fmt.Printf("\n\n manifest ===> %v \n\n", artifactManifestEntries)

	nFiles := len(artifactManifestEntries)
	fmt.Printf("\n\n manifest size ===> %v \n\n", nFiles)
	size := 0
	for _, file := range artifactManifestEntries {
		size += int(file.Size)
	}

	ad.downloadFiles(artifactAttrs.Id, artifactManifestEntries)
	// todo: ArtifactDownloadLogger
	// if nFiles > 5000 || size > 50*1024*1024 {
	// 	ad.logger.Info("downloadArtifact: downloading large artifact %s, %d MB, %d files", ad.QualifiedName, size/(1024*1024), nFiles)
	// }
	fmt.Printf("\n\nOutside download files ")
	return "", nil
}
