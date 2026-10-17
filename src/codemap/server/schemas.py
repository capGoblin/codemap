from pydantic import BaseModel


class Health(BaseModel):
    version: str
