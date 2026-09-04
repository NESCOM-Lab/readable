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
    /// Search body paragraph text (case-insensitive) and print the matches.
    Search { path: PathBuf, pattern: String },
}

/// A section without its body text, so the tree can be shown at a glance.
#[derive(Serialize)]
struct OutlineNode {
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    title: Option<String>,
    paragraphs: usize,
    provenance: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    subsections: Vec<OutlineNode>,
}

/// One paragraph that matched a search, with enough context to locate it.
#[derive(Serialize)]
struct SearchHit {
    #[serde(skip_serializing_if = "Option::is_none")]
    section: Option<String>,
    provenance: String,
    snippet: String,
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
                None => Err(format!("no section with id '{id}'")),
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
        Query::Search { path, pattern } => {
            let paper = load(path)?;
            let mut hits = Vec::new();
            search_sections(&paper.body.sections, &pattern.to_lowercase(), &mut hits);
            print_json(&hits)
        }
    }
}

/// Load a paper from a workspace directory (via its 'paper.jats.xml') or from a
/// JATS XML file directly.
fn load(path: &Path) -> Result<Paper, String> {
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
    for section in sections {
        nodes.push(OutlineNode {
            id: section.id.clone(),
            title: section.title.clone(),
            paragraphs: section.paragraphs.len(),
            provenance: section.provenance.clone(),
            subsections: outline(&section.subsections),
        });
    }
    nodes
}

/// Depth-first search for a section by id, including subsections.
fn find_section<'a>(sections: &'a [Section], id: &str) -> Option<&'a Section> {
    for section in sections {
        if section.id.as_deref() == Some(id) {
            return Some(section);
        }
        if let Some(found) = find_section(&section.subsections, id) {
            return Some(found);
        }
    }
    None
}

/// Collect every paragraph whose text contains `needle` (already lowercased).
fn search_sections(sections: &[Section], needle: &str, hits: &mut Vec<SearchHit>) {
    for section in sections {
        for paragraph in &section.paragraphs {
            if let Some(position) = paragraph.text.to_lowercase().find(needle) {
                hits.push(SearchHit {
                    section: section.title.clone(),
                    provenance: paragraph.provenance.clone(),
                    snippet: snippet(&paragraph.text, position, needle.len()),
                });
            }
        }
        search_sections(&section.subsections, needle, hits);
    }
}

/// A short window of text around a match, with an ellipsis when it is clipped.
fn snippet(text: &str, match_start: usize, match_len: usize) -> String {
    const CONTEXT: usize = 60;

    let start = clamp_to_char_boundary(text, match_start.saturating_sub(CONTEXT), false);
    let end = clamp_to_char_boundary(text, (match_start + match_len + CONTEXT).min(text.len()), true);

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
