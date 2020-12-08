from .media import Media


class Plotly(Media):
    """
        Wandb class for plotly plots.

        Arguments:
            val: matplotlib or plotly figure
    """

    @classmethod
    def make_plot_media(cls, val):
        if util.is_matplotlib_typename(util.get_full_typename(val)):
            if util.matplotlib_contains_images(val):
                return Image(val)
            val = util.matplotlib_to_plotly(val)
        return cls(val)

    def __init__(self, val, **kwargs):
        super(Plotly, self).__init__()
        # First, check to see if the incoming `val` object is a plotfly figure
        if not util.is_plotly_figure_typename(util.get_full_typename(val)):
            # If it is not, but it is a matplotlib figure, then attempt to convert it to plotly
            if util.is_matplotlib_typename(util.get_full_typename(val)):
                if util.matplotlib_contains_images(val):
                    raise ValueError(
                        "Plotly does not currently support converting matplotlib figures containing images. \
                            You can convert the plot to a static image with `wandb.Image(plt)` "
                    )
                val = util.matplotlib_to_plotly(val)
            else:
                raise ValueError(
                    "Logged plots must be plotly figures, or matplotlib plots convertible to plotly via mpl_to_plotly"
                )

        tmp_path = os.path.join(
            Media.MEDIA_TMP.name, util.generate_id() + ".plotly.json"
        )
        val = dt_util.numpy_arrays_to_lists(val.to_plotly_json())
        util.json_dump_safer(val, codecs.open(tmp_path, "w", encoding="utf-8"))
        self._set_file(tmp_path, is_tmp=True, extension=".plotly.json")

    def get_media_subdir(self):
        return os.path.join("media", "plotly")

    def to_json(self, run):
        json_dict = super(Plotly, self).to_json(run)
        json_dict["_type"] = "plotly-file"
        return json_dict
