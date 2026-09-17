"""Export the clean data graph from one or more TriG files to Turtle.

For each .trig file given, read its target data graph and write it as a
clean .ttl file with the same basename, overwriting anything already there.

    python trig_to_ttl.py ontology.trig            # -> ontology.ttl
    python trig_to_ttl.py a.trig b.trig            # -> a.ttl, b.ttl
"""

import sys
from pathlib import Path

from rdflib import Dataset, URIRef

DATA_GRAPH = URIRef("http://example.org/text-ontology/graphs/data")


def export_data_graph(trig_path):
    dataset = Dataset()
    dataset.parse(trig_path, format="trig")
    data = dataset.graph(DATA_GRAPH)
    return data.serialize(format="turtle")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python trig_to_ttl.py FILE.trig [FILE.trig ...]",
              file=sys.stderr)
        return 2
    for arg in args:
        trig = Path(arg)
        ttl = trig.with_suffix(".ttl")
        ttl.write_text(export_data_graph(trig), encoding="utf-8")
        print(f"{trig} -> {ttl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
