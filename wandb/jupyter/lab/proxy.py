import tornado.gen
import tornado.web
import tornado.websocket
import tornado.httpclient
from notebook.base.handlers import IPythonHandler


class ProxyHandler(IPythonHandler):
    def initialize(self, **kwargs):
        super(ProxyHandler, self).initialize(**kwargs)

    @tornado.gen.coroutine
    def get(self, *args):
        '''Get the lpage'''
        path = self.get_argument('path')
        req = tornado.httpclient.HTTPRequest(path)
        client = tornado.httpclient.AsyncHTTPClient()
        ret = yield client.fetch(req, raise_error=False)
        if ret.body:
            self.write(ret.body)
        self.finish()


class ProxyWSHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, **kwargs):
        super(ProxyWSHandler, self).initialize(**kwargs)
        self.ws = None
        self.closed = False

    @tornado.gen.coroutine
    def open(self, *args):
        path = self.get_argument('path')

        def write(msg):
            if self.closed:
                if self.ws:
                    self.ws.close()
            else:
                self.write_message(msg)

        self.ws = yield tornado.websocket.websocket_connect(path,
                                                            on_message_callback=write)

    def on_message(self, message):
        if self.ws:
            self.ws.write_message(message)

    def on_close(self):
        if self.ws:
            self.ws.close()
            self.ws = None
            self.closed = True
