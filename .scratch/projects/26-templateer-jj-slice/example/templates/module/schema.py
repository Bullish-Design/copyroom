from pydantic import BaseModel, ConfigDict, Field


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=1)
    module: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    python_version: str = Field(pattern=r"^3\.[0-9]+$")
