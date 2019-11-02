
from wandb import util, Image, Error, termwarn

# assums X represents images and y_true/y_pred are logits for each class
def image_categorizer_dataframe(x, y_true, y_pred, labels, example_ids=None):
    np = util.get_module('numpy', required='dataframes require numpy')
    pd = util.get_module('pandas', required='dataframes require pandas')

    x, y_true, y_pred, labels = np.array(x), np.array(y_true), np.array(y_pred), np.array(labels)

    # If there is only one output value of true_prob, convert to 2 class false_prob, true_prob
    if y_true[0].shape[-1] == 1 and y_pred[0].shape[-1] == 1:
        y_true = np.concatenate((1-y_true, y_true), axis=-1)
        y_pred = np.concatenate((1-y_pred, y_pred), axis=-1)

    if x.shape[0] != y_true.shape[0]:
        termwarn('Sample count mismatch: x(%d) != y_true(%d). skipping evaluation' % (x.shape[0], y_true.shape[0]))
        return
    if x.shape[0] != y_pred.shape[0]:
        termwarn('Sample count mismatch: x(%d) != y_pred(%d). skipping evaluation' % (x.shape[0], y_pred.shape[0]))
        return
    if y_true.shape[-1] != len(labels):
        termwarn('Label count mismatch: y_true(%d) != labels(%d). skipping evaluation' % (y_true.shape[-1], len(labels)))
        return
    if y_pred.shape[-1] != len(labels):
        termwarn('Label count mismatch: y_pred(%d) != labels(%d). skipping evaluation' % (y_pred.shape[-1], len(labels)))
        return

    class_preds = []
    for i in range(len(labels)):
        class_preds.append(y_pred[:,i])

    images = [Image(img) for img in x]
    true_class = labels[y_true.argmax(axis=-1)]
    true_prob = y_pred[np.arange(y_pred.shape[0]), y_true.argmax(axis=-1)]
    pred_class = labels[y_pred.argmax(axis=-1)]
    pred_prob = y_pred[np.arange(y_pred.shape[0]), y_pred.argmax(axis=-1)]
    correct = true_class == pred_class

    if example_ids is None:
        example_ids = ['example_' + str(i) for i in range(len(x))]

    dfMap = {
        'wandb_example_id': example_ids,
        'image': images,
        'true_class': true_class,
        'true_prob': true_prob,
        'pred_class': pred_class,
        'pred_prob': pred_prob,
        'correct': correct,
    }

    for i in range(len(labels)):
        dfMap['prob_{}'.format(labels[i])] = class_preds[i]

    all_columns = [
        'wandb_example_id',
        'image',
        'true_class',
        'true_prob',
        'pred_class',
        'pred_prob',
        'correct',
    ] + ['prob_{}'.format(l) for l in labels]

    return pd.DataFrame(dfMap, columns=all_columns)

def image_segmentation_dataframe(x, y_true, y_pred, labels=None, example_ids=None, class_colors=None):
    np = util.get_module('numpy', required='dataframes require numpy')
    y_pred = np.array(y_pred)
    if y_pred[0].shape[-1] == 1:
        return image_segmentation_binary_dataframe(x, y_true, y_pred, example_ids=example_ids)
    else:
        return image_segmentation_multiclass_dataframe(x, y_true, y_pred, labels=labels, example_ids=example_ids, class_colors=class_colors)

def image_segmentation_binary_dataframe(x, y_true, y_pred, example_ids=None):
    np = util.get_module('numpy', required='dataframes require numpy')
    pd = util.get_module('pandas', required='dataframes require pandas')

    x, y_true, y_pred= np.array(x), np.array(y_true), np.array(y_pred)

    if x.shape[0] != y_true.shape[0]:
        termwarn('Sample count mismatch: x(%d) != y_true(%d). skipping evaluation' % (x.shape[0], y_true.shape[0]))
        return
    if x.shape[0] != y_pred.shape[0]:
        termwarn('Sample count mismatch: x(%d) != y_pred(%d). skipping evaluation' % (x.shape[0], y_pred.shape[0]))
        return

    y_pred_discrete = y_pred > 0.5

    images = [Image(img) for img in x]
    labels = [Image(mask) for mask in y_true]
    predictions = [Image(mask) for mask in y_pred]
    predictions_discrete = [Image(mask) for mask in y_pred_discrete]

    intersection = np.logical_and(y_pred_discrete, y_true)
    union = np.logical_or(y_pred_discrete, y_true)
    difference = np.logical_xor(y_pred_discrete, y_true)

    flat_shape = (x.shape[0], -1)

    accuracy = np.mean(np.equal(y_true, y_pred_discrete).reshape(flat_shape), axis=1)
    iou = np.sum(intersection.reshape(flat_shape), axis=1) / (np.sum(union.reshape(flat_shape), axis=1) + 1e-9)

    incorrect_predictions = [Image(mask) for mask in difference]

    if example_ids is None:
        example_ids = ['example_' + str(i) for i in range(len(x))]

    dfMap = {
        'wandb_example_id': example_ids,
        'image': images,
        'label': labels,
        'prediction': predictions,
        'prediction_discrete': predictions_discrete,
        'incorrect_prediction': incorrect_predictions,
        'accuracy': accuracy,
        'iou': iou,
    }

    all_columns = [
        'wandb_example_id',
        'image',
        'label',
        'prediction',
        'prediction_discrete',
        'incorrect_prediction',
        'accuracy',
        'iou',
    ]

    return pd.DataFrame(dfMap, columns=all_columns)

def image_segmentation_multiclass_dataframe(x, y_true, y_pred, labels, example_ids=None, class_colors=None):
    np = util.get_module('numpy', required='dataframes require numpy')
    pd = util.get_module('pandas', required='dataframes require pandas')

    x, y_true, y_pred= np.array(x), np.array(y_true), np.array(y_pred)

    if x.shape[0] != y_true.shape[0]:
        termwarn('Sample count mismatch: x(%d) != y_true(%d). skipping evaluation' % (x.shape[0], y_true.shape[0]))
        return
    if x.shape[0] != y_pred.shape[0]:
        termwarn('Sample count mismatch: x(%d) != y_pred(%d). skipping evaluation' % (x.shape[0], y_pred.shape[0]))
        return
    if class_colors is not None and len(class_colors) != y_true.shape[-1]:
        termwarn('Class color count mismatch: y_true(%d) != class_colors(%d). using generated colors' % (y_true.shape[-1], len(class_colors)))
        class_colors = None

    class_count = y_true.shape[-1]

    if class_colors is None:
        class_colors = util.class_colors(class_count)
    class_colors = np.array(class_colors)

    y_true_class = np.argmax(y_true, axis=-1)
    y_pred_class = np.argmax(y_pred, axis=-1)

    y_pred_discrete = np.round(y_pred)

    images = [Image(img) for img in x]
    label_imgs = [Image(mask) for mask in class_colors[y_true_class]]
    predictions = [Image(mask) for mask in class_colors[y_pred_class]]

    flat_shape = (x.shape[0], -1)

    intersection = np.sum(np.logical_and(y_true, y_pred_discrete).reshape(flat_shape), axis=1)
    union = np.sum(np.logical_or(y_true, y_pred_discrete).reshape(flat_shape), axis=1)

    iou = intersection / (union + 1e-9)
    accuracy = np.mean(np.equal(y_true_class, y_pred_class).reshape(flat_shape), axis=1)

    difference = np.zeros(y_true_class.shape)
    difference[y_true_class != y_pred_class] = 1.

    incorrect_predictions = [Image(mask) for mask in difference]

    iou_class = [
        np.sum(np.logical_and(y_true_class == i, y_pred_class == i).reshape(flat_shape), axis=1) / # intersection
        (np.sum(np.logical_or(y_true_class == i, y_pred_class == i).reshape(flat_shape), axis=1) + 1e-9) # union
        for i in range(len(labels))
    ]

    if example_ids is None:
        example_ids = ['example_' + str(i) for i in range(len(x))]

    dfMap = {
        'wandb_example_id': example_ids,
        'image': images,
        'label': label_imgs,
        'prediction': predictions,
        'incorrect_prediction': incorrect_predictions,
        'iou': iou,
        'accuracy': accuracy,
    }

    for i in range(len(iou_class)):
        dfMap['iou_{}'.format(labels[i])] = iou_class[i]

    all_columns = [
        'wandb_example_id',
        'image',
        'label',
        'prediction',
        'incorrect_prediction',
        'iou',
        'accuracy',
    ] + ['iou_'.format(l) for l in labels]

    return pd.DataFrame(dfMap, columns=all_columns)
