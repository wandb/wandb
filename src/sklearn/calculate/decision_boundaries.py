from warnings import simplefilter

import wandb

# ignore all future warnings
simplefilter(action="ignore", category=FutureWarning)


def decision_boundaries(
    decision_boundary_x,
    decision_boundary_y,
    decision_boundary_color,
    train_x,
    train_y,
    train_color,
    test_x,
    test_y,
    test_color,
):
    x_dict, y_dict, color_dict = [], [], []
    for i in range(min(len(decision_boundary_x), 100)):
        x_dict.append(decision_boundary_x[i])
        y_dict.append(decision_boundary_y[i])
        color_dict.append(decision_boundary_color)
    for i in range(300):
        x_dict.append(test_x[i])
        y_dict.append(test_y[i])
        color_dict.append(test_color[i])
    for i in range(min(len(train_x), 600)):
        x_dict.append(train_x[i])
        y_dict.append(train_y[i])
        color_dict.append(train_color[i])

    return wandb.visualize(
        "wandb/decision_boundaries/v1",
        wandb.Table(
            columns=["x", "y", "color"],
            data=[[x_dict[i], y_dict[i], color_dict[i]] for i in range(len(x_dict))],
        ),
    )
