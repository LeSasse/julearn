import pandas as pd
import numpy as np
from sklearn.base import TransformerMixin, BaseEstimator
from sklearn.compose import ColumnTransformer

from .. utils import pick_columns, change_column_type
from . base import JuTransformer
from .. utils import raise_error, logger, make_type_selector


class SetColumnTypes(JuTransformer):

    def __init__(self, X_types):
        self.X_types = X_types

    def fit(self, X, y=None):
        if self.X_types is None:
            self.X_types = {}
        self.feature_names_in_ = X.columns
        logger.debug(f"Setting column types for {self.feature_names_in_}")
        column_mapper_ = {}
        for X_type, columns in self.X_types.items():
            if not isinstance(columns, (list, tuple)):
                raise_error(
                    "Each value of X_types must be either a list or a tuple.")
            column_mapper_ = {**column_mapper_,
                              **{col: change_column_type(col, X_type)
                                 for col in columns}
                              }
        for x in X.columns:
            if x not in column_mapper_:
                if "__:type:__" not in x:
                    column_mapper_[x] = change_column_type(x, "continuous")
                # TODO: this should not be needed, but there's an error
                else:
                    column_mapper_[x] = x

        logger.debug(f"\tColumn mappers for {column_mapper_}")
        self.column_mapper_ = column_mapper_
        return self

    def transform(self, X):
        return X.copy().rename(columns=self.column_mapper_)

    def get_feature_names_out(self, input_features=None):
        return self.feature_names_in_.map(self.column_mapper_)


class FilterColumns(JuTransformer):

    def __init__(self, apply_to, keep, needed_types=None):
        self.apply_to = apply_to
        self.keep = keep
        self.needed_types = needed_types

    def fit(self, X, y=None):
        inner_selector = make_type_selector(self.apply_to)
        inner_filter = ColumnTransformer(
            transformers=[
                ("filter_apply_to", "passthrough", inner_selector), ],
            remainder="passthrough", verbose_feature_names_out=False,
        )

        apply_to_selector = make_type_selector(self.keep)
        self.filter_columns_ = ColumnTransformer(
            transformers=[
                ("keep", inner_filter, apply_to_selector)],
            remainder="drop", verbose_feature_names_out=False,

        )
        self.filter_columns_.fit(X, y)

    def transform(self, X):
        return self.filter_columns_.transform(X)

    def get_feature_names_out(self, input_features=None):
        return self.filter_columns_.get_feature_names_out(input_features)


class ChangeColumnTypes(JuTransformer):

    def __init__(self, X_types, new_X_type):
        self.columns_match = X_types
        self.new_type = new_X_type

    def fit(self, X, y=None):
        self.detected_columns_ = pick_columns(self.columns_match, X.columns)
        self.column_mapper_ = {col: change_column_type(col, self.new_type)
                               for col in self.detected_columns_}
        return self

    def transform(self, X):
        return X.copy().rename(columns=self.column_mapper_)


class DropColumns(TransformerMixin, BaseEstimator):

    def __init__(self, columns):
        self.columns = columns

    def fit(self, X, y=None):
        self.support_mask_ = pd.Series(True, index=X.columns, dtype=bool)
        try:
            self.detected_columns_ = pick_columns(self.columns, X.columns)
            self.support_mask_[self.detected_columns_] = False
        except ValueError:
            self.detected_columns_ = []
        self.support_mask_ = self.support_mask_.values
        return self

    def transform(self, X):
        return X.drop(columns=self.detected_columns_)

    def get_support(self, indices=False):
        if indices:
            return np.arange(len(self.support_mask_))[self.support_mask_]
        else:
            return self.support_mask_
