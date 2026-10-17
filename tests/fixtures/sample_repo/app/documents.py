from dataclasses import dataclass

from app import db


@dataclass
class Doc:
    id: str
    status: str


def accept_document(file):
    db.insert("document", {"status": "accepted"})
    return Doc(id=file.name, status="accepted")
