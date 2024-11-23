package filetransfer

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/blob"
	"github.com/Azure/azure-sdk-for-go/sdk/storage/azblob/container"
	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/sync/errgroup"
)

const (
	maxAzureWorkers = 500
	// Azure blob storage urls have the following format:
	// https://<storage-account-name>.blob.core.windows.net/<container-name>/<blob-name>
	azureScheme = "https"
)

type AzureBlobClient interface {
	DownloadFile(ctx context.Context, destination *os.File, options *blob.DownloadFileOptions) (int64, error)
	GetProperties(ctx context.Context, options *blob.GetPropertiesOptions) (blob.GetPropertiesResponse, error)
	WithVersionID(versionId string) (*blob.Client, error)
}

type AzureAccountClient interface {
	DownloadFile(ctx context.Context, containerName string, blobName string, destination *os.File, options *azblob.DownloadFileOptions) (int64, error)
	NewListBlobsFlatPager(containerName string, options *azblob.ListBlobsFlatOptions) *runtime.Pager[azblob.ListBlobsFlatResponse]
}

// AzureClientsMap is a map of account URLs/container names to client objects.
// Azure clients exist at both the container and account level and support different
// blob operations, so we store clients only when necessary and reuse them.
type AzureClientsMap[T any] struct {
	// clients is a map of account URLs/container names to client objects
	clients sync.Map

	// once is a map of account URLs/container names to sync.Once objects to
	// ensure that we only set up each client once
	once sync.Map
}

func NewAzureClientsMap[T any]() *AzureClientsMap[T] {
	return &AzureClientsMap[T]{clients: sync.Map{}, once: sync.Map{}}
}

func (am *AzureClientsMap[T]) GetClient(key string) (T, error) {
	var zero T
	client, ok := am.clients.Load(key)
	if !ok {
		return zero, fmt.Errorf("client not found")
	}
	accountClient, ok := client.(T)
	if !ok {
		return zero, fmt.Errorf("client is not an account client")
	}
	return accountClient, nil
}

func setupAccountClient(
	accountUrl string,
	cred *azidentity.DefaultAzureCredential,
) (AzureAccountClient, error) {
	return azblob.NewClient(accountUrl, cred, nil)
}

func setupContainerClient(
	containerName string,
	cred *azidentity.DefaultAzureCredential,
) (*container.Client, error) {
	return container.NewClient(containerName, cred, nil)
}

func (am *AzureClientsMap[T]) LoadOrStore(
	key string,
	setup func(key string, cred *azidentity.DefaultAzureCredential) (T, error),
) (T, error) {
	onceVal, _ := am.once.LoadOrStore(key, &sync.Once{})
	once := onceVal.(*sync.Once)
	var err error
	once.Do(func() {
		var cred *azidentity.DefaultAzureCredential
		cred, err = azidentity.NewDefaultAzureCredential(nil)
		if err != nil {
			return
		}
		var client T
		client, err = setup(key, cred)
		if err != nil {
			return
		}
		am.clients.Store(key, client)
	})
	if err != nil {
		var zero T
		return zero, err
	}
	return am.GetClient(key)
}

// AzureFileTransfer uploads or downloads files to/from Azure.
type AzureFileTransfer struct {
	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context

	// clients is a map of account URLs to azblob.Client objects
	clients *AzureClientsMap[AzureAccountClient]

	// containerClients is a map of container names to container.Client objects
	containerClients *AzureClientsMap[*container.Client]

	// blobClient is a client for a specific blob
	blobClient AzureBlobClient
}

// NewAzureFileTransfer creates a new fileTransfer.
func NewAzureFileTransfer(
	clients *AzureClientsMap[AzureAccountClient],
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
	blobClient AzureBlobClient,
) *AzureFileTransfer {
	ctx := context.Background()
	if clients == nil {
		clients = NewAzureClientsMap[AzureAccountClient]()
	}
	return &AzureFileTransfer{
		logger:            logger,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
		clients:           clients,
		containerClients:  NewAzureClientsMap[*container.Client](),
		blobClient:        blobClient,
	}
}

// setupBlobClient sets up a client for a specific blob.
func setupBlobClient(
	task *ReferenceArtifactDownloadTask,
) (AzureBlobClient, error) {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		return nil, err
	}
	client, err := blob.NewClient(task.Reference, cred, nil)
	if err != nil {
		return nil, err
	}
	versionId, ok := task.VersionIDString()
	if ok {
		client, err = client.WithVersionID(versionId)
		if err != nil {
			return nil, err
		}
	}
	return client, nil
}

// Upload uploads a file to the server. This method is not yet implemented, but
// is required for the FileTransfer interface.
func (ft *AzureFileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("Azure file transfer: uploading file", "path", task.PathOrPrefix)

	return nil
}

type ParsedBlobInfo struct {
	AccountUrl string
	Container  string
	BlobPrefix string
}

// Download downloads a file from the server.
func (ft *AzureFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug(
		"Azure file transfer: downloading file",
		"path", task.PathOrPrefix,
		"ref", task.Reference,
	)

	// Parse the reference path to get the account URL and blob path
	accountUrl, fullBlobPath, err := parseCloudReference(task.Reference, azureScheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}
	pathSplit := strings.SplitN(fullBlobPath, "/", 2)
	fullAccountUrl := fmt.Sprintf("%s://%s", azureScheme, accountUrl)
	blobInfo := ParsedBlobInfo{
		AccountUrl: fullAccountUrl,
		Container:  pathSplit[0],
		BlobPrefix: pathSplit[1],
	}

	// Setup the client if it is not already set up
	_, err = ft.clients.LoadOrStore(fullAccountUrl, setupAccountClient)
	if err != nil {
		return ft.formatDownloadError(
			"error setting up Azure account client",
			fmt.Errorf("client not found"),
		)
	}

	var blobNames []string
	if task.HasSingleFile() {
		blobName, versionId, err := ft.getBlob(blobInfo, task)
		if err != nil {
			return ft.formatDownloadError(
				"error getting correct blob name and version",
				err,
			)
		}
		if versionId != "" {
			err = task.SetVersionID(versionId)
			if err != nil {
				return ft.formatDownloadError(
					"error setting version ID",
					err,
				)
			}
		}
		blobNames = []string{blobName}
	} else {
		blobNames, err = ft.listBlobsWithPrefix(blobInfo)
		if err != nil {
			return ft.formatDownloadError(
				fmt.Sprintf("error finding blobs with prefix %s", blobInfo.BlobPrefix),
				err,
			)
		}
	}

	err = ft.downloadFiles(blobInfo, blobNames, task)
	if err != nil {
		return ft.formatDownloadError(
			fmt.Sprintf("error downloading reference %s", task.Reference),
			err,
		)
	}
	return nil
}

// getBlob tries to get the blob name and version ID that matches the
// expected digest for the given task.
func (ft *AzureFileTransfer) getBlob(
	blobInfo ParsedBlobInfo,
	task *ReferenceArtifactDownloadTask,
) (string, string, error) {
	blobClient := ft.blobClient
	if ft.blobClient == nil {
		client, err := setupBlobClient(task)
		if err != nil {
			return "", "", err
		}
		blobClient = client
	}
	matches, err := ft.checkVersionIDMatches(blobClient, task.Digest)
	if err != nil {
		return "", "", err
	}

	if matches {
		return blobInfo.BlobPrefix, "", nil
	}

	// If the version ID is specified but the etag does not match, return an error
	if task.VersionId != nil {
		return "", "", fmt.Errorf(
			"digest/etag mismatch: etag does not match expected digest %s",
			task.Digest,
		)
	}

	// Otherwise, find the correct blob version
	blobName, versionId, err := ft.getCorrectBlobVersion(blobInfo, task)
	if err != nil {
		return "", "", err
	}
	return blobName, versionId, nil
}

// getCorrectBlobVersion finds the correct blob version that matches the
// expected digest.
func (ft *AzureFileTransfer) getCorrectBlobVersion(
	blobInfo ParsedBlobInfo,
	task *ReferenceArtifactDownloadTask,
) (string, string, error) {
	containerUrl := fmt.Sprintf("%s/%s", blobInfo.AccountUrl, blobInfo.Container)
	containerClient, err := ft.containerClients.LoadOrStore(containerUrl, setupContainerClient)
	if err != nil {
		return "", "", err
	}

	// Get all of the possible versions of the blob to check the digest against
	pager := containerClient.NewListBlobsFlatPager(&container.ListBlobsFlatOptions{
		Prefix: &blobInfo.BlobPrefix,
		Include: container.ListBlobsInclude{
			Versions: true,
		},
	})

	for pager.More() {
		resp, err := pager.NextPage(ft.ctx)
		if err != nil {
			return "", "", err
		}

		for _, blob := range resp.Segment.BlobItems {
			blobClient, err := containerClient.NewBlobClient(*blob.Name).
				WithVersionID(*blob.VersionID)
			if err != nil {
				return "", "", err
			}
			matches, err := ft.checkVersionIDMatches(blobClient, task.Digest)
			if err != nil {
				return "", "", err
			}
			if matches {
				return *blob.Name, *blob.VersionID, nil
			}
		}
	}
	return "", "", fmt.Errorf(
		"digest/etag mismatch: unable to find version with expected digest %s for reference %s",
		task.Digest,
		task.Reference,
	)
}

// checkVersionIDMatches checks if the etag of the given blob matches the expected digest.
func (ft *AzureFileTransfer) checkVersionIDMatches(
	client AzureBlobClient,
	digest string,
) (bool, error) {
	properties, err := client.GetProperties(ft.ctx, nil)
	if err != nil {
		return false, err
	}
	if properties.ETag != nil &&
		strings.Trim(string(*properties.ETag), "\"") == digest {
		return true, nil
	}
	return false, nil
}

// listBlobsWithPrefix lists all the blobs in the container with the given prefix.
func (ft *AzureFileTransfer) listBlobsWithPrefix(
	blobInfo ParsedBlobInfo,
) ([]string, error) {
	client, err := ft.clients.GetClient(blobInfo.AccountUrl)
	if err != nil {
		return nil, err
	}

	// List the blobs in the container
	pager := client.NewListBlobsFlatPager(
		blobInfo.Container,
		&azblob.ListBlobsFlatOptions{
			Prefix: &blobInfo.BlobPrefix,
		},
	)

	blobNames := []string{}
	for pager.More() {
		resp, err := pager.NextPage(ft.ctx)
		if err != nil {
			return nil, err
		}

		for _, blob := range resp.Segment.BlobItems {
			blobNames = append(blobNames, *blob.Name)
		}
	}

	return blobNames, nil
}

// downloadFiles downloads all of the blobs with the given names.
func (ft *AzureFileTransfer) downloadFiles(
	blobInfo ParsedBlobInfo,
	blobNames []string,
	task *ReferenceArtifactDownloadTask,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxAzureWorkers)
	for _, blobName := range blobNames {
		g.Go(func() error {
			objectRelativePath, _ := strings.CutPrefix(blobName, blobInfo.BlobPrefix)
			localPath := filepath.Join(task.PathOrPrefix, filepath.FromSlash(objectRelativePath))
			return ft.downloadBlobToFile(blobInfo, blobName, task, localPath)
		})
	}

	return g.Wait()
}

// downloadBlobToFile downloads a blob to a file at the given local path.
func (ft *AzureFileTransfer) downloadBlobToFile(
	blobInfo ParsedBlobInfo,
	blobName string,
	task *ReferenceArtifactDownloadTask,
	localPath string,
) error {
	// Create or open a local file where we can download the blob
	if err := os.MkdirAll(filepath.Dir(localPath), 0755); err != nil {
		return fmt.Errorf(
			"unable to create destination directory %s: %w",
			filepath.Dir(localPath),
			err,
		)
	}

	destination, err := os.Create(localPath)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", localPath, err)
	}

	// If version ID is specified, use the blob client to download the blob
	_, ok := task.VersionIDString()
	if ok {
		blobClient := ft.blobClient
		if blobClient == nil {
			client, err := setupBlobClient(task)
			if err != nil {
				return err
			}
			blobClient = client
		}
		_, err = blobClient.DownloadFile(ft.ctx, destination, nil)
		return err
	} else {
		client, err := ft.clients.GetClient(blobInfo.AccountUrl)
		if err != nil {
			return err
		}
		_, err = client.DownloadFile(ft.ctx, blobInfo.Container, blobName, destination, nil)
		return err
	}
}

func (ft *AzureFileTransfer) formatDownloadError(message string, err error) error {
	return fmt.Errorf("AzureFileTransfer: Download: %s: %w", message, err)
}
