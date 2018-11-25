#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2018  Mate Soos
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

import pandas as pd
import pickle
import sklearn
import sklearn.svm
import sklearn.tree
import sklearn.cluster
import optparse
import numpy as np
import sklearn.metrics
import time
import itertools
import math
import matplotlib.pyplot as plt
import sklearn.ensemble
import sklearn.model_selection


def write_mit_header(f):
    f.write("""/******************************************
Copyright (c) 2018, Mate Soos

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
***********************************************/\n\n""")


class Learner:
    def __init__(self, df, funcname, fname):
        self.df = df
        self.funcname = funcname
        self.fname = fname

    def output_to_dot(self, clf, features):
        fname = options.dot
        sklearn.tree.export_graphviz(clf, out_file=fname,
                                     feature_names=features,
                                     class_names=clf.classes_,
                                     filled=True, rounded=True,
                                     special_characters=True,
                                     proportion=True)
        print("Run dot:")
        print("dot -Tpng {fname} -o {fname}.png".format(fname=fname))
        print("gwenview {fname}.png".format(fname=fname))

    def plot_confusion_matrix(self, cm, classes,
                              normalize=False,
                              title='Confusion matrix',
                              cmap=plt.cm.Blues):
        """
        This function prints and plots the confusion matrix.
        Normalization can be applied by setting `normalize=True`.
        """
        if normalize:
            cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
            print(title)
        else:
            print('%s without normalization' % title)

        print(cm)

        if options.show:
            plt.figure()
            plt.imshow(cm, interpolation='nearest', cmap=cmap)
            plt.title(title)
            plt.colorbar()
            tick_marks = np.arange(len(classes))
            plt.xticks(tick_marks, classes, rotation=45)
            plt.yticks(tick_marks, classes)

            fmt = '.2f' if normalize else 'd'
            thresh = cm.max() / 2.
            for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
                plt.text(j, i, format(cm[i, j], fmt),
                         horizontalalignment="center",
                         color="white" if cm[i, j] > thresh else "black")

            plt.tight_layout()
            plt.ylabel('True label')
            plt.xlabel('Predicted label')

    # to check for too large or NaN values:
    def check_too_large_or_nan_values(self, df):
        features = df.columns.values.flatten().tolist()
        index = 0
        for index, row in df.iterrows():
            for x, name in zip(row, features):
                if not np.isfinite(x) or x > np.finfo(np.float32).max:
                    print("issue with data for features: ", name, x)
                index += 1

    class CodeWriter:
        def __init__(self, clf, features, funcname, code_file):
            self.f = open(code_file, 'w')
            write_mit_header(self.f)
            self.clf = clf
            self.feat = features
            self.funcname = funcname

        def print_full_code(self):
            self.f.write("""#include "clause.h"
#include "reducedb.h"

namespace CMSat {
    """)

            num_trees = 1
            if type(self.clf) is sklearn.tree.tree.DecisionTreeClassifier:
                self.f.write("""
static double estimator_{funcname}_0(
    const CMSat::Clause* cl
    , const uint32_t rdb0_last_touched_diff
    , const uint32_t rdb0_act_ranking
    , const uint32_t rdb0_act_ranking_top_10
) {{\n""".format(funcname=self.funcname))
                print(self.clf)
                print(self.clf.get_params())
                self.get_code(self.clf, 1)
                self.f.write("}\n")
            else:
                num_trees = len(self.clf.estimators_)
                for tree, i in zip(self.clf.estimators_, range(200)):
                    self.f.write("""
static double estimator_{funcname}_{est_num}(
    const CMSat::Clause* cl
    , const uint32_t rdb0_last_touched_diff
    , const uint32_t rdb0_act_ranking
    , const uint32_t rdb0_act_ranking_top_10
) {{\n""".format(est_num=i, funcname=self.funcname))
                    self.get_code(tree, 1)
                    self.f.write("}\n")

            # Final tally
            self.f.write("""
static bool {funcname}(
    const CMSat::Clause* cl
    , const uint32_t rdb0_last_touched_diff
    , const uint32_t rdb0_act_ranking
    , const uint32_t rdb0_act_ranking_top_10
) {{\n""".format(funcname=self.funcname))
            self.f.write("    int votes = 0;\n")
            for i in range(num_trees):
                self.f.write("""    votes += estimator_{funcname}_{est_num}(
    cl
    , rdb0_last_touched_diff
    , rdb0_act_ranking
    , rdb0_act_ranking_top_10
    ) < 1.0;\n""".format(est_num=i, funcname=self.funcname))
            self.f.write("    return votes >= %d;\n" % math.ceil(float(num_trees)/2.0))
            self.f.write("}\n")
            self.f.write("}\n")

        def recurse(self, left, right, threshold, features, node, tabs):
            tabsize = tabs*"    "
            if (threshold[node] != -2):
                feat_name = features[node]
                if feat_name[:3] == "cl.":
                    feat_name = feat_name[3:]
                feat_name = feat_name.replace(".", "_")
                if feat_name == "dump_no":
                    feat_name = "dump_number"

                if feat_name == "size":
                    feat_name = "cl->" + feat_name + "()"
                elif feat_name == "rdb0_last_touched_diff":
                    pass
                elif feat_name == "rdb0_act_ranking_top_10":
                    pass
                elif feat_name == "rdb0_act_ranking":
                    pass
                else:
                    feat_name = "cl->stats." + feat_name

                feat_name = feat_name.replace("cl->stats.rdb0_", "cl->stats.")

                self.f.write("{tabs}if ( {feat} <= {threshold}f ) {{\n".format(
                    tabs=tabsize,
                    feat=feat_name, threshold=str(threshold[node])))

                # recruse left
                if left[node] != -1:
                    self.recurse(left, right, threshold, features, left[node], tabs+1)

                self.f.write("{tabs}}} else {{\n".format(tabs=tabsize))

                # recurse right
                if right[node] != -1:
                    self.recurse(left, right, threshold, features, right[node], tabs+1)

                self.f.write("{tabs}}}\n".format(tabs=tabsize))
            else:
                x = self.value[node][0][0]
                y = self.value[node][0][1]
                if y == 0:
                    ratio = "1"
                else:
                    ratio = "%0.1f/%0.1f" % (x, y)

                self.f.write("{tabs}return {ratio};\n".format(
                    tabs=tabsize, ratio=ratio))

        def get_code(self, clf, starttab=0):
            left = clf.tree_.children_left
            right = clf.tree_.children_right
            threshold = clf.tree_.threshold
            if options.verbose:
                print("Node count:", clf.tree_.node_count)
                print("Left: %s Right: %s Threshold: %s" % (left, right, threshold))
                print("clf.tree_.feature:", clf.tree_.feature)
            features = [self.feat[i % len(self.feat)] for i in clf.tree_.feature]
            self.value = clf.tree_.value

            self.recurse(left, right, threshold, features, 0, starttab)

    def one_classifier(self, features, to_predict, final):
        _, df = sklearn.model_selection.train_test_split(self.df, test_size=options.only_pecr)
        print("================ predicting %s ================" % to_predict)
        print("-> Number of features  :", len(features))
        print("-> Number of datapoints:", df.shape)
        print("-> Predicting          :", to_predict)

        values2nums = {'luby': 0, 'glue': 1, 'geom': 2}
        df.loc[:, ('cl.cur_restart_type')] = df.loc[:, ('cl.cur_restart_type')].map(values2nums)
        train, test = sklearn.model_selection.train_test_split(df, test_size=0.33)
        X_train = train[features]
        y_train = train[to_predict]

        X_test = test[features]
        y_test = test[to_predict]

        t = time.time()
        clf = None
        # clf = sklearn.linear_model.LogisticRegression()
        if final:

            clf_tree = sklearn.tree.DecisionTreeClassifier(
                    max_depth=options.tree_depth,
                    min_samples_split=options.min_samples_split)

            clf_svm_pre = sklearn.svm.SVC(C=500, gamma=10**-5)
            clf_svm = sklearn.ensemble.BaggingClassifier(
                clf_svm_pre,
                n_estimators=3,
                max_samples=0.5, max_features=0.5)

            clf_logreg = sklearn.linear_model.LogisticRegression(
                C=0.3,
                penalty="l1")

            clf_forest = sklearn.ensemble.RandomForestClassifier(
                    n_estimators=5,
                    min_samples_leaf=options.min_samples_split)

            if options.final_is_tree:
                clf = clf_tree
            elif options.final_is_svm:
                clf = clf_svm
            elif options.final_is_logreg:
                clf = clf_logreg
            elif options.final_is_forest:
                clf = clf_forest
            else:
                mylist = [["tree", clf_tree], ["svm", clf_svm], ["logreg", clf_logreg]]
                clf = sklearn.ensemble.VotingClassifier(mylist)
        else:
            clf = sklearn.ensemble.RandomForestClassifier(
                n_estimators=80,
                min_samples_leaf=options.min_samples_split)

        clf.fit(X_train, y_train)

        print("Training finished. T: %-3.2f" % (time.time() - t))

        best_features = []
        if not final:
            importances = clf.feature_importances_
            std = np.std([tree.feature_importances_ for tree in clf.estimators_], axis=0)
            indices = np.argsort(importances)[::-1]
            indices = indices[:options.top_num_features]
            myrange = min(X_train.shape[1], options.top_num_features)

            # Print the feature ranking
            print("Feature ranking:")

            for f in range(myrange):
                print("%-3d  %-55s -- %8.4f" %
                      (f + 1, features[indices[f]], importances[indices[f]]))
                best_features.append(features[indices[f]])

            # Plot the feature importances of the clf
            plt.figure()
            plt.title("Feature importances")
            plt.bar(range(myrange), importances[indices],
                    color="r", align="center",
                    yerr=std[indices])
            plt.xticks(range(myrange), [features[x] for x in indices], rotation=45)
            plt.xlim([-1, myrange])

        if options.dot is not None and final:
            self.output_to_dot(clf, features)

        if options.basename is not None:
            c = self.CodeWriter(clf, features, self.funcname, self.fname)
            c.print_full_code()

        print("Calculating scores for test....")
        y_pred = clf.predict(X_test)
        accuracy = sklearn.metrics.accuracy_score(
            y_test, y_pred)
        precision = sklearn.metrics.precision_score(
            y_test, y_pred, average="macro")
        recall = sklearn.metrics.recall_score(
            y_test, y_pred, average="macro")
        print("test prec : %-3.4f  recall: %-3.4f accuracy: %-3.4f T: %-3.2f" % (
            precision, recall, accuracy, (time.time() - t)))

        print("Calculating scores for train....")
        y_pred_train = clf.predict(X_train)
        train_accuracy = sklearn.metrics.accuracy_score(
            y_train, y_pred_train)
        train_precision = sklearn.metrics.precision_score(
            y_train, y_pred_train, average="macro")
        train_recall = sklearn.metrics.recall_score(
            y_train, y_pred_train, average="macro")
        print("train prec: %-3.4f  recall: %-3.4f accuracy: %-3.4f" % (
            train_precision, train_recall, train_accuracy))

        if options.confusion:
            cnf_matrix = sklearn.metrics.confusion_matrix(
                y_true=y_test, y_pred=y_pred)

            np.set_printoptions(precision=2)

            # Plot non-normalized confusion matrix
            self.plot_confusion_matrix(
                cnf_matrix, classes=clf.classes_,
                title='Confusion matrix, without normalization -- test')

            # Plot normalized confusion matrix
            self.plot_confusion_matrix(
                cnf_matrix, classes=clf.classes_, normalize=True,
                title='Normalized confusion matrix -- test')

            cnf_matrix_train = sklearn.metrics.confusion_matrix(
                y_true=y_train, y_pred=y_pred_train)
            # Plot normalized confusion matrix
            self.plot_confusion_matrix(
                cnf_matrix_train, classes=clf.classes_, normalize=True,
                title='Normalized confusion matrix -- train')

        # TODO do L1 regularization

        if not final:
            return best_features
        else:
            return precision+recall+accuracy

    def remove_old_clause_features(self, features):
        todel = []
        for name in features:
            if "cl2" in name or "cl3" in name or "cl4" in name:
                todel.append(name)

        for x in todel:
            features.remove(x)
            if options.verbose:
                print("Removing old clause feature:", x)

    def rem_features(self, feat, to_remove):
        feat_less = list(feat)
        for feature in feat:
            for rem in to_remove:
                if rem in feature:
                    feat_less.remove(feature)
                    if options.verbose:
                        print("Removing feature from feat_less:", feature)

        return feat_less

    def calc_greedy_best_features(self, features):
        top_feats = self.one_classifier(features, "x.class", False)
        if options.show:
            plt.show()

        best_features = [top_feats[0]]
        for i in range(options.get_best_topn_feats-1):
            print("*** Round %d Best feature set until now: %s"
                  % (i, best_features))

            best_sum = 0.0
            best_feat = None
            feats_to_try = [i for i in top_feats if i not in best_features]
            print("Will try to get next best from ", feats_to_try)
            for feat in feats_to_try:
                this_feats = list(best_features)
                this_feats.append(feat)
                print("Trying feature set: ", this_feats)
                mysum = self.one_classifier(this_feats, "x.class", True)
                print("Reported mysum: ", mysum)
                if mysum > best_sum:
                    best_sum = mysum
                    best_feat = feat
                    print("-> Making this best accuracy")

            print("*** Best feature for round %d was: %s with mysum: %lf"
                  % (i, best_feat, mysum))
            best_features.append(best_feat)

            print("\n\n")
            print("Final best feature selection is: ", best_features)

        return best_features

    def learn(self):
        if options.check_row_data:
            self.check_too_large_or_nan_values(self.df)

        print("total samples: %5d" % self.df.shape[0])

        features = self.df.columns.values.flatten().tolist()
        features = self.rem_features(
            features, ["x.num_used", "x.class", "x.lifetime", "fname", "dump_no"])
        if options.no_rdb1:
            features = self.rem_features(features, ["rdb1", "rdb.rel"])
            features = self.rem_features(features, ["rdb.rel"])

        if True:
            self.remove_old_clause_features(features)

        if options.raw_data_plots:
            pd.options.display.mpl_style = "default"
            self.df.hist()
            self.df.boxplot()

        best_features = []
        if options.only_final:
            best_features = ['cl.glue_rel_long", "rdb0.used_for_uip_creation", "cl.glue_smaller_than_hist_lt", "cl.glue_smaller_than_hist_queue", "cl.overlap", "cl.glue_rel_queue", "cl.glue", "rdb0.dump_no", "cl.glue_rel", "cl.num_total_lits_antecedents", "cl.size", "cl.overlap_rel", "cl.num_overlap_literals", "rdb1.used_for_uip_creation", "cl.size_rel", "rdb0.last_touched_diff']

            best_features = ['cl.glue_rel_long", "rdb0.used_for_uip_creation", "cl.glue_smaller_than_hist_lt", "cl.glue_smaller_than_hist_queue", "cl.glue_rel_queue", "cl.glue", "cl.glue_rel", "cl.size", "cl.size_rel", "rdb1.used_for_uip_creation", "rdb0.dump_no']

            best_features = ['cl.glue_rel", "cl.backtrack_level_hist_lt", "rdb0.used_for_uip_creation", "cl.size_rel", "cl.overlap_rel", "cl.glue_rel_long']

            best_features = ['rdb0.used_for_uip_creation']
            best_features.append('rdb1.used_for_uip_creation')
            best_features.append('cl.size')
            best_features.append('cl.size_rel')
            best_features.append('cl.glue_rel_long')
            best_features.append('cl.glue_rel_queue')
            best_features.append('cl.glue')
            best_features.append('rdb0.act_ranking_top_10')
            best_features.append('rdb0.act_ranking')
            best_features.append('rdb0.last_touched_diff')
            #best_features.append('rdb1.act_ranking_top_10')
            #best_features.append('rdb1.act_ranking')
            #best_features.append('rdb1.last_touched_diff')
            #best_features.append('cl.num_antecedents_rel') # should we?
            best_features.append('cl.num_overlap_literals')
            #best_features.append('cl.num_overlap_literals_rel')

            #best_features.append('cl.cur_restart_type')

            if options.no_rdb1:
                best_features = self.rem_features(best_features, ["rdb.rel", "rdb1."])
        else:
            best_features = self.calc_greedy_best_features(features)

        self.one_classifier(best_features, "x.class", True)

        if options.show:
            plt.show()


class Clustering:
    def __init__(self, df):
        self.df = df

    def create_code_for_cluster_centers(self, clust, sz_feats):
        f = open("../src/clustering_{basename}.h".format(basename=options.basename), 'w')
        write_mit_header(f)

        sz_feats_clean = []
        for x in sz_feats:
            assert "szfeat_cur.conflicts" not in x

            #removing "szfeat_cur."
            c = x[11:]
            if c[:4] == "red_":
                c = c.replace("red_", "red_cl_distrib.")
            if c[:6] == "irred_":
                c = c.replace("irred_", "irred_cl_distrib.")
            sz_feats_clean.append(c)

        f.write("""
#ifndef CLUSTERING_{basename}_H
#define CLUSTERING_{basename}_H

#include "satzilla_features.h"
#include <cmath>

namespace CMSat {{
class Clustering_{basename} {{

public:
    Clustering_{basename}() {{
        set_up_centers();
    }}

    SatZillaFeatures center[{clusters}];

""".format(clusters=options.clusters, basename=options.basename))

        f.write("    void set_up_centers() {\n")
        for i in range(options.clusters):
            f.write("\n        // Doing cluster center %d\n" % i)
            for i2 in range(len(sz_feats_clean)):
                feat = sz_feats_clean[i2]
                center = clust.cluster_centers_[i][i2]
                f.write("        center[{num}].{feat} = {center};\n".format(
                    num=i, feat=feat, center=center))

        f.write("    }\n")

        f.write("""
    double sq(double x) const {
        return x*x;
    }

    double norm_dist(const SatZillaFeatures& a, const SatZillaFeatures& b) const {
        double dist = 0;
""")
        for feat in sz_feats_clean:
            f.write("        dist+=sq(a.{feat}-b.{feat});\n".format(feat=feat))

        f.write("""
        return dist;
    }\n""")

        f.write("""
    int which_is_closest(const SatZillaFeatures& p) {
        double closest_dist = std::numeric_limits<double>::max();
        int closest = -1;
        for (int i = 0; i < %d; i++) {
            double dist = norm_dist(center[i], p);
            if (dist < closest_dist) {
                closest_dist = dist;
                closest = i;
            }
        }
        return closest;
    }
""" % options.clusters)

        f.write("""
};


} //end namespace

#endif //header guard
""")

    def cluster(self):
        features = self.df.columns.values.flatten().tolist()

        # features from dataframe
        sz_all = []
        for x in features:
            if "szfeat_cur" in x:
                sz_all.append(x)
        print(sz_all)
        sz_all.remove("szfeat_cur.conflicts")
        sz_all.remove("szfeat_cur.var_cl_ratio")

        # fit to slice that only includes CNF features
        df2 = self.df[sz_all]
        clust = sklearn.cluster.KMeans(n_clusters=options.clusters)
        clust.fit(df2)

        # print distribution
        dist = {}
        for x in clust.labels_:
            if x not in dist:
                dist[x] = 1
            else:
                dist[x] += 1
        print(dist)

        # print information about the clusters
        if options.verbose:
            print(clust.labels_)
            print(clust.cluster_centers_)
            print(clust.get_params())
        self.create_code_for_cluster_centers(clust, sz_all)

        # predict based on the cluster
        self.df["clust"] = clust.labels_

        fnames = []
        functs = []
        for clust in range(options.clusters):
            funcname="should_keep_{basename}{clust}".format(clust=clust, basename=options.basename)
            functs.append(funcname)

            fname="final_predictor_{basename}{clust}.h".format(clust=clust, basename=options.basename)
            fnames.append(fname)

            learner = Learner(
                self.df[(self.df.clust == clust)],
                funcname,
                "../src/"+fname)
            learner.learn()

        f = open("../src/all_predictors_%s.h" % options.basename, "w")
        write_mit_header(f)
        f.write("""///auto-generated code. Under MIT license.
#ifndef ALL_PREDICTORS_{basename}_H
#define ALL_PREDICTORS_{basename}_H\n\n""".format(basename=options.basename))
        f.write('#include "clause.h"\n\n')
        for fname in fnames:
            f.write('#include "%s"\n' % fname)

        f.write("namespace CMSat {\n")
        f.write("typedef bool (*keep_func_type_%s)(const CMSat::Clause*, const uint32_t, const uint32_t, const uint32_t);\n" % options.basename)
        f.write("\nkeep_func_type_{basename} should_keep_{basename}_funcs[{clusters}] = {{\n".format(
            basename=options.basename, clusters=options.clusters))

        for i in range(len(functs)):
            func = functs[i];
            f.write("    CMSat::%s" % func)
            if i < len(functs)-1:
                f.write(",\n")
            else:
                f.write("\n")
        f.write("};\n\n")

        f.write("} //end namespace\n\n")
        f.write("#endif //ALL_PREDICTORS\n")


if __name__ == "__main__":
    usage = "usage: %prog [options] file.pandas"
    parser = optparse.OptionParser(usage=usage)

    parser.add_option("--verbose", "-v", action="store_true", default=False,
                      dest="verbose", help="Print more output")
    parser.add_option("--cross", action="store_true", default=False,
                      dest="cross_validate", help="Cross-validate prec/recall/acc against training data")
    parser.add_option("--depth", default=None, type=int,
                      dest="tree_depth", help="Depth of the tree to create")
    parser.add_option("--dot", type=str, default=None,
                      dest="dot", help="Create DOT file")
    parser.add_option("--conf", action="store_true", default=False,
                      dest="confusion", help="Create confusion matrix")
    parser.add_option("--show", action="store_true", default=False,
                      dest="show", help="Show visual graphs")
    parser.add_option("--check", action="store_true", default=False,
                      dest="check_row_data", help="Check row data for NaN or float overflow")
    parser.add_option("--rawplots", action="store_true", default=False,
                      dest="raw_data_plots", help="Display raw data plots")
    parser.add_option("--code", default=None, type=str,
                      dest="basename", help="Get raw C-like code into this function and file name")
    parser.add_option("--only", default=0.999, type=float,
                      dest="only_pecr", help="Only use this percentage of data")
    parser.add_option("--nordb1", default=False, action="store_true",
                      dest="no_rdb1", help="Delete RDB1 data")
    parser.add_option("--final", default=False, action="store_true",
                      dest="only_final", help="Only generate final predictor")
    parser.add_option("--split", default=80, type=int,
                      dest="min_samples_split", help="Split in tree if this many samples or above. Haved for forests, as there it's the leaf limit")
    parser.add_option("--greedybest", default=40, type=int,
                      dest="get_best_topn_feats", help="Greedy Best K top features from the top N features given by '--top N'")
    parser.add_option("--top", default=40, type=int,
                      dest="top_num_features", help="Top N features to take to generate the final predictor")
    parser.add_option("--clusters", default=7, type=int,
                      dest="clusters", help="How many clusters to use")

    parser.add_option("--tree", default=False, action="store_true",
                      dest="final_is_tree", help="Final predictor should be a tree")
    parser.add_option("--svm", default=False, action="store_true",
                      dest="final_is_svm", help="Final predictor should be an svm")
    parser.add_option("--lreg", default=False, action="store_true",
                      dest="final_is_logreg", help="Final predictor should be a logistic regression")
    parser.add_option("--forest", default=False, action="store_true",
                      dest="final_is_forest", help="Final predictor should be a forest")

    (options, args) = parser.parse_args()

    if len(args) < 1:
        print("ERROR: You must give the pandas file!")
        exit(-1)

    fname = args[0]
    with open(fname, "rb") as f:
        df = pickle.load(f)

        c = Clustering(df)
        c.cluster()
