class HTTPTransport(object):

    def __init__(self, url, headers=None, cookies=None):
        self.url = url
        self.headers = headers
        self.cookies = cookies
