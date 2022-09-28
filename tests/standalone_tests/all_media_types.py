#!/usr/bin/env python

# Test logging media alone, in dicts, lists, and data frames.
# Add to both history and summary.

import matplotlib.pyplot as plt
import numpy
import pandas
import PIL
import plotly.graph_objs as go
import tensorflow
import torch
import wandb
from pkg_resources import parse_version


def dummy_torch_tensor(size, requires_grad=True):
    if parse_version(torch.__version__) >= parse_version("0.4"):
        return torch.ones(size, requires_grad=requires_grad)
    else:
        return torch.autograd.Variable(torch.ones(size), requires_grad=requires_grad)


def main():
    wandb.init()

    histogram_small_literal = wandb.Histogram(np_histogram=([1, 2, 4], [3, 10, 20, 0]))
    histogram_large_random = wandb.Histogram(numpy.random.randint(255, size=(1000)))
    numpy_array = numpy.random.rand(1000)
    torch_tensor = torch.rand(1000, 1000)
    data_frame = pandas.DataFrame(  # noqa: F841
        data=numpy.random.rand(1000), columns=["col"]
    )
    tensorflow_variable_single = tensorflow.Variable(543.01, tensorflow.float32)
    tensorflow_variable_multi = tensorflow.Variable([[2, 3], [7, 11]], tensorflow.int32)
    plot_scatter = go.Figure(  # plotly
        data=go.Scatter(x=[0, 1, 2]),
        layout=go.Layout(title=go.layout.Title(text="A Bar Chart")),
    )

    image_data = numpy.zeros((28, 28))
    image_cool = wandb.Image(image_data, caption="Cool zeros")
    image_nice = wandb.Image(image_data, caption="Nice zeros")
    image_random = wandb.Image(numpy.random.randint(255, size=(28, 28, 3)))
    image_pil = wandb.Image(PIL.Image.new("L", (28, 28)))
    plt.plot([1, 2, 3, 4])
    plt.ylabel("some interesting numbers")
    image_matplotlib_plot = wandb.Image(plt)
    # matplotlib_plot = plt

    audio_data = numpy.random.uniform(-1, 1, 44100)
    sample_rate = 44100
    caption1 = "This is what a dog sounds like"
    caption2 = "This is what a chicken sounds like"
    # test with all captions
    audio1 = wandb.Audio(audio_data, sample_rate=sample_rate, caption=caption1)
    audio2 = wandb.Audio(audio_data, sample_rate=sample_rate, caption=caption2)
    # test with no captions
    audio3 = wandb.Audio(audio_data, sample_rate=sample_rate)
    audio4 = wandb.Audio(audio_data, sample_rate=sample_rate)
    # test with some captions
    audio5 = wandb.Audio(audio_data, sample_rate=sample_rate)
    audio6 = wandb.Audio(audio_data, sample_rate=sample_rate, caption=caption2)

    html = wandb.Html("<html><body><h1>Hello</h1></body></html>")

    table_default_columns = wandb.Table()
    table_default_columns.add_data("Some awesome text", "Positive", "Negative")

    table_custom_columns = wandb.Table(["Foo", "Bar"])
    table_custom_columns.add_data("So", "Cool")
    table_custom_columns.add_data("&", "Rad")

    # plot_figure = matplotlib.pyplot.plt.figure()
    # c1 = matplotlib.pyplot.plt.Circle((0.2, 0.5), 0.2, color='r')
    # ax = matplotlib.pyplot.plt.gca()
    # ax.add_patch(c1)
    # matplotlib.pyplot.plt.axis('scaled')

    # pytorch model graph
    # alex = models.AlexNet()
    # graph = wandb.wandb_torch.TorchGraph.hook_torch(alex)
    # alex.forward(dummy_torch_tensor((2, 3, 224, 224)))

    with tensorflow.Session().as_default() as sess:
        sess.run(tensorflow.global_variables_initializer())

        wandb.run.summary.update(
            {
                "histogram-small-literal-summary": histogram_small_literal,
                "histogram-large-random-summary": histogram_large_random,
                "numpy-array-summary": numpy_array,
                "torch-tensor-summary": torch_tensor,
                # bare dataframes in summary and history removed in 0.10.21
                # 'data-frame-summary': data_frame,
                "image-cool-summary": image_cool,
                "image-nice-summary": image_nice,
                "image-random-summary": image_random,
                "image-pil-summary": image_pil,
                "image-plot-summary": image_matplotlib_plot,
                "image-list-summary": [image_cool, image_nice, image_random, image_pil],
                # Doesn't work, because something has happened to the MPL object (MPL may
                # be doing magical scope stuff). If you log it right after creating it,
                # it works fine.
                # "matplotlib-plot": matplotlib_plot,
                "audio1-summary": audio1,
                "audio2-summary": audio2,
                "audio3-summary": audio3,
                "audio4-summary": audio4,
                "audio5-summary": audio5,
                "audio6-summary": audio6,
                "audio-list-summary": [audio1, audio2, audio3, audio4, audio5, audio6],
                "html-summary": html,
                "table-default-columns-summary": table_default_columns,
                "table-custom-columns-summary": table_custom_columns,
                "plot-scatter-summary": plot_scatter,
                # "plot_figure": plot_figure,
                "tensorflow-variable-single-summary": tensorflow_variable_single,
                "tensorflow-variable-multi-summary": tensorflow_variable_multi,
                # "graph-summary": graph,
            }
        )

        for _ in range(10):
            wandb.run.log(
                {
                    "string": "string",
                    "histogram-small-literal": histogram_small_literal,
                    "histogram-large-random": histogram_large_random,
                    "numpy-array": numpy_array,
                    "torch-tensor": torch_tensor,
                    # "data-frame": data_frame,  # not supported yet
                    "image-cool": image_cool,
                    "image-nice": image_nice,
                    "image-random": image_random,
                    "image-pil": image_pil,
                    "image-plot": image_matplotlib_plot,
                    "image-list": [image_cool, image_nice, image_random, image_pil],
                    # "matplotlib-plot": matplotlib_plot,
                    "audio1": audio1,
                    "audio2": audio2,
                    "audio3": audio3,
                    "audio4": audio4,
                    "audio5": audio5,
                    "audio6": audio6,
                    "audio-list": [audio1, audio2, audio3, audio4, audio5, audio6],
                    "html": html,
                    "table-default-columns": table_default_columns,
                    "table-custom-columns": table_custom_columns,
                    "plot-scatter": plot_scatter,
                    # "plot_figure": plot_figure,
                    "tensorflow-variable-single": tensorflow_variable_single,
                    "tensorflow-variable-multi": tensorflow_variable_multi,
                    # "graph": graph,
                }
            )

        wandb.run.summary.update(
            {
                "histogram-small-literal-summary": histogram_small_literal,
                "histogram-large-random-summary": histogram_large_random,
                "numpy-array-summary": numpy_array,
                "torch-tensor-summary": torch_tensor,
                # bare dataframes in summary and history removed in 0.10.21
                # "data-frame-summary": data_frame,
                "image-cool-summary": image_cool,
                "image-nice-summary": image_nice,
                "image-random-summary": image_random,
                "image-pil-summary": image_pil,
                "image-plot-summary": image_matplotlib_plot,
                "image-list-summary": [image_cool, image_nice, image_random, image_pil],
                # "matplotlib-plot": matplotlib_plot,
                "audio1-summary": audio1,
                "audio2-summary": audio2,
                "audio3-summary": audio3,
                "audio4-summary": audio4,
                "audio5-summary": audio5,
                "audio6-summary": audio6,
                "audio-list-summary": [audio1, audio2, audio3, audio4, audio5, audio6],
                "html-summary": html,
                "table-default-columns-summary": table_default_columns,
                "table-custom-columns-summary": table_custom_columns,
                "plot-scatter-summary": plot_scatter,
                # "plot_figure": plot_figure,
                "tensorflow-variable-single-summary": tensorflow_variable_single,
                "tensorflow-variable-multi-summary": tensorflow_variable_multi,
                # "graph-summary": graph,
            }
        )

        # history.add({
        #    "tensorflow_variable_single": tensorflow_variable_single,
        #    "tensorflow_variable_multi": tensorflow_variable_single,
        # })


if __name__ == "__main__":
    main()
