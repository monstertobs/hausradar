from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/sensors")
def get_sensors(request: Request):
    return request.app.state.sensors
