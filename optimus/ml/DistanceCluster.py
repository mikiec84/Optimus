from pyspark.sql.functions import *
from pyspark.sql.types import *
from pyspark.ml.feature import NGram
from functools import reduce
import string


class DistanceCluster():
    def __init__(self, df):
        self.df = df
        self.keyer = KeyCollision(df)

    def validate(column):
        # Asserting data variable is string:
        assert type(column) == type('s'), "Error: Column argument must be a string."

        # If None or [] is provided with column parameter:
        assert column != "", "Error: Column can not be a empty string"

        # Filters all string columns in dataFrame
        validCols = [c for (c, t) in filter(lambda t: t[1] == 'string', self.df.dtypes)]

        # asserts the column parameter is a string column of the dataFrame
        assert column in validCols, 'Error: Columns or column does not exist in the dataFrame or is numberic column'

    """
    Performs clustering on a string column 'column' based on the levenshtein distance
    between all values
    """

    def __cluster_leven__(self, column, threshold):
        first_col = 'fingerprint'
        second_col = '_fingerprint_'
        distance_col = 'levenshtein'

        fdf = self.keyer.fingerprints(column, first_col)
        fdict = (fdf.map(lambda r: r[first_col])
                 .zip(fdf.map(lambda f: f[column]))
                 .map(lambda x: (x[0], [x[1]]))
                 .reduceByKey(lambda a, b: a + b)
                 .collectAsMap())

        fingerprints = (fdf.select(first_col)
                        .distinct()
                        .cache())

        fc = (fdf
              .groupBy('fingerprint')
              .agg(sum('count')
                   .alias('count'))
              .cache())

        # get combinations between values
        # and obtain a distance matrix based on the levenshtein distance
        condition = first_col + '!=' + second_col
        l_matrix = (fingerprints.select(first_col)
                    .join(fingerprints.select(fingerprints[first_col].alias(second_col))
                          , col(first_col) < col(second_col)
                          , how='inner')
                    .distinct()
                    .filter(condition)
                    .withColumn('levenshtein', levenshtein(first_col, second_col))
                    .cache())

        clustering = {}  # dict to contain clusters
        cid = 0  # indexed cluster id for iterating over clusters
        pair = []  # pair of elements with levenshtein < distance
        smallest = 0  # smallest distance found in the DF

        # first, clustering is populated with all fdict values with more than one item
        def addItem(value):
            i = len(clustering)
            clustering[i] = value

        for i, v in fdict.items():
            if (len(v) > 1):
                addItem(v)

                # get the smallest distance (as an int) present in the matrix
        try:
            smallest = l_matrix.map(lambda d: d[distance_col]).min()
        except ValueError:
            assert False, "Error: Dataframe does not contain distinct values"

        # cluster procedure, clustering will be perfomed over rows with levenshtein < threshold
        while (smallest <= threshold):

            grouped = False  # flag to determine if pair has been added to a cluster

            # retrieves the first combination of strings with the smalles distance as a list
            first = l_matrix.filter(l_matrix[distance_col] == smallest).first()
            pair = [first[0], first[1]]

            # iterate over existing clusters
            for cid in clustering:

                # if any of the items in pair is in any of the clusters,
                # the other item should be added to the list
                if any(raw in clustering[cid] for fingerprint in pair for raw in fdict[fingerprint]):
                    clustering[cid].extend(raw
                                           for fingerprint in pair
                                           for raw in fdict[fingerprint]
                                           if raw not in clustering[cid])
                    grouped = True
                    break;

            # if pair was not added to a cluster, create a new one and add both elements
            if not grouped:
                cid = len(clustering)
                clustering[cid] = []
                clustering[cid].extend(raw
                                       for fingerprint in pair
                                       for raw in fdict[fingerprint])

                # index of item with smallest 'count' on fingerprint_count
            filtered = fc.filter((fc.fingerprint == pair[0]) |
                                 (fc.fingerprint == pair[1]))
            dropped = pair.index((filtered
                                  .select('*')
                                  .join(filtered.agg(max('count').alias('count')), ['count'])
                                  .map(lambda x: x.fingerprint)
                                  .collect())[0])

            # filter to remove all columns that include the value that will be dropped
            l_matrix = (l_matrix
                        .filter((l_matrix[first_col] != pair[dropped]) &
                                (l_matrix[second_col] != pair[dropped])))

            try:
                smallest = l_matrix.map(lambda d: d[distance_col]).min()
            except ValueError:
                break

        l_matrix.unpersist()
        fingerprints.unpersist()
        fc.unpersist()
        return clustering

    """Returns a dictionary containing clusters of strings, associated by the Levenshtein distance"""

    def levenshteinCluster(self, column, distance):
        validate(column)

        return self.__cluster_leven__(column, distance)