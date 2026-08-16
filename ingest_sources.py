"""Find and read the source material before anything is parsed."""

TEXT_FILES = {
    ".txt", ".md", ".rst", ".csv", ".json", ".jsonl", ".yaml", ".yml",
    ".xml", ".html", ".log",
}


def find_text_files(source, graph_path):
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise RuntimeError(f"Source does not exist: {source}")
    graph_path = graph_path.resolve()
    return sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.resolve() != graph_path
        and path.suffix.lower() in TEXT_FILES
    )


def read_source(path):
    return path.read_text(encoding="utf-8", errors="replace")
