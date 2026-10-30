//! Read-only queries over a parsed paper.
//!
//! Every subcommand takes a 'path' that is either a workspace directory
//! (produced by 'parse') or a JATS XML file, loads the paper, and prints the
//! answer as JSON on stdout so it is easy to consume programmatically.

use std::path::{Path, PathBuf};

use clap::Subcommand;
use serde::Serialize;

use crate::jats;
use crate::model::{Paper, Section};
use crate::workspace;

#[derive(Subcommand)]
pub enum Query {
    /// Print the paper metadata as JSON.
    Metadata { path: PathBuf },
    /// Print the section outline (ids and titles, no body text) as JSON.
    Outline { path: PathBuf },
    /// Print one section and its subsections as JSON, found by its id.
    Section { path: PathBuf, id: String },
    /// List the figures as JSON.
    Figures { path: PathBuf },
    /// List the tables as JSON.
    Tables { path: PathBuf },
    /// List the citations as JSON.
    Citations { path: PathBuf },
    /// Search the paper (case-insensitive) and print the matches.
    Search {
        path: PathBuf,
        pattern: String,
        /// Characters of surrounding text to show on each side of a match.
        #[arg(long, default_value_t = 300)]
        context: usize,
        /// Stop after this many matches, so a common word cannot flood the output.
        #[arg(long, default_value_t = 40)]
        limit: usize,
    },
}

/// A section without its body text, so the tree can be shown at a glance.
#[derive(Serialize)]
struct OutlineNode {
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    /// Workspace file stem, which 'section' accepts in place of the id.
    file: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    title: Option<String>,
    paragraphs: usize,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    subsections: Vec<OutlineNode>,
}

/// One piece of text a search looks at, labelled with where it came from.
struct Searchable {
    origin: &'static str,
    location: Option<String>,
    text: String,
    provenance: String,
}

/// One match, with a window of surrounding text.
#[derive(Serialize)]
struct SearchHit {
    /// "abstract", "body", "figure", "table" or "citation".
    origin: &'static str,
    /// Section title, figure label, or citation id, depending on the origin.
    #[serde(skip_serializing_if = "Option::is_none")]
    location: Option<String>,
    provenance: String,
    snippet: String,
}

/// Matches found, and how many of them are shown. 'note' spells out an empty
/// or clipped result so it does not read as 'nothing to find'.
#[derive(Serialize)]
struct SearchResults {
    matches: usize,
    shown: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    note: Option<String>,
    hits: Vec<SearchHit>,
}

pub fn run(query: &Query) -> Result<(), String> {
    match query {
        Query::Metadata { path } => {
            let paper = load(path)?;
            print_json(&paper.metadata)
        }
        Query::Outline { path } => {
            let paper = load(path)?;
            print_json(&outline(&paper.body.sections))
        }
        Query::Section { path, id } => {
            let paper = load(path)?;
            match find_section(&paper.body.sections, id) {
                Some(section) => print_json(section),
                None => Err(format!(
                    "no section matching '{id}'; run 'outline' for the ids and file names"
                )),
            }
        }
        Query::Figures { path } => {
            let paper = load(path)?;
            print_json(&paper.body.figures)
        }
        Query::Tables { path } => {
            let paper = load(path)?;
            print_json(&paper.body.tables)
        }
        Query::Citations { path } => {
            let paper = load(path)?;
            print_json(&paper.body.citations)
        }
        Query::Search {
            path,
            pattern,
            context,
            limit,
        } => {
            let paper = load(path)?;
            print_json(&search(&paper, pattern, *context, *limit))
        }
    }
}

/// Load a paper from a workspace directory (via its 'paper.jats.xml') or from a
/// JATS XML file directly.
pub(crate) fn load(path: &Path) -> Result<Paper, String> {
    let xml_path = if path.is_dir() {
        path.join("paper.jats.xml")
    } else {
        path.to_path_buf()
    };

    let xml = std::fs::read_to_string(&xml_path)
        .map_err(|error| format!("could not read {}: {error}", xml_path.display()))?;

    let source = xml_path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| xml_path.display().to_string());

    jats::parse(&xml, &source)
}

fn print_json<T: Serialize>(value: &T) -> Result<(), String> {
    let json = serde_json::to_string_pretty(value)
        .map_err(|error| format!("could not serialize result: {error}"))?;
    println!("{json}");
    Ok(())
}

/// Build the outline tree, dropping paragraph text but keeping its count.
fn outline(sections: &[Section]) -> Vec<OutlineNode> {
    let mut nodes = Vec::new();
    for (index, section) in sections.iter().enumerate() {
        nodes.push(OutlineNode {
            id: section.id.clone(),
            file: workspace::section_file_stem(section, index + 1),
            title: section.title.clone(),
            paragraphs: section.paragraphs.len(),
            subsections: outline(&section.subsections),
        });
    }
    nodes
}

/// Depth-first search for a section, including subsections. The needle may be
/// the JATS id ("Sec2"), the workspace file stem ("sec2_results", with or
/// without the ".md"), or just the slugified title ("results") — the README and
/// the outline advertise different ones, and all of them should work.
fn find_section<'a>(sections: &'a [Section], needle: &str) -> Option<&'a Section> {
    let needle = workspace::slugify(needle.trim_end_matches(".md"));

    for (index, section) in sections.iter().enumerate() {
        let id = section.id.as_deref().map(workspace::slugify);
        let title = section.title.as_deref().map(workspace::slugify);
        let stem = workspace::section_file_stem(section, index + 1);

        if id.as_deref() == Some(needle.as_str())
            || title.as_deref() == Some(needle.as_str())
            || stem == needle
        {
            return Some(section);
        }
        if let Some(found) = find_section(&section.subsections, &needle) {
            return Some(found);
        }
    }
    None
}

/// Search everything in the paper: the abstract, body paragraphs, figure and
/// table captions, and the reference list.
fn search(paper: &Paper, pattern: &str, context: usize, limit: usize) -> SearchResults {
    let needle = pattern.to_lowercase();
    let mut hits = Vec::new();
    let mut matches = 0;

    for item in searchable(paper) {
        for (start, end) in find_all(&item.text, &needle) {
            matches += 1;
            if hits.len() < limit {
                hits.push(SearchHit {
                    origin: item.origin,
                    location: item.location.clone(),
                    provenance: item.provenance.clone(),
                    snippet: snippet(&item.text, start, end, context),
                });
            }
        }
    }

    let note = if matches == 0 {
        Some(format!(
            "no match for '{pattern}'; this is a plain substring search, so try a \
             shorter word or read a section from 'outline'"
        ))
    } else if matches > hits.len() {
        Some(format!("showing {} of {matches} matches; narrow the pattern to see the rest", hits.len()))
    } else {
        None
    };

    SearchResults {
        matches,
        shown: hits.len(),
        note,
        hits,
    }
}

/// Everything worth searching, in the order a reader would meet it.
fn searchable(paper: &Paper) -> Vec<Searchable> {
    let mut items = Vec::new();

    if let Some(abstract_text) = &paper.metadata.abstract_text {
        items.push(Searchable {
            origin: "abstract",
            location: None,
            text: abstract_text.clone(),
            provenance: "article/front/abstract".to_string(),
        });
    }

    collect_section_text(&paper.body.sections, &mut items);

    for figure in &paper.body.figures {
        if let Some(caption) = &figure.caption {
            items.push(Searchable {
                origin: "figure",
                location: figure.label.clone().or_else(|| figure.id.clone()),
                text: caption.clone(),
                provenance: figure.provenance.clone(),
            });
        }
    }

    for table in &paper.body.tables {
        if let Some(caption) = &table.caption {
            items.push(Searchable {
                origin: "table",
                location: table.label.clone().or_else(|| table.id.clone()),
                text: caption.clone(),
                provenance: table.provenance.clone(),
            });
        }
    }

    for citation in &paper.body.citations {
        items.push(Searchable {
            origin: "citation",
            location: citation.id.clone(),
            text: citation.text.clone(),
            provenance: citation.provenance.clone(),
        });
    }

    items
}

fn collect_section_text(sections: &[Section], items: &mut Vec<Searchable>) {
    for section in sections {
        for paragraph in &section.paragraphs {
            items.push(Searchable {
                origin: "body",
                location: section.title.clone(),
                text: paragraph.text.clone(),
                provenance: paragraph.provenance.clone(),
            });
        }
        collect_section_text(&section.subsections, items);
    }
}

/// Byte ranges of every case-insensitive occurrence of `needle` (already
/// lowercased) in `text`. Lowercasing can change how many bytes a character
/// takes, so offsets found in a lowered copy are mapped back to the original.
fn find_all(text: &str, needle: &str) -> Vec<(usize, usize)> {
    let mut ranges = Vec::new();
    if needle.is_empty() {
        return ranges;
    }

    // Remember which original offset each byte of the lowered copy came from.
    let mut lowered = String::with_capacity(text.len());
    let mut origins = Vec::with_capacity(text.len() + 1);
    for (offset, character) in text.char_indices() {
        for lowered_char in character.to_lowercase() {
            let before = lowered.len();
            lowered.push(lowered_char);
            for _ in before..lowered.len() {
                origins.push(offset);
            }
        }
    }
    origins.push(text.len());

    let mut from = 0;
    while let Some(found) = lowered[from..].find(needle) {
        let start = from + found;
        let end = start + needle.len();
        ranges.push((origins[start], origins[end]));
        from = end;
    }

    ranges
}

/// A window of text around a match, with an ellipsis when it is clipped.
fn snippet(text: &str, match_start: usize, match_end: usize, context: usize) -> String {
    let start = clamp_to_char_boundary(text, match_start.saturating_sub(context), false);
    let end = clamp_to_char_boundary(text, (match_end + context).min(text.len()), true);

    let mut result = String::new();
    if start > 0 {
        result.push('…');
    }
    result.push_str(&text[start..end]);
    if end < text.len() {
        result.push('…');
    }
    result
}

/// Move `index` onto a char boundary so slicing never panics. `forward` picks
/// the direction: end offsets round up, start offsets round down.
fn clamp_to_char_boundary(text: &str, mut index: usize, forward: bool) -> usize {
    while index > 0 && index < text.len() && !text.is_char_boundary(index) {
        if forward {
            index += 1;
        } else {
            index -= 1;
        }
    }
    index
}
