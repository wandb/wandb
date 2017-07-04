from six import BytesIO
from wandb import Api
import base64
import csv
import tempfile
import os

def results(project=None, bucket=None):
    r = Results(project, bucket)
    try:
        yield r
    finally:
        r.close()

class Results(object):
    """Generates results to be compared in WandB

    with Results("project/bucket") as r:
        for truth, img_data in test_data:
            label, score = model.predict(img_data)
            img = array_to_img(img_data)
            r.write(input=r.encode_image(img), output=label, 
                truth=truth, score=score)
    """
    def __init__(self, project=None, bucket=None):
        self.api = Api()
        self.project = project or self.api.config("project")
        self.bucket = bucket or os.getenv("WANDB_BUCKET")
        self.tempfile = tempfile.NamedTemporaryFile(mode='w')
        self.csv = csv.writer(self.tempfile)
        self.csv.writerow(["input","output","probability","truth","loss"])
        self.rows = 0

    def __enter__(self):
        return self

    def __exit__(self, kind, value, extra):
        self.close()

    def encode_image(self, img, format="png"):
        """Accepts a PIL image and returns an encoded data uri"""
        buffer = BytesIO()
        img.save(buffer, format=format)
        return self.encode_data(buffer.getvalue(), format="image/%s" % format)

    def encode_data(self, data, format="image/png"):
        """Creates a data uri from raw data"""
        return "data:{format};base64,{img}".format(
            format=format,
            img=base64.b64encode(data).decode("UTF-8")
        )

    def write(self, **kwargs):
        self.rows += 1
        self.csv.writerow(
            [kwargs["input"], kwargs["output"], kwargs.get("probability"), 
                kwargs["truth"], kwargs["loss"]])

    def close(self):
        self.tempfile.flush()
        self.api.push(self.project, {'results.csv': open(self.tempfile.name, "rb")}, 
            bucket=self.bucket)
        self.tempfile.close()

        

