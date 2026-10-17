from app.worker import parse_document

HANDLERS = {"parse_document": parse_document}


def enqueue(name, arg):
    HANDLERS[name](arg)
