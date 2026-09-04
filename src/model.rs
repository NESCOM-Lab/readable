use serde::Serialize;



/// Top level Paper
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Paper {
    /// Name of source .xml or pdf file
    pub source: String,
    /// Paper identifier metadata and citation
    pub metadata: Metadata,
    /// Paper body
    pub body: Body,

}

/// Paper body
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Body {
    pub sections: Vec<Section>,
    pub figures: Vec<Figure>,
    pub tables: Vec<Table>,
    pub citations: Vec<Citation>,
}

/// Paper metadata, retrieved from JATS
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Metadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// Abstract text, flattened to a single string.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub abstract_text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub doi: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pmcid: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pmid: Option<String>,
    /// Publication year, when present.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<String>,
    /// Author display names in document order.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub authors: Vec<String>,
}


/// A single entry from the reference list
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Citation {
    /// JATS 'id' attribute of the '<ref>', when present.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    /// The citation text, flattened to a single string.
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub doi: Option<String>,
    pub provenance: String,
}

#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct PaperResult;



/// TODO: not implemented
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Claim {

}



/// A section or subsection
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Section {
    /// JATS 'id' attribute of the '<sec>', when present.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    pub paragraphs: Vec<Paragraph>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub subsections: Vec<Section>,
    /// Element path back into the source document.
    pub provenance: String,
}

/// A single paragraph of body text
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Paragraph {
    pub text: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub citations: Vec<String>,
    pub provenance: String,
}

/// A figure and its caption
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Figure {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    /// Label such as "Figure 1"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub caption: Option<String>,
    pub provenance: String,
}

/// A table and its caption. TODO: get the actual table
#[derive(Debug, Clone, PartialEq, Default, Serialize)]
pub struct Table {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub caption: Option<String>,
    pub provenance: String,
}

