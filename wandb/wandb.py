# -*- coding: utf-8 -*-

import os
import glob
import tarfile
import requests

class Packager(object):
    """Packager manages tar, gzip, and resumable uploads

    Attributes:
        name: The name of the model
        max_attempts: The maximum number of times to retry the upload
    """

    def __init__(self, name, max_attempts=10):
        self.path = "/tmp/%s.tar.gz" % name
        self.max_attempts = max_attempts
        self.attempts = 0

    def content_length(self):
        os.path.getsize(self.path)
    
    def package(self, source_dir):
        tar = tarfile.open(self.path, "w:gz")
        for file_name in glob.glob(os.path.join(source_dir, "*")):
            print("  Adding %s..." % file_name)
            tar.add(file_name, os.path.basename(file_name))
        tar.close()

    @property
    def upload_url(self):
        if(self._upload_url is None):
            api


    def status_request(self):
        return requests.put(
            url=self.upload_url,
            headers={'Content-Length': 0, 'Content-Range': 'bytes */%i' % self.content_length()}
        )

    def upload_request(self, extra_headers={}):
        headers = {'Content-Type': 'application/gzip'}
        return requests.put(
            url=self.upload_url,
            data=open(self.path),
            headers=headers.update(extra_headers)
        )
    
    def upload(self):
        extra_headers = {}
        while(self.attempts < self.max_attempts):
            try:
                res = this.upload_request(extra_headers)
                res.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                status = self.status_request
                if(status.status_code == 308):
                    self.attempts += 1
                    range = int(status.headers['Range'].split("-")[-1])
                    extra_headers = {
                        'Content-Range': 'bytes %i-%i/%i' % (range,this.content_length(), this.content_length()),
                        'Content-Length': this.content_length() - range
                    }
                else:
                    break
        return res