//! Retrieval units: small pieces of the paper, each keeping the address it
//! came from so a semantic hit can be traced back and read in full.

use serde::Serialize;

use crate::model::{Paper, Section};

/// Sentences per window, and how far the next window starts along. A stride
/// smaller than the window means neighbours overlap, so a fact that straddles
/// a boundary still lands whole in one of them.
const SENTENCES_PER_WINDOW: usize = 3;
const WINDOW_STRIDE: usize = 2;

/// Words that end in a period without ending a sentence.
const ABBREVIATIONS: [&str; 9] = [
    "al.", "Fig.", "Figs.", "e.g.", "i.e.", "vs.", "approx.", "ca.", "Eq.",
];

#[derive(Serialize)]
pub struct Unit {
    pub id: String,
    /// 'abstract', 'body', 'figure', 'table' or 'citation'.
    pub origin: &'static str,
    /// Section id, for body text only. Pass it to 'query section' to read on.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub section: Option<String>,
    /// This section and the ones it sits inside, outermost first. Filtering on
    /// a parent id needs it: 'Methods' owns no paragraphs of its own, they all
    /// belong to its subsections, so matching on 'section' alone finds nothing.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub section_path: Vec<String>,
    /// Section title, figure label, or citation id, depending on the origin.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub location: Option<String>,
    pub provenance: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub citations: Vec<String>,
    pub text: String,
}

/// Everything a unit needs apart from its own text.
struct Address {
    prefix: String,
    origin: &'static str,
    section: Option<String>,
    section_path: Vec<String>,
    location: Option<String>,
    provenance: String,
    citations: Vec<String>,
}

pub fn build(paper: &Paper) -> Vec<Unit> {
    let mut units = Vec::new();

    if let Some(abstract_text) = &paper.metadata.abstract_text {
        let address = Address {
            prefix: "abstract".to_string(),
            origin: "abstract",
            section: None,
            section_path: Vec::new(),
            location: None,
            provenance: "article/front/abstract".to_string(),
            citations: Vec::new(),
        };
        push_windows(&mut units, &address, abstract_text);
    }

    collect_sections(&paper.body.sections, &[], &mut units);

    for figure in &paper.body.figures {
        if let Some(caption) = &figure.caption {
            let address = Address {
                prefix: figure.id.clone().unwrap_or_else(|| "fig".to_string()),
                origin: "figure",
                section: None,
                section_path: Vec::new(),
                location: figure.label.clone().or_else(|| figure.id.clone()),
                provenance: figure.provenance.clone(),
                citations: Vec::new(),
            };
            push_windows(&mut units, &address, caption);
        }
    }

    for table in &paper.body.tables {
        if let Some(caption) = &table.caption {
            let address = Address {
                prefix: table.id.clone().unwrap_or_else(|| "tab".to_string()),
                origin: "table",
                section: None,
                section_path: Vec::new(),
                location: table.label.clone().or_else(|| table.id.clone()),
                provenance: table.provenance.clone(),
                citations: Vec::new(),
            };
            push_windows(&mut units, &address, caption);
        }
    }

    // Reference entries are already short, so each one stays a single unit.
    for (index, citation) in paper.body.citations.iter().enumerate() {
        let id = citation
            .id
            .clone()
            .unwrap_or_else(|| format!("ref{}", index + 1));
        units.push(Unit {
            id: id.clone(),
            origin: "citation",
            section: None,
            section_path: Vec::new(),
            location: Some(id),
            provenance: citation.provenance.clone(),
            citations: Vec::new(),
            text: citation.text.clone(),
        });
    }

    units
}

fn collect_sections(sections: &[Section], ancestors: &[String], units: &mut Vec<Unit>) {
    for section in sections {
        let mut path = ancestors.to_vec();
        if let Some(id) = &section.id {
            path.push(id.clone());
        }

        for (index, paragraph) in section.paragraphs.iter().enumerate() {
            let section_id = section.id.clone().unwrap_or_else(|| "sec".to_string());
            let address = Address {
                prefix: format!("{}/p{}", section_id, index + 1),
                origin: "body",
                section: section.id.clone(),
                section_path: path.clone(),
                location: section.title.clone(),
                provenance: paragraph.provenance.clone(),
                citations: paragraph.citations.clone(),
            };
            push_windows(units, &address, &paragraph.text);
        }
        collect_sections(&section.subsections, &path, units);
    }
}

fn push_windows(units: &mut Vec<Unit>, address: &Address, text: &str) {
    for (number, window) in windows(&sentences(text)).into_iter().enumerate() {
        units.push(Unit {
            id: format!("{}/w{}", address.prefix, number + 1),
            origin: address.origin,
            section: address.section.clone(),
            section_path: address.section_path.clone(),
            location: address.location.clone(),
            provenance: address.provenance.clone(),
            citations: address.citations.clone(),
            text: window,
        });
    }
}

/// Group sentences into overlapping windows.
fn windows(sentences: &[String]) -> Vec<String> {
    let mut result = Vec::new();
    let mut start = 0;

    while start < sentences.len() {
        let end = (start + SENTENCES_PER_WINDOW).min(sentences.len());
        result.push(sentences[start..end].join(" "));
        if end == sentences.len() {
            break;
        }
        start += WINDOW_STRIDE;
    }

    result
}

/// Split text into sentences. A '.', '?' or '!' ends one when whitespace and a
/// capital letter follow it, unless it closes a known abbreviation.
fn sentences(text: &str) -> Vec<String> {
    let characters: Vec<(usize, char)> = text.char_indices().collect();
    let mut result = Vec::new();
    let mut start = 0;

    for position in 0..characters.len() {
        let (offset, character) = characters[position];
        if character != '.' && character != '?' && character != '!' {
            continue;
        }

        let followed_by_space =
            matches!(characters.get(position + 1), Some(&(_, next)) if next.is_whitespace());
        let then_capital = matches!(
            characters.get(position + 2),
            Some(&(_, next)) if next.is_uppercase() || next == '('
        );
        if !followed_by_space || !then_capital {
            continue;
        }

        let end = offset + character.len_utf8();
        let sentence = text[start..end].trim();
        if character == '.' && ends_with_abbreviation(sentence) {
            continue;
        }
        if !sentence.is_empty() {
            result.push(sentence.to_string());
        }
        start = end;
    }

    let tail = text[start..].trim();
    if !tail.is_empty() {
        result.push(tail.to_string());
    }

    result
}

fn ends_with_abbreviation(sentence: &str) -> bool {
    let last_word = sentence.split_whitespace().last().unwrap_or("");

    // A lone initial, as in an author name.
    if last_word.chars().count() == 2
        && last_word.ends_with('.')
        && last_word.starts_with(char::is_uppercase)
    {
        return true;
    }

    ABBREVIATIONS
        .iter()
        .any(|abbreviation| last_word.ends_with(abbreviation))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Paragraph;

    #[test]
    fn keeps_abbreviations_inside_a_sentence() {
        let split = sentences("We used a treadmill. McHugh et al. found the opposite. That is all.");
        assert_eq!(split.len(), 3);
        assert_eq!(split[1], "McHugh et al. found the opposite.");
    }

    #[test]
    fn windows_overlap_by_one_sentence() {
        let input: Vec<String> = ["A one. ", "B two. ", "C three. ", "D four. ", "E five."]
            .iter()
            .map(|sentence| sentence.trim().to_string())
            .collect();
        let grouped = windows(&input);

        assert_eq!(grouped[0], "A one. B two. C three.");
        assert_eq!(grouped[1], "C three. D four. E five.");
    }

    #[test]
    fn section_path_runs_from_the_outermost_section_inward() {
        let mut parent = Section::default();
        parent.id = Some("Sec8".to_string());
        parent.title = Some("Methods".to_string());

        let mut child = Section::default();
        child.id = Some("Sec15".to_string());
        child.title = Some("Curve fitting analysis".to_string());
        child.paragraphs.push(Paragraph {
            text: "Tuning curves were fit with a von Mises function.".to_string(),
            provenance: "article/body/sec[8]/sec[8]/p[1]".to_string(),
            citations: Vec::new(),
        });
        parent.subsections.push(child);

        let mut units = Vec::new();
        collect_sections(&[parent], &[], &mut units);

        assert_eq!(units.len(), 1);
        assert_eq!(units[0].section.as_deref(), Some("Sec15"));
        // A paragraph of a subsection has to be findable under its parent,
        // which owns no paragraphs of its own.
        assert_eq!(units[0].section_path, vec!["Sec8", "Sec15"]);
    }

    #[test]
    fn short_text_is_one_window() {
        assert_eq!(windows(&sentences("Only a single sentence here.")).len(), 1);
    }
}
