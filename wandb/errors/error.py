class Error(Exception):
    """Base W&B Error"""

    def __init__(self, message):
        super(Error, self).__init__(message)
        self.message = message

    # For python 2 support
    def encode(self, encoding):
        return self.message

