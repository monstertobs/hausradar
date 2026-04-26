from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/rooms")
def get_rooms(request: Request):
    return request.app.state.rooms
