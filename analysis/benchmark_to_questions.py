"""Turn the Benchmark_Suite gold set into a questions file the harness can run.

The suite stores each content point as a sentence of prose. The harness scores
with regexes. Converting one into the other is not uniformly safe, so each
element is routed to whichever scorer can actually judge it:

- an element carrying numbers, units or identifiers becomes a regex facet, and
  every extracted token has to appear, not just one of them. Matching any one
  token would award '82 +/- 2% (SEM)' to an answer that said only '82%', which
  drops exactly the uncertainty the suite says to preserve.
- everything else becomes a judge facet, holding the gold sentence itself. A
  claim about mechanism or polarity cannot be pattern matched without
  penalising paraphrase, which the suite forbids.

The generated regexes are meant to be read before they are trusted. Run
score.py afterwards: it checks every pattern against the paper and reports the
ones that no longer match.
"""

import argparse
import glob
import json
import os
import re

# Units that appear in this corpus. A bare number is ambiguous, so a number is
# only worth matching on when it carries one of these or sits in an identifier.
# A unit is matched by the family it belongs to, because the gold and the paper
# rarely spell one the same way: the gold says '20 seconds' where the paper says
# '20 s'. Single letters that are not units in their own right are left out
# entirely; 'n' used to swallow the n of '91 neurites' and produce a pattern
# that matched nothing.
UNIT_FAMILIES = [
    (["nm"], r"nm"),
    (["um", "µm", "micron", "microns", "micrometer"], r"(?:um|µm|micron|micrometer)"),
    (["mm"], r"mm"),
    (["cm"], r"cm"),
    (["%", "percent"], r"(?:%|percent)"),
    (["ms", "millisecond", "milliseconds"], r"(?:ms|millisecond)"),
    (["sec", "secs", "second", "seconds"], r"(?:s|sec|secs|second|seconds)"),
    (["min", "minute", "minutes"], r"(?:min|minute|minutes)"),
    (["hr", "hour", "hours"], r"(?:h|hr|hour|hours)"),
    (["mM"], r"mM"),
    (["uM", "µM"], r"(?:uM|µM)"),
    (["nM"], r"nM"),
    (["kDa"], r"kDa"),
    (["ug", "µg", "microgram"], r"(?:ug|µg|microgram)"),
    (["mg"], r"mg"),
    (["ml"], r"ml"),
    (["ul", "µl"], r"(?:ul|µl)"),
    (["fold"], r"fold"),
    (["wk", "week", "weeks"], r"(?:wk|week|weeks)"),
    (["d", "day", "days"], r"(?:d|day|days)"),
]

# Words that carry the uncertainty or the statistic, which the suite treats as
# part of the content point rather than decoration.
STATISTICS = ["SEM", "SD", "SE", "s.e.m", "s.d", "P value", "P <", "P =", "n ="]

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# Atg5, LC3, GFP-LC3, p62, Rab7, NS060698, DRG. Letters and digits together, or
# an all-caps run of three or more.
IDENTIFIER = re.compile(r"\b(?:[A-Za-z]+[-/]?[A-Za-z]*\d+[A-Za-z]*|[A-Z]{3,})\b")

# Identifier-looking tokens that are really just words.
NOT_IDENTIFIERS = {
    "THE", "AND", "FOR", "WITH", "WAS", "WERE", "NOT", "ARE", "HAS", "HAD",
    "THAT", "THIS", "FROM", "INTO", "ALSO", "BUT", "ALL", "ONE", "TWO",
    "NIH", "DNA", "RNA", "PBS", "FBS",
}


def normalize_locator(locator):
    """Put a gold XPath into the shape units.json uses for provenance.

    The gold writes '/article/body/sec[2]/sec[1]/p[5]' and the parser writes
    'article[1]/body[1]/sec[2]/sec[1]/p[5]'. The only differences are the
    leading slash and the implicit [1] on a step that has no index.
    """
    steps = []
    for step in locator.strip("/").split("/"):
        if not step:
            continue
        if "[" not in step:
            step = step + "[1]"
        steps.append(step)
    return "/".join(steps)


def load_units(workspace):
    path = os.path.join(workspace, "units.json")
    with open(path) as handle:
        return json.load(handle)



def corpus_text(workspace):
    """Everything any condition could retrieve: abstract, sections, and every
    unit, which is what brings in figure captions and references."""
    parts = []
    metadata_path = os.path.join(workspace, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path) as handle:
            parts.append(json.load(handle).get("abstract_text", ""))
    for path in sorted(glob.glob(os.path.join(workspace, "sections", "*.md"))):
        with open(path) as handle:
            parts.append(handle.read())
    for unit in load_units(workspace):
        parts.append(unit["text"])
    return "\n".join(parts)


def section_for_locator(locator, units):
    """Which section id holds the paragraph this gold element came from.

    Matches on provenance, then falls back to the nearest ancestor, because the
    gold sometimes points at a paragraph the parser merged or skipped.
    """
    wanted = normalize_locator(locator)

    for unit in units:
        if unit.get("provenance") == wanted and unit.get("section"):
            return unit["section"]

    # Walk up the path: a locator for p[5] still tells us which sec it is in.
    steps = wanted.split("/")
    while len(steps) > 1:
        steps.pop()
        prefix = "/".join(steps)
        for unit in units:
            provenance = unit.get("provenance") or ""
            if provenance.startswith(prefix) and unit.get("section"):
                return unit["section"]

    if wanted.startswith("article[1]/front[1]"):
        return "abstract"
    return None


def quoted(text):
    """A regex matching this literal, tolerant about runs of whitespace."""
    return r"\s+".join(re.escape(word) for word in text.split())


def number_patterns(element):
    """One pattern per number, carrying its unit when it has one."""
    patterns = []
    for match in NUMBER.finditer(element):
        # A number glued to letters is part of a name, not a measurement.
        # 'LC3' and 'PMC3283992' have no word boundary before the digits, so a
        # pattern built from the digits alone could never match anything.
        before = element[match.start() - 1] if match.start() > 0 else " "
        after = element[match.end()] if match.end() < len(element) else " "
        if before.isalnum() or after.isalpha():
            continue

        number = match.group()
        tail = element[match.end():].lstrip()

        unit_pattern = None
        for spellings, family in UNIT_FAMILIES:
            for spelling in sorted(spellings, key=len, reverse=True):
                if tail.lower().startswith(spelling.lower()):
                    unit_pattern = family
                    break
            if unit_pattern:
                break

        # Allow a thousands separator to be written either way, and let a
        # number be followed by its unit with or without a space.
        digits = re.escape(number).replace(",", "[,.]?")
        if unit_pattern:
            # Not \b: a word boundary cannot exist after '%', so '2\s*%\b'
            # would never match '2%'. A negative lookahead works for both a
            # symbol and a word, and still stops 'sec' matching 'section'.
            patterns.append(digits + r"\s*" + unit_pattern + r"(?!\w)")
        else:
            patterns.append(r"\b" + digits + r"\b")
    return patterns


def identifier_patterns(element):
    patterns = []
    for match in IDENTIFIER.finditer(element):
        token = match.group()
        if token.upper() in NOT_IDENTIFIERS:
            continue
        if NUMBER.fullmatch(token):
            continue
        # Atg5 and Atg-5 and atg 5 are the same name.
        loose = re.escape(token).replace(r"\-", r"[\s-]?")
        patterns.append(r"\b" + loose + r"\b")
    return patterns


def statistic_patterns(element):
    """At most one pattern: the longest statistic the element mentions.

    'SEM' also contains 'SE', and with require 'all' the shorter one adds no
    constraint while making the facet harder to read.
    """
    found = []
    for word in STATISTICS:
        if word.lower() in element.lower():
            found.append(word)
    if not found:
        return []

    longest = max(found, key=len)
    return [re.escape(longest).replace(r"\ ", r"\s*")]


# An element that restates one quantity, '800 nm (0.8 µm)', or offers a choice
# of them, 'every 2, 3 or 5 seconds', is still a single content point. Its
# numbers are alternatives, so requiring all of them would demand the answer
# repeat every spelling.
RESTATEMENT = re.compile(r"\(\s*[^)]*\d[^)]*\)|\d[^.]{0,20}\bor\b[^.]{0,20}\d")


def numbers_are_alternatives(element):
    return bool(RESTATEMENT.search(element))


def regex_facet(element):
    """Patterns for one element, or None when it should go to the judge."""
    numbers = number_patterns(element)
    if len(numbers) > 1 and numbers_are_alternatives(element):
        numbers = ["(?:" + "|".join(numbers) + ")"]

    patterns = []
    patterns.extend(numbers)
    patterns.extend(identifier_patterns(element))

    # 'SEM' is picked up as an identifier too, being three capitals, so only add
    # the statistic when nothing already matches it.
    for pattern in statistic_patterns(element):
        covered = False
        for existing in patterns:
            if re.search(existing, element, re.I) and re.search(pattern, element, re.I):
                if re.search(existing, re.sub(r"\\b", "", pattern), re.I):
                    covered = True
                    break
        if not covered:
            patterns.append(pattern)

    # Drop duplicates but keep the order, so a reviewer reads them in the order
    # they appear in the element.
    unique = []
    for pattern in patterns:
        if pattern not in unique:
            unique.append(pattern)

    if not unique:
        return None
    return unique


def facet_id(question_id, index):
    return f"{question_id}_e{index + 1}"


def convert(gold_rows, units, track, include_unanswerable, corpus=None,
            drop_unfindable=False, workspace=None):
    questions = []
    counts = {"regex": 0, "judge": 0, "unmapped_section": 0, "unfindable": 0}

    for row in gold_rows:
        if track != "all" and row["input_track"] != track:
            continue
        if not row["answerable"] and not include_unanswerable:
            continue

        # Every element of a question shares its evidence, so resolve the
        # section once.
        section = None
        for source in row["sources"]:
            if source["source_id"] != "XML":
                continue
            section = section_for_locator(source["locator"], units)
            if section:
                break
        if not section:
            section = "abstract"
            counts["unmapped_section"] += 1

        facets = []
        for index, element in enumerate(row["answer_elements"]):
            patterns = regex_facet(element)
            facet = {
                "id": facet_id(row["id"], index),
                "element": element,
                "source_section": section,
            }
            if patterns:
                facet["scoring"] = "regex"
                facet["require"] = "all"
                facet["patterns"] = patterns

                # A pattern absent from the corpus cannot be reached by any
                # condition, so leaving it in the denominator penalises every
                # system for something the paper does not say. The gold is
                # partly drawn from the PDF, which this workspace does not
                # have, and front matter is not indexed at all.
                if corpus is not None:
                    unreachable = [pattern for pattern in patterns
                                   if not re.search(pattern, corpus, re.I)]
                    if unreachable:
                        counts["unfindable"] += 1
                        if drop_unfindable:
                            continue
                        facet["unfindable"] = True
                counts["regex"] += 1
            else:
                facet["scoring"] = "judge"
                counts["judge"] += 1
            facets.append(facet)

        if not facets:
            continue

        questions.append({
            "id": row["id"],
            # Named per question as well as for the file, so the paper travels
            # with the question whatever flags the harness is given.
            "workspace": workspace,
            "question": row["question"],
            "reference_answer": row["reference_answer"],
            "category": row["category"],
            "capability": row["capability"],
            "answerable": row["answerable"],
            "evidence_location": row["evidence_location"],
            "facets": facets,
        })

    return questions, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold",
                        default="Benchmark_Suite/benchmark/PMC3283992_gold.jsonl")
    parser.add_argument("--workspace", default="papers/maday2012",
                        help="needed to map gold XPaths onto section ids")
    parser.add_argument("--track", default="XML",
                        choices=["XML", "XML+supplement", "all"],
                        help="XML is the 159-item subset that needs no supplement")
    parser.add_argument("--include-unanswerable", action="store_true",
                        help="keep the abstention questions, which coverage "
                             "cannot score; they need their own report")
    parser.add_argument("--drop-unfindable", action="store_true",
                        help="leave out facets whose patterns appear nowhere in "
                             "the corpus, instead of only flagging them")
    parser.add_argument("--out", default="analysis/questions_benchmark.json")
    args = parser.parse_args()

    with open(args.gold) as handle:
        gold_rows = [json.loads(line) for line in handle if line.strip()]

    units = load_units(args.workspace)
    questions, counts = convert(gold_rows, units, args.track,
                                args.include_unanswerable,
                                corpus=corpus_text(args.workspace),
                                drop_unfindable=args.drop_unfindable,
                                workspace=args.workspace)

    points = sum(len(question["facets"]) for question in questions)
    document = {
        "_comment": (
            f"Generated by benchmark_to_questions.py from {os.path.basename(args.gold)}, "
            f"track {args.track}. Each facet is one content point from the suite's "
            "answer_elements. Facets scored by regex list the patterns, and every "
            "pattern has to match; facets scored by judge carry the gold sentence "
            "instead. Do not edit by hand, regenerate."
        ),
        "workspace": args.workspace,
        "source_benchmark": args.gold,
        "track": args.track,
        "questions": questions,
    }

    with open(args.out, "w") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")

    print(f"{len(questions)} questions, {points} content points -> {args.out}")
    print(f"  regex facets {counts['regex']}, judge facets {counts['judge']}")
    if counts["unfindable"]:
        verb = "dropped" if args.drop_unfindable else "flagged"
        print(f"  {counts['unfindable']} regex facets {verb} as unfindable in "
              "the corpus")
    if counts["unmapped_section"]:
        print(f"  {counts['unmapped_section']} questions had no mappable section, "
              "defaulted to abstract")


if __name__ == "__main__":
    main()
