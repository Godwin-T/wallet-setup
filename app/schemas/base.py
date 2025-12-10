from pydantic import BaseModel


class ORMModel(BaseModel):
    class Config:
        model_config = {
        "from_attributes": True
    }
