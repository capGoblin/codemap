from app import s3
from app.storage import store_pages


def ocr(doc_id):
    return [f"page text of {doc_id}"]


def parse_document(doc_id):
    pages = ocr(doc_id)
    s3.put(f"normalized/{doc_id}", pages)
    store_pages(doc_id, pages)
