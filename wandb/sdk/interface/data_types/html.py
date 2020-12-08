from .media import BatchableMedia


class Html(BatchableMedia):
    """
        Wandb class for arbitrary html

        Arguments:
            data (string or io object): HTML to display in wandb
            inject (boolean): Add a stylesheet to the HTML object.  If set
                to False the HTML will pass through unchanged.
    """

    def __init__(self, data, inject=True):
        super(Html, self).__init__()

        if isinstance(data, str):
            self.html = data
        elif hasattr(data, "read"):
            if hasattr(data, "seek"):
                data.seek(0)
            self.html = data.read()
        else:
            raise ValueError("data must be a string or an io object")
        if inject:
            self.inject_head()

        tmp_path = os.path.join(Media.MEDIA_TMP.name, util.generate_id() + ".html")
        with open(tmp_path, "w") as out:
            print(self.html, file=out)

        self._set_file(tmp_path, is_tmp=True)

    def inject_head(self):
        join = ""
        if "<head>" in self.html:
            parts = self.html.split("<head>", 1)
            parts[0] = parts[0] + "<head>"
        elif "<html>" in self.html:
            parts = self.html.split("<html>", 1)
            parts[0] = parts[0] + "<html><head>"
            parts[1] = "</head>" + parts[1]
        else:
            parts = ["", self.html]
        parts.insert(
            1,
            '<base target="_blank"><link rel="stylesheet" type="text/css" href="https://app.wandb.ai/normalize.css" />',
        )
        self.html = join.join(parts).strip()

    @classmethod
    def get_media_subdir(self):
        return os.path.join("media", "html")

    def to_json(self, run):
        json_dict = super(Html, self).to_json(run)
        json_dict["_type"] = "html-file"
        return json_dict

    @classmethod
    def seq_to_json(cls, html_list, run, key, step):
        base_path = os.path.join(run.dir, cls.get_media_subdir())
        util.mkdir_exists_ok(base_path)

        meta = {
            "_type": "html",
            "count": len(html_list),
            "html": [h.to_json(run) for h in html_list],
        }
        return meta
