# Shared HTTP clients for artifacts and TensorBoard

The `cloud_http` Go build tag replaces the artifact transfer implementations for
S3, GCS, and Azure with narrow HTTP clients and shares them with TensorBoard's
cloud log reader. It retains the provider credential libraries. Default builds
continue to use the existing storage SDKs.

This is an experiment for measuring binary size and validating the smaller API
surface, not a replacement for every feature of the provider SDKs.

## Build and measure

From the repository root:

```sh
python3 core/scripts/measure-cloud-http-size.py --output-dir /tmp/cloud-http-size
```

The script builds both variants from the same source tree with Go's release
flags, CGO disabled, and the existing `disable_grpc_modules parquet_read_only`
tags. It reports executable bytes and writes `measurements.json`. The default
target is Linux amd64; `--goos darwin --goarch arm64` selects another target.
It does not change dependencies or the checkout.

CI reports two separate comparisons. The existing Nox check compares the
packaged default binary against main; it does not enable `cloud_http`, so this
experiment should not produce a large reduction in that check. A separate
CircleCI step runs the measurement script on the same revision with and without
`cloud_http`, prints both sizes and the savings, and uploads `measurements.json`.
Direct-build sizes can differ slightly from package sizes because packaging
embeds the commit SHA and may strip additional ELF metadata. CI also runs the
artifact and TensorBoard tests with the experimental build tag and race checks.

From `core`, build or test the experimental variant explicitly:

```sh
go build -mod=vendor -tags='disable_grpc_modules parquet_read_only cloud_http' \
  -ldflags='-s -w' -o /tmp/wandb-core-http cmd/wandb-core/main.go
go test -mod=vendor -tags='disable_grpc_modules parquet_read_only cloud_http' \
  ./internal/filetransfer ./internal/tensorboard ./pkg/artifacts
```

## Scope

| Provider | Storage implementation | Authentication retained |
| --- | --- | --- |
| S3 | Object GET, attributes, object/version XML listings, SigV4, response checksums | AWS config, credential providers/cache, signer |
| GCS | JSON metadata/listings, generation-pinned media/range GET, CRC32C and gzip handling | Google auth/ADC and authenticated HTTP transport |
| Azure | Blob properties, versioned/ranged GET, XML listings, SAS PUT/block uploads | Azure identity and azcore authentication/retry pipeline |

Ordinary S3/GCS artifact transfers already use backend-provided URLs. The new
Azure uploader also uses its already-authorized URL; it does not acquire local
credentials for that path. Cloud reference downloads continue to acquire and
refresh credentials locally through the existing provider libraries.

The experimental interfaces use W&B-owned object and page types, or an HTTP
transport, rather than exposing the storage SDK's generated types.

## Sharing the clients with TensorBoard

TensorBoard cloud log directories (`s3://`, `gs://`, and `az://`) now use the
same HTTP storage transports through `CloudReadBucket`: paginated prefix
listings and streaming reads starting at a byte offset. The existing Go CDK
cloud driver imports are compiled only in the default SDK build. Local event
files continue to use Go CDK's filesystem driver.

Event files can grow or be replaced while training runs. The TensorBoard reader
reopens cloud streams after EOF at the saved byte offset, observes the latest
object on each open, and retains incomplete event records until more bytes
arrive. GCS pins each individual stream to one generation. GCS and Azure gzip
offsets refer to decoded bytes, so reopening a gzip object streams from zero
and discards the decoded prefix. Azure uses HEAD before nonzero-offset reads
to distinguish gzip from plain objects. A checksum rewind reopens an HTTP
stream at the event's starting offset. Local file descriptors remain open
across EOF.

The adapters preserve the previous Go CDK key escaping, per-page ordering, and
bare-bucket environment configuration. S3 uses the AWS default config and
credentials. GCS uses ADC with the cloud-platform scope or the storage emulator.
Azure supports account key, SAS, connection strings, or default credentials,
including the existing account/domain/protocol/emulator/CDN environment options.
TensorBoard's existing path parser continues to determine the bucket and prefix;
it does not forward arbitrary URL query options to storage clients.

Verify that the full HTTP binary no longer imports the storage SDKs with:

```sh
go list -mod=vendor -tags=cloud_http -deps ./internal/filetransfer
go list -mod=vendor -tags=cloud_http -deps ./cmd/wandb-core
```

## Measured results

Measured with Go 1.27.1 targeting Linux amd64, CGO disabled, and the build flags
above. Each row compares SDK and HTTP builds of the same source tree, including
the build-tag split. Sizes are uncompressed executable bytes.

The final shared implementation preserves the three TensorBoard cloud paths:

| Dependency snapshot | SDK bytes | Shared HTTP bytes | Saved |
| --- | ---: | ---: | ---: |
| PR preparation on current main `d3119f18a2` (2026-09-22) | 51,953,927 | 35,496,199 | 16,457,728 bytes (15.70 MiB, 31.68%) |
| Starting checkout `8f93d444e2` | 46,952,711 | 35,496,199 | 11,456,512 bytes (10.93 MiB, 24.40%) |
| PR #12800 head `483358ac724012cf06a62cc3ecf8e46e532b3c2b` | 52,019,463 | 35,520,775 | 16,498,688 bytes (15.73 MiB, 31.72%) |

On current main, the binary drops from **49.55 MiB to 33.85 MiB**. The earlier
PR #12800 snapshot drops from **49.61 MiB to 33.88 MiB**. Dependency inspection
confirms that no AWS S3, Google Storage, Azure Blob, or Arrow packages remain
in the full executable's import graph. The default SDK build still imports
all three storage clients. The remaining difference between the two HTTP
dependency snapshots is 24 KiB, instead of the SDK builds' 4.83 MiB.

The first artifact-only implementation, before TensorBoard shared the clients,
produced these results:

| Dependency snapshot | SDK bytes | Artifact-only HTTP bytes | Saved |
| --- | ---: | ---: | ---: |
| Starting checkout `8f93d444e2` | 46,948,615 | 46,924,039 | 24 KiB (0.052%) |
| PR #12800 head `483358ac724012cf06a62cc3ecf8e46e532b3c2b` | 52,015,367 | 51,978,503 | 36 KiB (0.071%) |

For a diagnostic at that stage, removing TensorBoard's three cloud-driver
imports from the PR's HTTP build yielded **35,459,335 bytes (33.82 MiB)**: 15.79 MiB smaller
than the SDK build, or 31.83%. That build disables cloud TensorBoard and is not
part of this implementation. It demonstrates the code still retained through
TensorBoard, not the guaranteed savings from a compatible TensorBoard rewrite.

That small artifact-only saving was due to TensorBoard retaining the same
storage clients. With the shared implementation, the full executable's
dependency closure contains none of the three storage clients or Arrow.

Validation includes the file-transfer, TensorBoard and artifact package tests,
race checks, and package lint, as well as the default SDK path. Local protocol
servers exercise the complete TensorBoard path through each of S3, GCS, and
Azure, including partial appends and reads from nonzero offsets. Additional
tests cover credentials, pagination, file rotation, checksum rewinds, encoding,
retries, upload/download streams and injected failures. Live cloud integration
coverage remains outstanding.

## Compatibility limits

- S3 supports ordinary regional/configured endpoints, path-style fallback,
  FIPS and dual-stack configuration. ARN, Express directory, Object Lambda and
  multi-region access-point buckets are rejected. The custom resolver does not
  reproduce all generated SDK endpoint rules. Retry limits and credential
  refresh are retained, but adaptive rate limiting and clock-skew correction
  are not. Supported full-object response checksums are checked; composite
  multipart checksums are skipped as in the SDK.
- GCS supports the default Google universe and an unauthenticated storage
  emulator. Alternate universes and mTLS endpoint modes fail explicitly before
  requests are sent. Concurrent object downloads are capped at 32 instead of
  the SDK-backed implementation's 1,000. Stream resumes are bounded at five
  attempts, separately from per-request retries. Downloads use a temporary file
  and atomic replacement of the destination.
- Azure uses REST version `2023-11-03` and XML listings. Uploads use at most four
  1 MiB buffers; downloads use four concurrent ranges with ETag conditions and
  interrupted-body recovery. Truncation inside an XML listing returns an error
  rather than replaying the whole listing. Successful uploads return the real
  HTTP status, normally 201, instead of the old wrapper's synthetic 200.
- Reference-task cancellation and other existing outer transfer-manager
  behavior are unchanged. Tests use local or injected transports; they do not
  establish live-service or every credential-provider configuration parity.

Keep this opt-in until the remaining endpoint/retry behavior and live integration
coverage are resolved. The default SDK implementations and their original tests
remain available under `!cloud_http`.
