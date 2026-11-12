from typing import Literal

from pydantic import BaseModel

from app.schemas.common import InputModel


class DeploymentFailure(BaseModel):
    code: str
    message: str
    field: str = ""
    suggestion: str = ""


class DeploymentJob(BaseModel):
    id: str
    appId: str | None
    status: Literal[
        "queued", "running", "succeeded", "failed", "recovery_required", "cancelled"
    ]
    phase: str
    terminal: bool
    repository: str
    subdomain: str
    commit: str | None
    updatedAt: float
    url: str | None
    error: DeploymentFailure | None


class DeploymentOptions(BaseModel):
    executionEnabled: bool
    baseDomain: str
    gitHosts: list[str]
    maxAppMemoryMiB: int
    message: str


class DeploymentSecretUse(BaseModel):
    service: str
    environmentVariable: str


class DeploymentSecretItem(BaseModel):
    name: str
    uses: list[DeploymentSecretUse]
    state: Literal["missing", "configured", "unavailable"]
    managed: bool


class DeploymentSecretRequirements(BaseModel):
    jobId: str
    repository: str
    subdomain: str
    canGenerate: bool
    items: list[DeploymentSecretItem]


class DeploymentSecretValues(InputModel):
    values: dict[str, str]
