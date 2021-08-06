from io import BytesIO
from urllib.request import urlopen
from zipfile import ZipFile


url = "INSERT DATASET URL"
extract_dir = "prodigy_sample_datasets"

http_response = urlopen(url)
zipfile = ZipFile(BytesIO(http_response.read()))
zipfile.extractall(path=extract_dir)
