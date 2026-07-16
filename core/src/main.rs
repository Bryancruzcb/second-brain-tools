use std::collections::{HashMap, HashSet};
use std::fs;

use walkdir::WalkDir;
use rayon::prelude::*;
use regex::Regex;
use chrono::Local;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
struct NoteDetails {
    rel_path: String,
    title: String,
    links: Vec<String>,
    tags: Vec<String>,
}

#[derive(Serialize, Clone)]
struct BrokenLink {
    source: String,
    source_title: String,
    target: String,
}

#[derive(Serialize, Clone)]
struct OrphanedNote {
    path: String,
    title: String,
}

#[derive(Serialize, Clone)]
struct TaglessNote {
    path: String,
    title: String,
    suggestions: Vec<String>,
}

#[derive(Serialize)]
struct GraphNode {
    id: String,
    label: String,
    tags: Vec<String>,
}

#[derive(Serialize)]
struct GraphEdge {
    source: String,
    target: String,
}

#[derive(Serialize)]
struct VaultHealthResult {
    total_notes: usize,
    total_links: usize,
    avg_links_per_note: f64,
    broken_links: Vec<BrokenLink>,
    orphaned_notes: Vec<OrphanedNote>,
    tagless_notes: Vec<TaglessNote>,
    nodes: Vec<GraphNode>,
    edges: Vec<GraphEdge>,
}

fn parse_links(content: &str) -> Vec<String> {
    let re = Regex::new(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]").unwrap();
    let mut links = Vec::new();
    for cap in re.captures_iter(content) {
        let link = cap[1].trim().to_string();
        if !link.starts_with("http") && !link.starts_with("file:") {
            links.push(link);
        }
    }
    links
}

fn parse_tags(content: &str) -> Vec<String> {
    let mut tags = HashSet::new();
    
    // Body tags
    let body_re = Regex::new(r"(?:^|\s)#([\p{L}\p{N}_\-/]+)").unwrap();
    for cap in body_re.captures_iter(content) {
        tags.insert(cap[1].to_string());
    }

    // YAML Frontmatter tags
    let frontmatter_re = Regex::new(r"^---\r?\n(.*?)\r?\n---").unwrap();
    if let Some(fm_match) = frontmatter_re.captures(content) {
        let yaml_content = &fm_match[1];
        
        let inline_tags_re = Regex::new(r"(?m)^tags:\s*\[(.*?)\]").unwrap();
        if let Some(inline_match) = inline_tags_re.captures(yaml_content) {
            for t in inline_match[1].split(',') {
                let tag = t.trim().trim_matches('"').trim_matches('\'');
                if !tag.is_empty() {
                    tags.insert(tag.to_string());
                }
            }
        } else {
            let multiline_tags_re = Regex::new(r"(?m)^\s*-\s*([^\s#]+)").unwrap();
            for cap in multiline_tags_re.captures_iter(yaml_content) {
                tags.insert(cap[1].to_string());
            }
        }
    }

    tags.into_iter().collect()
}

fn suggest_tags(title: &str, content: &str) -> Vec<String> {
    let mut suggestions = Vec::new();
    let text = format!("{} {}", title.to_lowercase(), content.to_lowercase());

    let rules: Vec<(&str, Vec<&str>)> = vec![
        ("#school", vec!["essay", "thesis", "assignment", "homework", "math", "class", "course", "lecture", "study", "university", "college", "professor"]),
        ("#coding", vec!["react", "python", "javascript", "code", "git", "api", "database", "sql", "function", "development", "bug", "node", "npm", "script", "rust", "go"]),
        ("#personal", vec!["subscription", "charge", "bank", "purchase", "progressive", "weed", "tiktok", "personal", "finance", "bill", "receipt"]),
        ("#second-brain", vec!["obsidian", "second brain", "rag", "embedding", "vector", "retrieve", "prompt", "chat", "archive"]),
    ];

    for (tag, keywords) in rules {
        if keywords.iter().any(|&kw| text.contains(kw)) {
            suggestions.push(tag.to_string());
        }
    }

    suggestions
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let json_mode = args.contains(&"--json".to_string());

    // Resolve vault directory from env (for Docker) or default local paths
    let vault_dir = if let Ok(env_path) = std::env::var("OBSIDIAN_VAULT_PATH") {
        std::path::PathBuf::from(env_path)
    } else {
        let home_dir = dirs::home_dir().expect("Could not find home directory");
        // Try CloudStorage first, fallback to OneDrive
        let cloud_path = home_dir.join("Library/CloudStorage/OneDrive-Personal/Documents/Obsidian Vault");
        if cloud_path.exists() {
            cloud_path
        } else {
            home_dir.join("OneDrive/Documents/Obsidian Vault")
        }
    };
    let report_path = vault_dir.join("00 Home/Vault Health Report.md");

    let exclude_dirs = [".obsidian", ".smart-env", "Templates", "99 Archive", "Obsidian Vault Backup", "05 AI Chats", "99 Import Logs"];

    // 1. Collect all valid markdown files
    let md_files: Vec<std::path::PathBuf> = WalkDir::new(&vault_dir)
        .into_iter()
        .filter_entry(|e| {
            if e.file_type().is_dir() {
                let name = e.file_name().to_string_lossy();
                !exclude_dirs.contains(&name.as_ref()) && !name.starts_with('.')
            } else {
                true
            }
        })
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file() && e.path().extension().and_then(|s| s.to_str()) == Some("md"))
        .filter(|e| {
            let name = e.file_name().to_string_lossy();
            !name.contains("Index.md") && name != "Vault Health Report.md"
        })
        .map(|e| e.path().to_path_buf())
        .collect();

    if !json_mode {
        println!("Found {} markdown files. Loading I/O sequentially to avoid OneDrive timeouts...", md_files.len());
    }

    // 2. Read files sequentially to prevent overwhelming OneDrive's File Provider daemon (os error 60)
    let mut raw_notes = Vec::new();
    for path in &md_files {
        let rel_path = path.strip_prefix(&vault_dir).unwrap().to_string_lossy().replace("\\", "/");
        let title = path.file_stem().unwrap().to_string_lossy().to_string();
        
        match fs::read_to_string(path) {
            Ok(content) => raw_notes.push((rel_path, title, content)),
            Err(e) => {
                if !json_mode {
                    eprintln!("Failed to read (skipping) {:?}: {}", path, e);
                }
            }
        }
    }

    if !json_mode {
        println!("Loaded {} files into memory. Parsing concurrently on CPU threads...", raw_notes.len());
    }

    // 3. Parallel processing using Rayon for heavy CPU parsing
    let parsed_notes: Vec<NoteDetails> = raw_notes.par_iter().map(|(rel_path, title, content)| {
        let links = parse_links(content);
        let tags = parse_tags(content);
        NoteDetails {
            rel_path: rel_path.clone(),
            title: title.clone(),
            links,
            tags,
        }
    }).collect();

    // 4. Post-processing (Sequential, fast hashmap lookups)
    let mut all_notes = HashMap::new();
    let mut note_details = HashMap::new();

    for note in &parsed_notes {
        note_details.insert(note.rel_path.clone(), note.clone());
        all_notes.insert(note.title.to_lowercase(), note.rel_path.clone());
        all_notes.insert(note.rel_path.replace(".md", "").to_lowercase(), note.rel_path.clone());
        all_notes.insert(note.rel_path.to_lowercase(), note.rel_path.clone());
    }

    let mut broken_links = Vec::new();
    let mut incoming_links: HashMap<String, Vec<String>> = HashMap::new();
    for note in &parsed_notes {
        incoming_links.insert(note.rel_path.clone(), Vec::new());
    }
    
    let mut tagless_notes = Vec::new();
    let mut edges = Vec::new();

    for note in &parsed_notes {
        for link in &note.links {
            let mut normalized_link = link.to_lowercase();
            if let Some(idx) = normalized_link.find('#') {
                normalized_link = normalized_link[..idx].to_string();
            }

            if let Some(target_rel) = all_notes.get(&normalized_link) {
                incoming_links.get_mut(target_rel).unwrap().push(note.rel_path.clone());
                edges.push(GraphEdge {
                    source: note.rel_path.clone(),
                    target: target_rel.clone(),
                });
            } else if !link.starts_with('#') {
                broken_links.push(BrokenLink {
                    source: note.rel_path.clone(),
                    source_title: note.title.clone(),
                    target: link.clone(),
                });
            }
        }

        if note.tags.is_empty() {
            if let Some((_, _, content)) = raw_notes.iter().find(|(r, _, _)| *r == note.rel_path) {
                let suggs = suggest_tags(&note.title, content);
                tagless_notes.push(TaglessNote {
                    path: note.rel_path.clone(),
                    title: note.title.clone(),
                    suggestions: suggs,
                });
            }
        }
    }

    let mut orphaned_notes = Vec::new();
    for (rel_path, incoming) in &incoming_links {
        if incoming.is_empty() && !rel_path.contains("Home") && !rel_path.contains("Index.md") {
            orphaned_notes.push(OrphanedNote {
                path: rel_path.clone(),
                title: note_details[rel_path].title.clone(),
            });
        }
    }

    let nodes: Vec<GraphNode> = parsed_notes.iter().map(|note| {
        GraphNode {
            id: note.rel_path.clone(),
            label: note.title.clone(),
            tags: note.tags.clone(),
        }
    }).collect();

    let total_notes = parsed_notes.len();
    let total_links: usize = parsed_notes.iter().map(|n| n.links.len()).sum();
    let avg_links = if total_notes > 0 { total_links as f64 / total_notes as f64 } else { 0.0 };

    if json_mode {
        let result = VaultHealthResult {
            total_notes,
            total_links,
            avg_links_per_note: avg_links,
            broken_links,
            orphaned_notes,
            tagless_notes,
            nodes,
            edges,
        };
        match serde_json::to_string(&result) {
            Ok(json_str) => println!("{}", json_str),
            Err(e) => eprintln!("Error serializing health stats to JSON: {}", e),
        }
        return;
    }

    // Markdown Mode (Standard output when run manually)
    let mut report = format!("# Obsidian Vault Health Report\n\nGenerated: {}\n\n## 📊 Quick Stats\n\n- **Total Notes**: {}\n- **Total Internal Links**: {}\n- **Average Links per Note**: {:.2}\n- **Broken Links**: {}\n- **Orphaned Notes**: {}\n- **Notes Lacking Tags**: {}\n\n---\n\n## ❌ Broken Links\n\nThese are wikilinks pointing to notes that do not exist:\n\n", 
        Local::now().format("%Y-%m-%d %H:%M:%S"), total_notes, total_links, avg_links, broken_links.len(), orphaned_notes.len(), tagless_notes.len());

    if !broken_links.is_empty() {
        report.push_str("| Source Note | Broken Target Link |\n|---|---|\n");
        for bl in &broken_links {
            report.push_str(&format!("| [[{}\\|{}]] | `{}` |\n", bl.source, bl.source_title, bl.target));
        }
    } else {
        report.push_str("*No broken links found! 🎉*\n");
    }

    report.push_str("\n---\n\n## 🕸️ Orphaned Notes\n\nThese notes exist but have no incoming links from other files in the vault:\n\n");
    if !orphaned_notes.is_empty() {
        let mut sorted_orphaned = orphaned_notes.clone();
        sorted_orphaned.sort_by(|a, b| a.title.cmp(&b.title));
        for note in &sorted_orphaned {
            report.push_str(&format!("- [[{}|{}]] (`{}`)\n", note.path, note.title, note.path));
        }
    } else {
        report.push_str("*No orphaned notes found! 🎉*\n");
    }

    report.push_str("\n---\n\n## 🏷️ Missing Tags & Suggestions\n\nThese notes do not have any tags. Here are automatically suggested tags based on their content:\n\n");
    if !tagless_notes.is_empty() {
        report.push_str("| Note | Suggested Tags |\n|---|---|\n");
        for note in &tagless_notes {
            let sugg_str = if note.suggestions.is_empty() { "*No suggestions*".to_string() } else { note.suggestions.join(", ") };
            report.push_str(&format!("| [[{}\\|{}]] | {} |\n", note.path, note.title, sugg_str));
        }
    } else {
        report.push_str("*All notes have tags! 🎉*\n");
    }

    if let Some(parent) = report_path.parent() {
        if let Err(e) = fs::create_dir_all(parent) {
            eprintln!("Failed to create parent directories for report: {}", e);
        }
    }
    match fs::write(&report_path, report) {
        Ok(_) => {
            println!("Vault Health Report generated successfully: {:?}", report_path);
            println!("- Found {} broken links.", broken_links.len());
            println!("- Found {} orphaned notes.", orphaned_notes.len());
            println!("- Found {} notes without tags.", tagless_notes.len());
        },
        Err(e) => eprintln!("Failed to write the Vault Health Report to disk. OneDrive might be syncing. Error: {}", e),
    }
}

