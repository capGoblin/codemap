from app.documents import accept_document
from app.queue import enqueue


def upload(request):
    doc = accept_document(request.file)
    enqueue("parse_document", doc.id)
    return {"id": doc.id}
