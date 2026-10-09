from bokeh.document import Document
from bokeh.plotting import figure
from wandb import data_types


def _line_plot():
    plot = figure()
    plot.line([0, 1], [0, 1])
    return plot


def test_bokeh_model_sets_media_file():
    media = data_types.Bokeh(_line_plot())
    assert media.file_is_set()


def test_bokeh_document_sets_media_file():
    doc = Document()
    doc.add_root(_line_plot())
    media = data_types.Bokeh(doc)
    assert media.file_is_set()
