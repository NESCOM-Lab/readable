#!/usr/bin/env python3
"""Find the passages of a paper closest in meaning to a query.

The counterpart to 'pgraph query search', which only matches substrings. Every
hit keeps its section id and provenance, so a hit can be read in full with
'pgraph query section <id>'.
"""

import argparse
import json
import os

from ollama_client import cosine, embed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_index(workspace):
    units_path = os.path.join(workspace, "units.json")
    vectors_path = os.path.join(workspace, "embeddings.json")

    for path, step in [(units_path, "pgraph index"), (vectors_path, "analysis/embed.py")]:
        if not os.path.exists(path):
            raise SystemExit(f"missing {os.path.basename(path)}; run '{step}' first")

    with open(units_path) as handle:
        units = json.load(handle)
    with open(vectors_path) as handle:
        cached = json.load(handle)

    if len(cached["vectors"]) != len(units):
        raise SystemExit("units.json and embeddings.json disagree; rerun analysis/embed.py")

    return units, cached["vectors"]


def search(query, units, vectors, count, section=None, origin=None, with_citations=False):
    """Rank units by cosine similarity to the query, filtered if asked.

    Reference entries are left out unless asked for. A reference title is dense
    topical text that matches a question well while saying nothing about this
    paper, so in the pool by default they crowd out the real answer.
    """
    wanted = []
    for index, unit in enumerate(units):
        if origin and unit["origin"] != origin:
            continue
        if unit["origin"] == "citation" and not (with_citations or origin == "citation"):
            continue
        # Match against the whole ancestor chain, so a parent id like the
        # Methods section finds the units in its subsections. Those parents
        # usually own no paragraphs themselves, so matching 'section' alone
        # would quietly return nothing.
        if section and section not in unit.get("section_path", []):
            continue
        wanted.append(index)

    if not wanted:
        return [], 0

    query_vector = embed(query)
    scored = sorted(wanted, key=lambda index: cosine(query_vector, vectors[index]), reverse=True)

    hits = []
    for index in scored[:count]:
        unit = units[index]
        hits.append({
            "id": unit["id"],
            "origin": unit["origin"],
            "section": unit.get("section"),
            "location": unit.get("location"),
            "provenance": unit["provenance"],
            "citations": unit.get("citations", []),
            "score": round(cosine(query_vector, vectors[index]), 3),
            "text": unit["text"],
        })
    return hits, len(wanted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=5, help="how many hits to show")
    parser.add_argument("--in", dest="section",
                        help="restrict to a section id and everything under it")
    parser.add_argument("--origin", help="restrict to body, abstract, figure, table or citation")
    parser.add_argument("--with-citations", action="store_true",
                        help="also search the reference list")
    args = parser.parse_args()

    units, vectors = load_index(args.workspace)
    hits, searched = search(args.query, units, vectors, args.k, args.section,
                            args.origin, args.with_citations)

    print(json.dumps({"searched": searched, "shown": len(hits), "hits": hits}, indent=2))


if __name__ == "__main__":
    main()
