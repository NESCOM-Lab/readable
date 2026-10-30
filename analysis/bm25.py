#!/usr/bin/env python3
"""BM25 ranking over the same retrieval units the other conditions use.

The evaluation spec asks for a sparse lexical baseline alongside the dense
ones, to show how much of a result comes from embeddings rather than from term
overlap. The usual library for this cannot be installed into a managed Python,
and Okapi BM25 is short enough to write out, so it lives here where the
parameters are visible.
"""

import math
import re

# The standard Okapi settings. k1 controls how fast term frequency saturates,
# b how strongly a long passage is penalised for its length.
K1 = 1.5
B = 0.75

WORD = re.compile(r"[a-z0-9]+")


def tokenize(text):
    return WORD.findall(text.lower())


class Index:
    def __init__(self, documents):
        self.documents = [tokenize(text) for text in documents]
        self.lengths = [len(document) for document in self.documents]
        self.average_length = sum(self.lengths) / len(self.documents) if self.documents else 0.0

        self.frequencies = []
        appearances = {}
        for document in self.documents:
            counts = {}
            for word in document:
                counts[word] = counts.get(word, 0) + 1
            self.frequencies.append(counts)
            for word in counts:
                appearances[word] = appearances.get(word, 0) + 1

        total = len(self.documents)
        self.inverse_frequency = {}
        for word, seen_in in appearances.items():
            self.inverse_frequency[word] = math.log(1 + (total - seen_in + 0.5) / (seen_in + 0.5))

    def score(self, query, number):
        """Indexes of the top scoring documents, best first."""
        words = tokenize(query)
        scores = []
        for position, counts in enumerate(self.frequencies):
            total = 0.0
            length = self.lengths[position]
            for word in words:
                if word not in counts:
                    continue
                frequency = counts[word]
                weight = frequency * (K1 + 1) / (
                    frequency + K1 * (1 - B + B * length / (self.average_length or 1))
                )
                total += self.inverse_frequency.get(word, 0.0) * weight
            scores.append((total, position))

        scores.sort(key=lambda pair: (-pair[0], pair[1]))
        return [position for total, position in scores[:number] if total > 0]
