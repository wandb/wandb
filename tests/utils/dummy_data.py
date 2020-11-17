import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def matplotlib_multiple_axes_figures(total_plot_count=3, data=[1, 2, 3]):
    """Helper generator which  create a figure containing up to `total_plot_count` 
    axes and optionally adds `data` to each axes in a permutation-style loop.
    """
    for num_plots in range(1, total_plot_count + 1):
        for permutation in range(2 ** num_plots):
            has_data = [permutation & (1 << i) > 0 for i in range(num_plots)]
            fig, ax = plt.subplots(num_plots)
            if num_plots == 1:
                if has_data[0]:
                    ax.plot(data)
            else:
                for plot_id in range(num_plots):
                    if has_data[plot_id]:
                        ax[plot_id].plot(data)
            yield fig
            plt.close()


def matplotlib_with_image():
    """Creates a matplotlib figure with an image
    """
    fig, ax = plt.subplots(3)
    ax[0].plot([1, 2, 3])
    ax[1].imshow(np.random.rand(200, 200, 3))
    ax[2].plot([1, 2, 3])
    return fig


def matplotlib_without_image():
    """Creates a matplotlib figure without an image
    """
    fig, ax = plt.subplots(2)
    ax[0].plot([1, 2, 3])
    ax[1].plot([1, 2, 3])
    return fig
