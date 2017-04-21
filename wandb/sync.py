import psutil, os, stat, sys, time
from tempfile import NamedTemporaryFile
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

class Sync(object):
    def __init__(self, api, project, bucket="default"):
        self._proc = psutil.Process(os.getpid())
        self._api = api
        self._project = project
        self._bucket = bucket
        self._handler = PatternMatchingEventHandler()
        self._handler.on_created = self.add
        self._handler.on_modified = self.push
        self._observer = Observer()
        self._observer.schedule(self._handler, os.path.abspath("."), recursive=False)

    def watch(self, files=[]):
        if len(files) > 0:
            self._handler._patterns = [os.path.abspath(file) for file in files]
        #TODO: upsert command line
        self._observer.start()
        print("Watching changes for {project}/{bucket}".format(
            project=self._project,
            bucket=self._bucket
        ))
        output = NamedTemporaryFile()
        try:
            if self.source_proc:
                output.write(" ".join(self.source_proc.cmdline()))
                line = sys.stdin.readline()
                while line:
                    output.write(line)
                    #TODO: push log every few minutes...
                    line = sys.stdin.readline()
                #Wait for changes
                time.sleep(0.1)
                output.flush()
                print("Pushing log")
                self._api.push(self._project, {"training.log": open(output.name, "rb")}, bucket=self._bucket)
            else:
                time.sleep(1.0)
            output.close()
            self._observer.stop()
        except KeyboardInterrupt:
            self._observer.stop()
        self._observer.join()

    def add(self, event):
        self.push(event)

    def push(self, event):
        fileName = event.src_path.split("/")[-1]
        print("Pushing {file}".format(file=fileName))
        self._api.push(self._project, [fileName], bucket=self._bucket)

    @property
    def source_proc(self):
        mode = os.fstat(0).st_mode
        if not stat.S_ISFIFO(mode):
            # stdin is not a pipe
            return None
        else:
            source = self._proc.parent().children()[0]
            return None if source == self._proc else source

    def echo(self):
        print(sys.stdin.read())
