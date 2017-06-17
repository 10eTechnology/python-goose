# -*- coding: utf-8 -*-
"""\
This is a python port of "Goose" orignialy licensed to Gravity.com
under one or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.

Python port was written by Xavier Grangier for Recrutae

Gravity.com licenses this file
to you under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from copy import deepcopy

from goose.extractors import BaseExtractor

KNOWN_ARTICLE_CONTENT_TAGS = [
    {'attr': 'itemprop', 'value': 'articleBody'},
    {'attr': 'class', 'value': 'post-content'},
    {'tag': 'article'},
]


class ContentExtractor(BaseExtractor):
    def get_language(self):
        """\
        Returns the language is by the article or
        the configuration language
        """
        # we don't want to force the target language
        # so we use the article.meta_lang
        if self.config.use_meta_language:
            if self.article.meta_lang:
                return self.article.meta_lang[:2]
        return self.config.target_language

    def get_known_article_tags(self):
        for item in KNOWN_ARTICLE_CONTENT_TAGS:
            nodes = self.parser.get_elements_by_tag(
                self.article.doc,
                **item)
            if len(nodes):
                return nodes[0]
        return None

    def is_articlebody(self, node):
        for item in KNOWN_ARTICLE_CONTENT_TAGS:
            # attribute
            if "attr" in item and "value" in item:
                if self.parser.get_attribute(node, item['attr']) == item['value']:
                    return True
            # tag
            if "tag" in item:
                if node.tag == item['tag']:
                    return True

        return False

    def calculate_best_node(self):

        doc = self.article.doc
        top_node = None
        nodes_to_check = self.nodes_to_check(doc)

        starting_boost = float(1.0)
        cnt = 0
        i = 0
        parent_nodes = []
        nodes_with_text = []

        for node in nodes_to_check:
            text_node = self.parser.get_text(node)
            word_stats = self.stopwords_class(language=self.get_language()).get_stopword_count(text_node)
            high_link_density = self.is_high_link_density(node)
            if word_stats.get_stopword_count() > 2 and not high_link_density:
                nodes_with_text.append(node)

        nodes_number = len(nodes_with_text)
        negative_scoring = 0
        bottom_negative_score_nodes = float(nodes_number) * 0.25

        for node in nodes_with_text:
            boost_score = float(0)
            # boost
            if self.is_boostable(node):
                if cnt >= 0:
                    boost_score = float((1.0 / starting_boost) * 50)
                    starting_boost += 1
            # nodes_number
            if nodes_number > 15:
                if float(nodes_number - i) <= bottom_negative_score_nodes:
                    booster = float(bottom_negative_score_nodes - (nodes_number - i))
                    boost_score = float(-pow(booster, float(2)))
                    neg_score = abs(boost_score) + negative_scoring
                    if neg_score > 40:
                        boost_score = float(5)

            text_node = self.parser.get_text(node)
            word_stats = self.stopwords_class(language=self.get_language()).get_stopword_count(text_node)
            upscore = int(word_stats.get_stopword_count() + boost_score)

            # parent node
            parent_node = self.parser.get_parent(node)
            self.update_score(parent_node, upscore)
            self.update_node_count(parent_node, 1)

            if parent_node not in parent_nodes:
                parent_nodes.append(parent_node)

            # grandparent node
            grandparent_node = self.parser.get_parent(parent_node)
            if grandparent_node is not None:
                self.update_node_count(grandparent_node, 1)
                self.update_score(grandparent_node, upscore / 2)
                if grandparent_node not in parent_nodes:
                    parent_nodes.append(grandparent_node)
            cnt += 1
            i += 1

        top_node_score = 0
        for e in parent_nodes:
            score = self.get_score(e)

            if score > top_node_score:
                top_node = e
                top_node_score = score

            if top_node is None:
                top_node = e

        return top_node

    def is_boostable(self, node):
        """\
        alot of times the first paragraph might be the caption under an image
        so we'll want to make sure if we're going to boost a parent node that
        it should be connected to other paragraphs,
        at least for the first n paragraphs so we'll want to make sure that
        the next sibling is a paragraph and has at
        least some substatial weight to it
        """
        para = "p"
        steps_away = 0
        minimum_stopword_count = 5
        max_stepsaway_from_node = 3

        nodes = self.walk_siblings(node)
        for current_node in nodes:
            # p
            current_node_tag = self.parser.get_tag(current_node)
            if current_node_tag == para:
                if steps_away >= max_stepsaway_from_node:
                    return False
                para_text = self.parser.get_text(current_node)
                word_stats = self.stopwords_class(language=self.get_language()).get_stopword_count(para_text)
                if word_stats.get_stopword_count() > minimum_stopword_count:
                    return True
                steps_away += 1
        return False

    def walk_siblings(self, node):
        current_sibling = self.parser.previous_sibling(node)
        b = []
        while current_sibling is not None:
            b.append(current_sibling)
            previous_sibling = self.parser.previous_sibling(current_sibling)
            current_sibling = None if previous_sibling is None else previous_sibling
        return b

    def add_siblings(self, top_node):
        # in case the extraction used known attributes
        # we don't want to add siblings
        if self.is_articlebody(top_node):
            return top_node
        baseline_score_siblings_para = self.get_siblings_score(top_node)
        results = self.walk_siblings(top_node)
        for current_node in results:
            ps = self.get_siblings_content(current_node, baseline_score_siblings_para)
            for p in ps.__iter__():
                top_node.insert(0, p)
        return top_node

    def get_siblings_content(self, current_sibling, baselinescore_siblings_para):
        """\
        adds any siblings that may have a decent score to this node
        """
        if current_sibling.tag == 'p' and len(self.parser.get_text(current_sibling)) > 0:
            e0 = current_sibling
            if e0.tail:
                e0 = deepcopy(e0)
                e0.tail = ''
            return [e0]
        else:
            potential_paragraphs = self.parser.get_elements_by_tag(current_sibling, tag='p')
            if potential_paragraphs is None:
                return None
            else:
                ps = []
                for first_paragraph in potential_paragraphs:
                    text = self.parser.get_text(first_paragraph)
                    if len(text) > 0:
                        word_stats = self.stopwords_class(language=self.get_language()).get_stopword_count(text)
                        paragraph_score = word_stats.get_stopword_count()
                        sibling_baseline_score = float(.30)
                        high_link_density = self.is_high_link_density(first_paragraph)
                        score = float(baselinescore_siblings_para * sibling_baseline_score)
                        if score < paragraph_score and not high_link_density:
                            p = self.parser.create_element(tag='p', text=text, tail=None)
                            ps.append(p)
                return ps

    def get_siblings_score(self, top_node):
        """\
        we could have long articles that have tons of paragraphs
        so if we tried to calculate the base score against
        the total text score of those paragraphs it would be unfair.
        So we need to normalize the score based on the average scoring
        of the paragraphs within the top node.
        For example if our total score of 10 paragraphs was 1000
        but each had an average value of 100 then 100 should be our base.
        """
        base = 100000
        paragraphs_number = 0
        paragraphs_score = 0
        nodes_to_check = self.parser.get_elements_by_tag(top_node, tag='p')

        for node in nodes_to_check:
            text_node = self.parser.get_text(node)
            word_stats = self.stopwords_class(language=self.get_language()).get_stopword_count(text_node)
            high_link_density = self.is_high_link_density(node)
            if word_stats.get_stopword_count() > 2 and not high_link_density:
                paragraphs_number += 1
                paragraphs_score += word_stats.get_stopword_count()

        if paragraphs_number > 0:
            base = paragraphs_score / paragraphs_number

        return base

    def update_score(self, node, add_to_score):
        """\
        adds a score to the gravityScore Attribute we put on divs
        we'll get the current score then add the score
        we're passing in to the current
        """
        current_score = 0
        score_string = self.parser.get_attribute(node, 'gravityScore')
        if score_string:
            current_score = int(score_string)

        new_score = current_score + add_to_score
        self.parser.set_attribute(node, "gravityScore", str(new_score))

    def update_node_count(self, node, add_to_count):
        """\
        stores how many decent nodes are under a parent node
        """
        current_score = 0
        count_string = self.parser.get_attribute(node, 'gravityNodes')
        if count_string:
            current_score = int(count_string)

        new_score = current_score + add_to_count
        self.parser.set_attribute(node, "gravityNodes", str(new_score))

    def is_high_link_density(self, e):
        """\
        checks the density of links within a node,
        is there not much text and most of it contains linky shit?
        if so it's no good
        """
        links = self.parser.get_elements_by_tag(e, tag='a')
        if links is None or len(links) == 0:
            return False

        text = self.parser.get_text(e)
        words = text.split(' ')
        words_number = float(len(words))
        sb = []
        for link in links:
            sb.append(self.parser.get_text(link))

        link_text = ''.join(sb)
        link_words = link_text.split(' ')
        number_of_link_words = float(len(link_words))
        number_of_links = float(len(links))
        link_divisor = float(number_of_link_words / words_number)
        score = float(link_divisor * number_of_links)
        if score >= 1.0:
            return True
        return False
        # return True if score > 1.0 else False

    def get_score(self, node):
        """\
        returns the gravityScore as an integer from this node
        """
        return self.get_node_gravity_score(node) or 0

    def get_node_gravity_score(self, node):
        grv_score_string = self.parser.get_attribute(node, 'gravityScore')
        if not grv_score_string:
            return None
        return int(grv_score_string)

    def nodes_to_check(self, doc):
        """\
        returns a list of nodes we want to search
        on like paragraphs and tables
        """
        nodes_to_check = []

        for tag in ['p', 'pre', 'td']:
            items = self.parser.get_elements_by_tag(doc, tag=tag)
            nodes_to_check += items
        return nodes_to_check

    def is_table_and_no_para_exist(self, e):
        sub_paragraphs = self.parser.get_elements_by_tag(e, tag='p')
        for p in sub_paragraphs:
            txt = self.parser.get_text(p)
            if len(txt) < 25:
                self.parser.remove(p)

        sub_paragraphs2 = self.parser.get_elements_by_tag(e, tag='p')
        if len(sub_paragraphs2) == 0 and e.tag != "td":
            return True
        return False

    def is_node_score_threshold_met(self, node, e):
        top_node_score = self.get_score(node)
        current_node_score = float(self.get_score(e))
        threshold_score = float(top_node_score * .08)

        if (current_node_score < threshold_score) and e.tag != 'td':
            return False
        return True

    def post_cleanup(self):
        """\
        remove any divs that looks like non-content,
        clusters of links, or paras with no gusto
        """
        target_node = self.article.top_node
        node = self.add_siblings(target_node)
        for e in self.parser.get_children(node):
            e_tag = self.parser.get_tag(e)
            if e_tag != 'p':
                if self.is_high_link_density(e) \
                        or self.is_table_and_no_para_exist(e) \
                        or not self.is_node_score_threshold_met(node, e):
                    self.parser.remove(e)
        return node


class StandardContentExtractor(ContentExtractor):
    pass
