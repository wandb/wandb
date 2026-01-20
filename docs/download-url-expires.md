# Download URL Expires

## Background

Downloading artifacts uses presigned URL, which can expire when

- Download is taking too long
- The issuer of presigned URL has a shorter expiration time

We can skip dealing with Go core's logic for now and focus on the Python side.
Right now, we downloading in `WandbStoragePolicy.load_file` there are two paths

- `multipart_download` is used when there is a download url, executor and size, ideally the executor is presented when `should_multipart_download` is true from callers
- `_session.get` path is used for small file and can fallback to using `_file_url` to get a new presigned URL when signed URL is expired.

Users having issue are using the multipart download path which does not have
fallback when the presigend URL expires.

Futhermore, there are some other issues from multipart download

- The retry (we set in requests session) seems to hang the error after the url expires (e.g. AWS returns 403 error)
- When downloading very large models e.g. Qwen3 235B of 470GB, the multipart download just hangs forever, there seems to be deadlock issue in the multipart download logic.

## Initial investigation

Go through the python download path and try to figure out:

- How can we support getting a new presigned URL when the first one expires
  - We might need to do it more than once if the download is long and the expiration time is short, e.g. total 1h download while the url expires every 10 minutes.
  - NOTE: One url can be shared by multiple threads by using different HTTP range headers
- Are there any potential issues in the multipart download logic that leads to hanging, deadlock

Write down you summary in a markdown doc `download-url-expires-investigation.claude.md`

## More investigation

- Are we setting timeout for http requests for downloading files (e.g. run files), graphql API calls anywhere/configurable in either python or go code for SDK
- Split the investigation into two parts, we might need separated pull requests for fixing them
  - handling expired url in multipart download
  - timeout/hanging issues in multipart download

## Initial implementation

Now base on the plan in [download-url-expires-investigation.claude.md](download-url-expires-investigation.claude.md), implement getting a new presigned URL when doing multipart download.

- Use `GET_ARTIFACT_MEMBERSHIP_FILES_GQL` to fetch new url
  - I think `GET_ARTIFACT_FILES_GQL` is legacy method base on `_file_url` checking server feature via `server_supports`
- Write tests, you can look at existing tests about http extra headers such as `test_artifact_download_http_headers`, they are using the response library to mock responses, which you can also check doc at https://github.com/getsentry/responses
  - The test first return 403 https://repost.aws/knowledge-center/request-has-expired-s3-object then passthrough to the actual backend so sdk can finish the actual download
