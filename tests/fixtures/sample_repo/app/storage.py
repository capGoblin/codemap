from app import db


def store_pages(doc_id, pages):
    db.update("document", {"status": "parsed"})
