from pydantic import BaseModel, ConfigDict, Field


class NotifyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user: str
    password: str = Field(alias="pass")
    notify_id: str
    param: dict = Field(default_factory=dict)
