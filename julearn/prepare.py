# Authors: Federico Raimondo <f.raimondo@fz-juelich.de>
#          Sami Hamdan <s.hamdan@fz-juelich.de>
# License: AGPL
from julearn.model_selection.available_searchers import (
    get_searcher,
    list_searchers,
)
from julearn.utils.column_types import pick_columns
import pandas as pd
import numpy as np
from sklearn.model_selection import RepeatedKFold
from sklearn.base import clone
from sklearn.model_selection import check_cv

from .estimators import get_model
from .transformers import get_transformer
from .utils import raise_error, warn, logger


def _validate_input_data_np(X, y, confounds, groups):
    # X must be np.ndarray with at most 2d
    if not isinstance(X, np.ndarray):
        raise_error("X must be a numpy array if no dataframe is specified")

    if X.ndim not in [1, 2]:
        raise_error("X must be at most bi-dimensional")

    # Y must be np.ndarray with 1 dimension
    if not isinstance(y, np.ndarray):
        raise_error("y must be a numpy array if no dataframe is specified")

    if y.ndim != 1:
        raise_error("y must be one-dimensional")

    # Same number of elements
    if X.shape[0] != y.shape[0]:
        raise_error(
            "The number of samples in X do not match y "
            "(X.shape[0] != y.shape[0]"
        )

    if confounds is not None:
        if not isinstance(confounds, np.ndarray):
            raise_error(
                "confounds must be a numpy array if no dataframe is "
                "specified"
            )

        if confounds.ndim not in [1, 2]:
            raise_error("confounds must be at most bi-dimensional")

        if X.shape[0] != confounds.shape[0]:
            raise_error(
                "The number of samples in X do not match confounds "
                "(X.shape[0] != confounds.shape[0]"
            )

    if groups is not None:
        if not isinstance(groups, np.ndarray):
            raise_error(
                "groups must be a numpy array if no dataframe is " "specified"
            )

        if groups.ndim != 1:
            raise_error("groups must be one-dimensional")


def _validate_input_data_df(X, y, confounds, df, groups):

    # in the dataframe
    if not isinstance(X, (str, list)):
        raise_error("X must be a string or list of strings")

    if not isinstance(y, str):
        raise_error("y must be a string")

    # Confounds can be a string, list or none
    if not isinstance(confounds, (str, list, type(None))):
        raise_error(
            "If not None, confounds must be a string or list " "of strings"
        )

    if not isinstance(groups, (str, type(None))):
        raise_error("groups must be a string")

    if not isinstance(df, pd.DataFrame):
        raise_error("df must be a pandas.DataFrame")

    if any(not isinstance(x, str) for x in df.columns):
        raise_error("DataFrame columns must be strings")


def _validate_input_data_df_ext(X, y, confounds, df, groups):
    missing_columns = [t_x for t_x in X if t_x not in df.columns]
    # In reality, this is not needed as the regexp match will fail
    # Leaving it as additional check in case the regexp match changes
    if len(missing_columns) > 0:  # pragma: no cover
        raise_error(  # pragma: no cover
            "All elements of X must be in the dataframe. "
            f"The following are missing: {missing_columns}"
        )

    if y not in df.columns:
        raise_error(f"Target '{y}' (y) is not a valid column in the dataframe")

    if confounds is not None:
        missing_columns = [t_c for t_c in confounds if t_c not in df.columns]
        # In reality, this is not needed as the regexp match will fail
        # Leaving it as additional check in case the regexp match changes
        if len(missing_columns) > 0:  # pragma: no cover
            raise_error(  # pragma: no cover
                "All elements of confounds must be in the dataframe. "
                f"The following are missing: {missing_columns}"
            )

    if groups is not None:
        if groups not in df.columns:
            raise_error(
                f"Groups '{groups}' is not a valid column " "in the dataframe"
            )
        if groups == y:
            warn("y and groups are the same column")
        if groups in X:
            warn("groups is part of X")

    if y in X:
        warn(f"List of features (X) contains the target {y}")


def prepare_input_data(X, y, confounds, df, pos_labels, groups):
    """Prepare the input data and variables for the pipeline

    Parameters
    ----------
    X : str, list(str) or numpy.array
        The features to use.
        See https://juaml.github.io/julearn/input.html for details.
    y : str or numpy.array
        The targets to predict.
        See https://juaml.github.io/julearn/input.html for details.
    confounds : str, list(str) or numpy.array | None
        The confounds.
        See https://juaml.github.io/julearn/input.html for details.
    df : pandas.DataFrame with the data. | None
        See https://juaml.github.io/julearn/input.html for details.
    pos_labels : str, int, float or list | None
        The labels to interpret as positive. If not None, every element from y
        will be converted to 1 if is equal or in pos_labels and to 0 if not.
    groups : str or numpy.array | None
        The grouping labels in case a Group CV is used.
        See https://juaml.github.io/julearn/input.html for details.

    Returns
    -------
    df_X_conf : pandas.DataFrame
        A dataframe with the features and confounds (if specified in the
        confounds parameter) for each sample.
    df_y : pandas.Series
        A series with the y variable (target) for each sample.
    df_groups : pandas.Series
        A series with the grouping variable for each sample (if specified
        in the groups parameter).
    confound_names : str
        The name of the columns if df_X_conf that represent confounds.

    """
    logger.info("==== Input Data ====")

    # Declare them as None to avoid CI issues
    df_X_conf = None
    confound_names = None
    df_groups = None
    if df is None:
        logger.info("Using numpy arrays as input")
        _validate_input_data_np(X, y, confounds, groups)
        # creating df_X_conf
        if X.ndim == 1:
            X = X[:, None]
        logger.info(f"# Samples: {X.shape[0]}")
        logger.info(f"# Features: {X.shape[1]}")
        columns = [f"feature_{i}" for i in range(X.shape[1])]
        df_X_conf = pd.DataFrame(X, columns=columns)

        # adding confounds to df_X_conf
        if confounds is not None:
            if confounds.ndim == 1:
                confounds = confounds[:, None]
            logger.info(f"# Confounds: {X.shape[1]}")
            confound_names = [
                f"confound_{i}" for i in range(confounds.shape[1])
            ]
            df_X_conf[confound_names] = confounds

        # creating a Series for y if not existent
        df_y = pd.Series(y, name="y")

        if groups is not None:
            logger.info("Using groups")
            df_groups = pd.Series(groups, name="groups")

    else:
        logger.info("Using dataframe as input")
        _validate_input_data_df(X, y, confounds, df, groups)
        logger.info(f"\tFeatures: {X}")
        logger.info(f"\tTarget: {y}")
        if confounds is not None:
            logger.info(f"Confounds: {confounds}")
            X_confounds = pick_columns(confounds, df.columns)
        else:
            X_confounds = []

        if X == [":"]:
            X_columns = [
                x for x in df.columns if x not in X_confounds and x != y
            ]
            if groups is not None:
                X_columns = [x for x in X_columns if x not in groups]
        else:
            X_columns = pick_columns(X, df.columns)

        logger.info(f"\tExpanded X: {X_columns}")
        logger.info(f"\tExpanded Confounds: {X_confounds}")
        _validate_input_data_df_ext(X_columns, y, X_confounds, df, groups)
        X_conf_columns = X_columns

        overlapping = [t_c for t_c in X_confounds if t_c in X]
        if len(overlapping) > 0:
            warn(f"X contains the following confounds {overlapping}")
        for t_c in X_confounds:
            # This will add the confounds if not there already
            if t_c not in X_conf_columns:
                X_conf_columns.append(t_c)

        df_X_conf = df.loc[:, X_conf_columns].copy()
        df_y = df.loc[:, y].copy()
        if groups is not None:
            logger.info(f"Using {groups} as groups")
            df_groups = df.loc[:, groups].copy()
        confound_names = X_confounds

    if pos_labels is not None:
        if not isinstance(pos_labels, list):
            pos_labels = [pos_labels]
        logger.info(f"Setting the following as positive labels {pos_labels}")
        # TODO: Warn if pos_labels are not in df_y
        df_y = df_y.isin(pos_labels).astype(np.int64)
    logger.info("====================")
    logger.info("")
    return df_X_conf, df_y, df_groups, confound_names


def prepare_model(model, problem_type):
    """Get the propel model/name pair from the input

    Parameters
    ----------
    model: str or sklearn.base.BaseEstimator
        str/model_name that can be read in to create a model.
    problem_type: str
        classification or regression

    Returns
    -------
    model_name : str
        The model name
    model : object
        The model

    """
    logger.info("====== Model ======")
    if isinstance(model, str):
        logger.info(f"Obtaining model by name: {model}")
        model_name = model
        model = get_model(model_name, problem_type)
    elif _is_valid_sklearn_model(model):
        model_name = model.__class__.__name__.lower()
        logger.info(f"Using scikit-learn model: {model_name}")
    else:
        raise_error(
            "Model must be a string or a scikit-learn compatible object."
        )
    logger.info("===================")
    logger.info("")
    return model_name, model


def prepare_hyperparameter_tuning(params_to_tune, search_params, pipeline):
    """Prepare model parameters.

    For each of the model parameters, determine if it can be directly set or
    must be tuned using hyperparameter tuning.

    Parameters
    ----------
    msel_dict : dict
        A dictionary with the model selection parameters.The dictionary can
        define the following keys:

        * 'STEP__PARAMETER': A value (or several) to be used as PARAMETER for
          STEP in the pipeline. Example: 'svm__probability': True will set
          the parameter 'probability' of the 'svm' model. If more than option
        * 'search': The kind of search algorithm to use e.g.:
          'grid' or 'random'. All valid julearn searchers can be entered.
        * 'cv': If search is going to be used, the cross-validation
          splitting strategy to use. Defaults to same CV as for the model
          evaluation.
        * 'scoring': If search is going to be used, the scoring metric to
          evaluate the performance.
        * 'search_params': Additional parameters for the search method.

    pipeline : ExtendedDataframePipeline
        The pipeline to apply/tune the hyperparameters

    Returns
    -------
    pipeline : ExtendedDataframePipeline
        The modified pipeline
    """
    logger.info("= Model Parameters =")

    search_params = {} if search_params is None else search_params
    if len(params_to_tune) > 0:
        search = search_params.get("kind", "grid")
        scoring = search_params.get("scoring", None)
        cv_inner = search_params.get("cv", None)

        if search in list_searchers():
            logger.info(f"Tuning hyperparameters using {search}")
            search = get_searcher(search)
        else:
            if isinstance(search, str):
                raise_error(
                    f"The searcher {search} is not a valid julearn searcher. "
                    "You can get a list of all available once by using: "
                    "julearn.model_selection.list_searchers(). You can also "
                    "enter a valid scikit-learn searcher or register it."
                )
            else:
                warn(f"{search} is not a registered searcher. ")
                logger.info(
                    f"Tuning hyperparameters using not registered {search}"
                )

        logger.info("Hyperparameters:")
        for k, v in params_to_tune.items():
            logger.info(f"\t{k}: {v}")

        cv_inner = prepare_cv(cv_inner)

        search_params["cv"] = cv_inner
        search_params["scoring"] = scoring
        logger.info("Search Parameters:")
        for k, v in search_params.items():
            logger.info(f"\t{k}: {v}")
        pipeline = search(pipeline, params_to_tune, **search_params)
    elif search_params is not None and len(search_params) > 0:
        warn(
            "Hyperparameter search parameters were specified, but no "
            "hyperparameters to tune"
        )
    logger.info("====================")
    logger.info("")
    return pipeline


def prepare_cv(cv):
    """Generates a CV using string compatible with
    repeat:5_nfolds:5 where 5 can be exchange with any int.
    Alternatively, it can take in a valid cv splitter or int as
    in cross_validate in sklearn.

    Parameters
    ----------
    cv : int or str or cv_splitter
        [description]

    """

    def parser(cv_string):
        n_repeats, n_folds = cv_string.split("_")
        n_repeats, n_folds = [
            int(name.split(":")[-1]) for name in [n_repeats, n_folds]
        ]
        logger.info(
            f"CV interpreted as RepeatedKFold with {n_repeats} "
            f"repetitions of {n_folds} folds"
        )
        return RepeatedKFold(n_splits=n_folds, n_repeats=n_repeats)

    try:
        _cv = check_cv(cv)
        logger.info(f"Using scikit-learn CV scheme {_cv}")
    except ValueError:
        _cv = parser(cv)

    return _cv


def _create_preprocess_tuple(transformer):
    if type(transformer) == list:
        return transformer
    elif type(transformer) == str:
        trans_name = transformer
        trans = get_transformer(transformer)
    else:
        trans_name = transformer.__class__.__name__.lower()
        trans = clone(transformer)

    return trans_name, trans


def _is_valid_sklearn_transformer(transformer):

    return (
        hasattr(transformer, "fit")
        and hasattr(transformer, "transform")
        and hasattr(transformer, "get_params")
        and hasattr(transformer, "set_params")
    )


def _is_valid_sklearn_model(model):
    return (
        hasattr(model, "fit")
        and hasattr(model, "predict")
        and hasattr(model, "get_params")
        and hasattr(model, "set_params")
    )


# def check_consistency(
#     pipeline,
#     df_X_conf,
#     y,
#     cv,
#     groups,
#     problem_type,
# ):
#     """Check the consistency of the parameters/input"""

#     # Check problem type and the target.
#     n_classes = np.unique(y.values).shape[0]
#     if problem_type == "classification":
#         # If not exactly two classes:
#         if n_classes != 2:
#             logger.info(
#                 "Multi-class classification problem detected "
#                 f"#classes = {n_classes}."
#             )
#         else:
#             logger.info("Binary classification problem detected.")
#     else:
#         # Regression
#         is_numeric = np.issubdtype(y.values.dtype, np.number)
#         if not is_numeric:
#             warn(
#                 f"The kind of values in y ({y.values.dtype}) is not "
#                 "suitable for a regression."
#             )
#         else:
#             n_classes = np.unique(y.values).shape[0]
#             if n_classes == 2:
#                 warn(
#                     f"A regression will be performed but only 2 "
#                     "distinct values are defined in y."
#                 )
#     # Check groups and CV scheme
#     if groups is not None:
#         valid_instances = (
#             model_selection.GroupKFold,
#             model_selection.GroupShuffleSplit,
#             model_selection.LeaveOneGroupOut,
#             model_selection.LeavePGroupsOut,
#             StratifiedGroupsKFold,
#             RepeatedStratifiedGroupsKFold,
#         )
#         if not isinstance(cv, valid_instances):
#             warn(
#                 "The parameter groups was specified but the CV strategy "
#                 "will not consider them."
#             )
