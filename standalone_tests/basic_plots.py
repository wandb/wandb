import math
import random

import wandb

wandb.init(entity='wandb', project='new-plots-test-5')
data = [[i, random.random() + math.sin(i / 10)] for i in range(100)]
table = wandb.Table(data=data, columns=["step", "height"])
line_plot = wandb.plot.line(table, x='step', y='height', title='what a great line plot')

x = [i for i in range(1,100)]
ys = {
        "y1": [random.random() + math.sin(i / 10) for i in range(1,100)],
        "y2": [math.sin(i / 10) for i in range(1,100)],
        "y3": [math.cos(i / 10) for i in range(1,100)],
        "y4": [random.random() - math.cos(i / 10) for i in range(1,100)]
    }
line_series_plot = wandb.plot.line_series(x, ys, "Get serial now!", "step")

histogram = wandb.plot.histogram(table, value='height', title='my-histo')
scatter = wandb.plot.scatter(table, x='step', y='height', title='scatter!')

bar_table = wandb.Table(data=[
    ['car', random.random()],
    ['bus', random.random()],
    ['road', random.random()],
    ['person', random.random()],
    ['cyclist', random.random()],
    ['tree', random.random()],
    ['sky', random.random()]
    ], columns=["class", "acc"])
bar = wandb.plot.bar(bar_table, label='class', value='acc', title='bar')

wandb.log({
    'line1': line_plot,
    'line_series1': line_series_plot,
    'histogram1': histogram,
    'scatter1': scatter,
    'bar1': bar})
