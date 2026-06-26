from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import get_board_service, require_admin
from app.schemas.auth import UserRead
from app.schemas.board import BoardCreate, BoardListItem, BoardRead, BoardUpdate
from app.schemas.common import MessageResponse
from app.services.board_service import BoardService

router = APIRouter(prefix="/board", tags=["board"])


@router.get("", response_model=dict)
def list_boards(
    board_type: str = "notice",
    page: int = 1,
    size: int = 20,
    service: BoardService = Depends(get_board_service),
):
    items, total = service.list_boards(board_type, page, size)
    return {"items": [i.model_dump() for i in items], "total": total, "page": page, "size": size}


@router.get("/{board_id}", response_model=BoardRead)
def get_board(board_id: int, service: BoardService = Depends(get_board_service)):
    try:
        return service.get_board(board_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("", response_model=BoardRead)
def create_board(
    body: BoardCreate,
    admin: UserRead = Depends(require_admin),
    service: BoardService = Depends(get_board_service),
):
    """공지 작성 — 관리자 전용."""
    return service.create_board(body, admin.username)


@router.put("/{board_id}", response_model=BoardRead)
def update_board(
    board_id: int,
    body: BoardUpdate,
    admin: UserRead = Depends(require_admin),
    service: BoardService = Depends(get_board_service),
):
    try:
        return service.update_board(board_id, body, admin.username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.delete("/{board_id}", response_model=MessageResponse)
def delete_board(
    board_id: int,
    admin: UserRead = Depends(require_admin),
    service: BoardService = Depends(get_board_service),
):
    try:
        service.delete_board(board_id, admin.username, admin.role)
        return MessageResponse(message="삭제되었습니다.")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/{board_id}/files", response_model=MessageResponse)
async def upload_file(
    board_id: int,
    file: UploadFile,
    admin: UserRead = Depends(require_admin),
    service: BoardService = Depends(get_board_service),
):
    content = await file.read()
    try:
        service.attach_file(board_id, file.filename or "unknown", content)
        return MessageResponse(message="파일이 업로드되었습니다.")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
