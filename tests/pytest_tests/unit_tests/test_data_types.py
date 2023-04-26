import matplotlib.pyplot as plt
import numpy as np
import wandb


def subdict(d, expected_dict):
    """Return a new dict with only the items from `d` whose keys occur in `expected_dict`."""
    return {k: v for k, v in d.items() if k in expected_dict}


def matplotlib_multiple_axes_figures(total_plot_count=3, data=(1, 2, 3)):
    """Create a figure containing up to `total_plot_count` axes.

    Optionally adds `data` to each axes in a permutation-style loop.
    """
    for num_plots in range(1, total_plot_count + 1):
        for permutation in range(2**num_plots):
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
    """Create a matplotlib figure with an image."""
    fig, ax = plt.subplots(3)
    ax[0].plot([1, 2, 3])
    ax[1].imshow(np.random.rand(200, 200, 3))
    ax[2].plot([1, 2, 3])
    return fig


def matplotlib_without_image():
    """Create a matplotlib figure without an image."""
    fig, ax = plt.subplots(2)
    ax[0].plot([1, 2, 3])
    ax[1].plot([1, 2, 3])
    return fig


###############################################################################
# Test wandb.Histogram
###############################################################################


def test_raw_data():
    data = np.random.randint(255, size=(1000))

    wbhist = wandb.Histogram(data)
    assert len(wbhist.histogram) == 64
