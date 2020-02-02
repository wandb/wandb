import numpy as np
import pandas as pd
import matplotlib.pyplot as mplt
import os
import collections
import sklearn
import scipy
from sklearn.base import BaseEstimator
from sklearn.model_selection import train_test_split
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.neighbors import KNeighborsClassifier
import random
import wandb
from scipy.spatial.distance import euclidean, squareform, pdist
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score, f1_score
from sklearn.exceptions import NotFittedError
from sklearn.utils.validation import check_is_fitted
from sklearn.preprocessing import LabelEncoder

dimensionality_reduction=PCA(n_components=2)
def encode_labels(df):
    le = LabelEncoder()
    # apply le on categorical feature columns
    categorical_cols = df.select_dtypes(exclude=['int','float','float64','float32','int32','int64']).columns
    df[categorical_cols] = df[categorical_cols].apply(lambda col: le.fit_transform(col))
# Test Asummptions for plotting parameters and datasets
def test_missing(**kwargs):
    test_passed = True
    for k,v in kwargs.items():
        # Missing/empty params/datapoint arrays
        if v is None:
            wandb.termerror("%s is None. Please try again." % (k))
            test_passed = False
        if ((k == 'X') or (k == 'X_test')):
            if isinstance(v, scipy.sparse.csr.csr_matrix):
                v = v.toarray()
            elif isinstance(v, (pd.DataFrame, pd.Series)):
                v = v.to_numpy()
            elif isinstance(v, list):
                v = np.asarray(v)

            # Warn the user about missing values
            missing = 0
            missing = np.count_nonzero(pd.isnull(v))
            if missing>0:
                wandb.termwarn("%s contains %d missing values. " % (k,missing))
                test_passed = False
            # Ensure the dataset contains only integers
            non_nums = 0
            if v.ndim == 1:
                non_nums = sum(1 for val in v if (not isinstance(val, (int, float, complex)) and not isinstance(val,np.number)))
            else:
                non_nums = sum(1 for sl in v for val in sl if (not isinstance(val, (int, float, complex)) and not isinstance(val,np.number)))
            if non_nums>0:
                wandb.termerror("%s contains values that are not numbers. Please vectorize, label encode or one hot encode %s and call the plotting function again." % (k,k))
                test_passed = False
    return test_passed
def test_types(**kwargs):
    test_passed = True
    for k,v in kwargs.items():
        # check for incorrect types
        if ((k == 'X') or (k == 'X_test') or (k == 'y') or (k == 'y_test')
            or (k == 'y_true') or (k == 'y_probas')):
            if not isinstance(v, (collections.Sequence, collections.Iterable, np.ndarray, np.generic, pd.DataFrame, pd.Series, list)):
                wandb.termerror("%s is not an array. Please try again." % (k))
                test_passed = False
        # check for classifier types
        if (k=='model'):
            if ((not sklearn.base.is_classifier(v)) and (not sklearn.base.is_regressor(v))):
                wandb.termerror("%s is not a classifier or regressor. Please try again." % (k))
                test_passed = False
        elif (k=='clf' or k=='binary_clf'):
            if (not(sklearn.base.is_classifier(v))):
                wandb.termerror("%s is not a classifier. Please try again." % (k))
                test_passed = False
        elif (k=='regressor'):
            if (not sklearn.base.is_regressor(v)):
                wandb.termerror("%s is not a regressor. Please try again." % (k))
                test_passed = False
        elif (k=='clusterer'):
            if (not(getattr(v, "_estimator_type", None) == "clusterer")):
                wandb.termerror("%s is not a clusterer. Please try again." % (k))
                test_passed = False
    return test_passed
def test_fitted(model):
    try:
        model.predict(np.zeros((7, 3)))
    except NotFittedError:
        wandb.termerror("Please fit the model before passing it in.")
        return False
    except AttributeError:
        # Some clustering models (LDA, PCA, Agglomerative) don't implement ``predict``
        try:
            check_is_fitted(
                model,
                [
                    "coef_",
                    "estimator_",
                    "labels_",
                    "n_clusters_",
                    "children_",
                    "components_",
                    "n_components_",
                    "n_iter_",
                    "n_batch_iter_",
                    "explained_variance_",
                    "singular_values_",
                    "mean_",
                ],
                all_or_any=any,
            )
            return True
        except sklearn.exceptions.NotFittedError:
            wandb.termerror("Please fit the model before passing it in.")
            return False
    except Exception:
        # Assume it's fitted, since ``NotFittedError`` wasn't raised
        return True

# Decision Boundary Utils
# Modified from https://github.com/tmadl/highdimensional-decision-boundary-plot
class DBPlot(BaseEstimator):
    def __init__(
        self,
        estimator=KNeighborsClassifier(n_neighbors=10),
        acceptance_threshold=0.03,
        n_decision_boundary_keypoints=60,
        n_connecting_keypoints=None,
        n_interpolated_keypoints=None,
        n_generated_testpoints_per_keypoint=15,
        linear_iteration_budget=100,
        hypersphere_iteration_budget=300,
        verbose=False,
    ):
        if acceptance_threshold == 0:
            raise Warning(
                "A nonzero acceptance threshold is strongly recommended so the optimizer can finish in finite time"
            )
        if linear_iteration_budget < 2 or hypersphere_iteration_budget < 2:
            raise Exception("Invalid iteration budget")

        self.classifier = estimator
        self.acceptance_threshold = acceptance_threshold

        if (
            n_decision_boundary_keypoints
            and n_connecting_keypoints
            and n_interpolated_keypoints
            and n_connecting_keypoints + n_interpolated_keypoints
            != n_decision_boundary_keypoints
        ):
            raise Exception(
                "n_connecting_keypoints and n_interpolated_keypoints must sum to n_decision_boundary_keypoints (set them to None to use calculated suggestions)"
            )

        self.n_connecting_keypoints = (
            n_connecting_keypoints
            if n_connecting_keypoints != None
            else n_decision_boundary_keypoints / 3
        )
        self.n_interpolated_keypoints = (
            n_interpolated_keypoints
            if n_interpolated_keypoints != None
            else n_decision_boundary_keypoints * 2 / 3
        )

        self.linear_iteration_budget = linear_iteration_budget
        self.n_generated_testpoints_per_keypoint = n_generated_testpoints_per_keypoint
        self.hypersphere_iteration_budget = hypersphere_iteration_budget
        self.verbose = verbose

        self.decision_boundary_points = []
        self.decision_boundary_points_2d = []
        self.X_testpoints = []
        self.y_testpoints = []
        self.train_idx = []
        self.test_idx = []
        self.background = []
        self.steps = 3

        self.hypersphere_max_retry_budget = 20
        self.penalties_enabled = True
        self.random_gap_selection = False

    def setclassifier(self, estimator=KNeighborsClassifier(n_neighbors=10)):
        self.classifier = estimator

    def fit(self, X, y, training_indices=None):
        if set(np.array(y, dtype=int).tolist()) != set([0, 1]):
            raise Exception(
                "Currently only implemented for binary classification. Make sure you pass in two classes (0 and 1)"
            )

        if training_indices == None:
            train_idx = range(len(y))
        else:
            train_idx = training_indices

        self.X = X
        self.y = y
        self.train_idx = train_idx
        # self.test_idx = np.setdiff1d(np.arange(len(y)), self.train_idx, assume_unique=False)
        self.test_idx = list(set(range(len(y))).difference(set(self.train_idx)))

        # fit classifier if necessary
        try:
            self.classifier.predict([X[0]])
        except:
            self.classifier.fit(X, y)

        self.y_pred = self.classifier.predict(self.X)

        # fit DR method if necessary
        dimensionality_reduction.fit(X)
        try:
            dimensionality_reduction.transform([X[0]])
        except:
            raise Exception(
                "Please make sure your dimensionality reduction method has an exposed transform() method! If in doubt, use PCA or Isomap"
            )

        # transform data
        self.X2d = dimensionality_reduction.transform(self.X)
        self.mean_2d_dist = np.mean(pdist(self.X2d))
        self.X2d_xmin, self.X2d_xmax = np.min(self.X2d[:, 0]), np.max(self.X2d[:, 0])
        self.X2d_ymin, self.X2d_ymax = np.min(self.X2d[:, 1]), np.max(self.X2d[:, 1])

        self.majorityclass = 0 if list(y).count(0) > list(y).count(1) else 1
        self.minorityclass = 1 - self.majorityclass
        minority_idx, majority_idx = (
            np.where(y == self.minorityclass)[0],
            np.where(y == self.majorityclass)[0],
        )
        self.Xminor, self.Xmajor = X[minority_idx], X[majority_idx]
        self.Xminor2d, self.Xmajor2d = self.X2d[minority_idx], self.X2d[majority_idx]

        # set up efficient nearest neighbor models for later use
        self.nn_model_2d_majorityclass = NearestNeighbors(n_neighbors=2)
        self.nn_model_2d_majorityclass.fit(self.X2d[majority_idx, :])

        self.nn_model_2d_minorityclass = NearestNeighbors(n_neighbors=2)
        self.nn_model_2d_minorityclass.fit(self.X2d[minority_idx, :])

        # step 1. look for decision boundary points between corners of majority &
        # minority class distribution
        minority_corner_idx, majority_corner_idx = [], []
        for extremum1 in [np.min, np.max]:
            for extremum2 in [np.min, np.max]:
                _, idx = self.nn_model_2d_minorityclass.kneighbors(
                    [[extremum1(self.Xminor2d[:, 0]), extremum2(self.Xminor2d[:, 1])]]
                )
                minority_corner_idx.append(idx[0][0])
                _, idx = self.nn_model_2d_majorityclass.kneighbors(
                    [[extremum1(self.Xmajor2d[:, 0]), extremum2(self.Xmajor2d[:, 1])]]
                )
                majority_corner_idx.append(idx[0][0])

        # optimize to find new db keypoints between corners
        self._linear_decision_boundary_optimization(
            minority_corner_idx, majority_corner_idx, all_combinations=True, step=1
        )

        # step 2. look for decision boundary points on lines connecting randomly
        # sampled points of majority & minority class
        n_samples = int(self.n_connecting_keypoints)
        from_idx = list(random.sample(list(np.arange(len(self.Xminor))), n_samples))
        to_idx = list(random.sample(list(np.arange(len(self.Xmajor))), n_samples))

        # optimize to find new db keypoints between minority and majority class
        self._linear_decision_boundary_optimization(
            from_idx, to_idx, all_combinations=False, step=2
        )

        if len(self.decision_boundary_points_2d) < 2:
            wandb.termerror(
                "Failed to find initial decision boundary. Retrying... If this keeps happening, increasing the acceptance threshold might help. Also, make sure the classifier is able to find a point with 0.5 prediction probability (usually requires an even number of estimators/neighbors/etc)."
            )
            return self.fit(X, y, training_indices)

        # step 3. look for decision boundary points between already known db
        # points that are too distant (search on connecting line first, then on
        # surrounding hypersphere surfaces)
        edges, gap_distances, gap_probability_scores = (
            self._get_sorted_db_keypoint_distances()
        )  # find gaps
        self.nn_model_decision_boundary_points = NearestNeighbors(n_neighbors=2)
        self.nn_model_decision_boundary_points.fit(self.decision_boundary_points)

        i = 0
        retries = 0
        while i < self.n_interpolated_keypoints:
            if self.random_gap_selection:
                # randomly sample from sorted DB keypoint gaps?
                gap_idx = np.random.choice(
                    len(gap_probability_scores), 1, p=gap_probability_scores
                )[0]
            else:
                # get largest gap
                gap_idx = 0
            from_point = self.decision_boundary_points[edges[gap_idx][0]]
            to_point = self.decision_boundary_points[edges[gap_idx][1]]

            # optimize to find new db keypoint along line connecting two db keypoints
            # with large gap
            db_point = self._find_decision_boundary_along_line(
                from_point, to_point, penalize_tangent_distance=self.penalties_enabled
            )

            if self.decision_boundary_distance(db_point) > self.acceptance_threshold:
                if self.verbose:
                    wandb.termerror(
                        "No good solution along straight line - trying to find decision boundary on hypersphere surface around known decision boundary point"
                    )

                # hypersphere radius half the distance between from and to db keypoints
                R = euclidean(from_point, to_point) / 2.0
                # search around either source or target keypoint, with 0.5 probability,
                # hoping to find decision boundary in between
                if random.random() > 0.5:
                    from_point = to_point

                # optimize to find new db keypoint on hypersphere surphase around known keypoint
                db_point = self._find_decision_boundary_on_hypersphere(from_point, R)
                if (
                    self.decision_boundary_distance(db_point)
                    <= self.acceptance_threshold
                ):
                    db_point2d = dimensionality_reduction.transform([db_point])[0]
                    self.decision_boundary_points.append(db_point)
                    self.decision_boundary_points_2d.append(db_point2d)
                    i += 1
                    retries = 0
                else:
                    retries += 1
                    if retries > self.hypersphere_max_retry_budget:
                        i += 1
                        dist = self.decision_boundary_distance(db_point)
                        msg = "Found point is too distant from decision boundary ({}), but retry budget exceeded ({})"
                        wandb.termerror(msg.format(dist, self.hypersphere_max_retry_budget))
                    elif self.verbose:
                        dist = self.decision_boundary_distance(db_point)
                        wandb.termerror(
                            "Found point is too distant from decision boundary ({}) retrying...".format(
                                dist
                            )
                        )

            else:
                db_point2d = dimensionality_reduction.transform([db_point])[0]
                self.decision_boundary_points.append(db_point)
                self.decision_boundary_points_2d.append(db_point2d)
                i += 1
                retries = 0

            edges, gap_distances, gap_probability_scores = (
                self._get_sorted_db_keypoint_distances()
            )  # reload gaps

        self.decision_boundary_points = np.array(self.decision_boundary_points)
        self.decision_boundary_points_2d = np.array(self.decision_boundary_points_2d)

        return self

    def plot(self):
        # decision boundary
        decision_boundary_x = self.decision_boundary_points_2d[:, 0]
        decision_boundary_y = self.decision_boundary_points_2d[:, 1]
        decision_boundary_color = "Decision Boundary"

        # training data
        train_x = self.X2d[self.train_idx, 0]
        train_y = self.X2d[self.train_idx, 1]
        train_color = ["Class 1 - Train Set"
                if self.y_pred[self.train_idx[i]] == self.y[self.train_idx[i]] == 1
                else (
                    "Class 2 - Train Set"
                    if self.y_pred[self.train_idx[i]] == self.y[self.train_idx[i]] == 0
                    else "Misclassified")
                for i in range(len(self.train_idx))]

        # testing data
        test_x = self.X2d[self.test_idx, 0]
        test_y = self.X2d[self.test_idx, 1]
        test_color = ["Class 1 - Test Set"
                if self.y_pred[self.test_idx[i]] == self.y[self.test_idx[i]] == 1
                else (
                    "Class 2 - Test Set"
                    if self.y_pred[self.test_idx[i]] == self.y[self.test_idx[i]] == 0
                    else "Misclassified")
                for i in range(len(self.test_idx))]
        return (
            decision_boundary_x,
            decision_boundary_y,
            decision_boundary_color,
            train_x,
            train_y,
            train_color,
            test_x,
            test_y,
            test_color
        )

    def decision_boundary_distance(self, x, grad=0):
        return np.abs(0.5 - self.classifier.predict_proba([x])[0][1])

    def get_decision_boundary_keypoints(self):
        if len(self.decision_boundary_points) == 0:
            raise Exception("Please call the fit method first!")
        return self.decision_boundary_points, self.decision_boundary_points_2d

    def _get_sorted_db_keypoint_distances(self, N=None):
        if N == None:
            N = self.n_interpolated_keypoints
        edges = minimum_spanning_tree(
            squareform(pdist(self.decision_boundary_points_2d))
        )
        edged = np.array(
            [
                euclidean(
                    self.decision_boundary_points_2d[u],
                    self.decision_boundary_points_2d[v],
                )
                for u, v in edges
            ]
        )
        gap_edge_idx = np.argsort(edged)[::-1][: int(N)]
        edges = edges[gap_edge_idx]
        gap_distances = np.square(edged[gap_edge_idx])
        gap_probability_scores = gap_distances / np.sum(gap_distances)
        return edges, gap_distances, gap_probability_scores

    def _linear_decision_boundary_optimization(
        self,
        from_idx,
        to_idx,
        all_combinations=True,
        retry_neighbor_if_failed=True,
        step=None,
        suppress_output=True,
    ):
        step_str = (
            ("Step " + str(step) + "/" + str(self.steps) + ":") if step != None else ""
        )

        retries = 4 if retry_neighbor_if_failed else 1
        for i in range(len(from_idx)):
            n = len(to_idx) if all_combinations else 1
            for j in range(n):
                from_i = from_idx[i]
                to_i = to_idx[j] if all_combinations else to_idx[i]
                for k in range(retries):
                    if k == 0:
                        from_point = self.Xminor[from_i]
                        to_point = self.Xmajor[to_i]
                    else:
                        # first attempt failed, try nearest neighbors of source and destination
                        # point instead
                        _, idx = self.nn_model_2d_minorityclass.kneighbors(
                            [self.Xminor2d[from_i]]
                        )
                        from_point = self.Xminor[idx[0][k // 2]]
                        _, idx = self.nn_model_2d_minorityclass.kneighbors(
                            [self.Xmajor2d[to_i]]
                        )
                        to_point = self.Xmajor[idx[0][k % 2]]

                    if euclidean(from_point, to_point) == 0:
                        break  # no decision boundary between equivalent points

                    db_point = self._find_decision_boundary_along_line(
                        from_point,
                        to_point,
                        penalize_tangent_distance=self.penalties_enabled,
                        penalize_extremes=self.penalties_enabled,
                    )

                    if (
                        self.decision_boundary_distance(db_point)
                        <= self.acceptance_threshold
                    ):
                        db_point2d = dimensionality_reduction.transform(
                            [db_point]
                        )[0]
                        if (
                            db_point2d[0] >= self.X2d_xmin
                            and db_point2d[0] <= self.X2d_xmax
                            and db_point2d[1] >= self.X2d_ymin
                            and db_point2d[1] <= self.X2d_ymax
                        ):
                            self.decision_boundary_points.append(db_point)
                            self.decision_boundary_points_2d.append(db_point2d)
                            break
                        else:
                            if self.verbose and not suppress_output:
                                msg = "{} {}/{}: Rejected decision boundary keypoint (outside of plot area)"

    def _find_decision_boundary_along_line(
        self,
        from_point,
        to_point,
        penalize_extremes=False,
        penalize_tangent_distance=False,
    ):
        def objective(l, grad=0):
            # interpolate between source and destionation; calculate distance from
            # decision boundary
            X = from_point + l[0] * (to_point - from_point)
            error = self.decision_boundary_distance(X)

            if penalize_tangent_distance:
                # distance from tangent between class1 and class0 point in 2d space
                x0, y0 = dimensionality_reduction.transform([X])[0]
                x1, y1 = dimensionality_reduction.transform([from_point])[0]
                x2, y2 = dimensionality_reduction.transform([to_point])[0]
                error += (
                    1e-12
                    * np.abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
                    / np.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)
                )

            if penalize_extremes:
                error += 1e-8 * np.abs(0.5 - l[0])

            return error

        optimizer = self._get_optimizer()
        optimizer.set_min_objective(objective)
        cl = optimizer.optimize([random.random()])
        db_point = from_point + cl[0] * (to_point - from_point)
        return db_point

    def _find_decision_boundary_on_hypersphere(self, centroid, R, penalize_known=False):
        def objective(phi, grad=0):
            # search on hypersphere surface in polar coordinates - map back to cartesian
            cx = centroid + polar_to_cartesian(phi, R)
            try:
                cx2d = dimensionality_reduction.transform([cx])[0]
                error = self.decision_boundary_distance(cx)
                if penalize_known:
                    # slight penalty for being too close to already known decision boundary
                    # keypoints
                    db_distances = [
                        euclidean(cx2d, self.decision_boundary_points_2d[k])
                        for k in range(len(self.decision_boundary_points_2d))
                    ]
                    error += (
                        1e-8
                        * (
                            (self.mean_2d_dist - np.min(db_distances))
                            / self.mean_2d_dist
                        )
                        ** 2
                    )
                return error
            except Exception as ex:
                wandb.termerror("Error in objective function:", ex)
                return np.infty

        optimizer = self._get_optimizer(
            D=self.X.shape[1] - 1,
            upper_bound=2 * np.pi,
            iteration_budget=self.hypersphere_iteration_budget,
        )
        optimizer.set_min_objective(objective)
        db_phi = optimizer.optimize(
            [random.random() * 2 * np.pi for k in range(self.X.shape[1] - 1)]
        )
        db_point = centroid + polar_to_cartesian(db_phi, R)
        return db_point

    def _get_optimizer(self, D=1, upper_bound=1, iteration_budget=None):
        if iteration_budget == None:
            iteration_budget = self.linear_iteration_budget

        '''
        opt = nlopt.opt(nlopt.GN_DIRECT_L_RAND, D)
        opt.set_stopval(self.acceptance_threshold/10.0)
        opt.set_ftol_rel(1e-5)
        opt.set_maxeval(iteration_budget)
        opt.set_lower_bounds(0)
        opt.set_upper_bounds(upper_bound)

        return opt
        '''

def minimum_spanning_tree(X, copy_X=True):
    if copy_X:
        X = X.copy()

    if X.shape[0] != X.shape[1]:
        raise ValueError("X needs to be square matrix of edge weights")
    n_vertices = X.shape[0]
    spanning_edges = []

    # initialize with node 0:
    visited_vertices = [0]
    num_visited = 1
    # exclude self connections:
    diag_indices = np.arange(n_vertices)
    X[diag_indices, diag_indices] = np.inf

    while num_visited != n_vertices:
        new_edge = np.argmin(X[visited_vertices], axis=None)
        # 2d encoding of new_edge from flat, get correct indices
        new_edge = divmod(new_edge, n_vertices)
        new_edge = [visited_vertices[new_edge[0]], new_edge[1]]
        # add edge to tree
        spanning_edges.append(new_edge)
        visited_vertices.append(new_edge[1])
        # remove all edges inside current tree
        X[visited_vertices, new_edge[1]] = np.inf
        X[new_edge[1], visited_vertices] = np.inf
        num_visited += 1
    return np.vstack(spanning_edges)


def polar_to_cartesian(arr, r):
    a = np.concatenate((np.array([2 * np.pi]), arr))
    si = np.sin(a)
    si[0] = 1
    si = np.cumprod(si)
    co = np.cos(a)
    co = np.roll(co, -1)
    return si * co * r
