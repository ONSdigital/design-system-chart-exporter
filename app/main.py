from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class LivenessResponse(BaseModel):
    message: str


@app.get("/")
def liveness() -> LivenessResponse:
    """Returns a liveness response indicating the service is up and running."""
    return LivenessResponse(message="Chart generator is up and running")
