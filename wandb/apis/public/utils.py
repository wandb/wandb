import re
from urllib.parse import urlparse


def parse_s3_url_to_s3_uri(url) -> str:
    """Convert an S3 HTTP(S) URL to an S3 URI.

    Arguments:
        url (str): The S3 URL to convert, in the format
                   'http(s)://<bucket>.s3.<region>.amazonaws.com/<key>'.
                   or 'http(s)://<bucket>.s3.amazonaws.com/<key>'

    Returns:
        str: The corresponding S3 URI in the format 's3://<bucket>/<key>'.

    Raises:
        ValueError: If the provided URL is not a valid S3 URL.
    """
    # Regular expression to match S3 URL pattern
    s3_pattern = r"^https?://.*s3.*amazonaws\.com.*"
    parsed_url = urlparse(url)

    # Check if it's an S3 URL
    match = re.match(s3_pattern, parsed_url.geturl())
    if not match:
        raise ValueError("Invalid S3 URL")

    # Extract bucket name and key
    bucket_name, *_ = parsed_url.netloc.split(".")
    key = parsed_url.path.lstrip("/")

    # Construct the S3 URI
    s3_uri = f"s3://{bucket_name}/{key}"

    return s3_uri
