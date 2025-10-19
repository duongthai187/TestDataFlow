"""Inventory HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..dependencies import get_repository
from ..repository import InventoryRepository
from ..schemas import (
    InventoryAdjust,
    InventoryCreate,
    InventoryEventResponse,
    InventoryListResponse,
    InventoryReservation,
    InventoryResponse,
)
from ..services import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _serialize_item(item) -> dict[str, object]:
    available = item.quantity_on_hand - item.quantity_reserved
    return {
        "id": item.id,
        "sku": item.sku,
        "location": item.location,
        "quantityOnHand": item.quantity_on_hand,
        "quantityReserved": item.quantity_reserved,
        "available": available,
        "safetyStock": item.safety_stock,
        "createdAt": item.created_at,
        "updatedAt": item.updated_at,
    }


def _serialize_events(item) -> list[dict[str, object]]:
    return [
        {
            "type": event.type,
            "payload": event.payload,
            "createdAt": event.created_at,
        }
        for event in item.events
    ]


@router.post("", response_model=InventoryResponse, status_code=status.HTTP_201_CREATED)
async def create_inventory_item(
    payload: InventoryCreate,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryResponse:
    existing = await repository.find_by_sku(payload.sku, payload.location)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory item already exists")
    service = InventoryService(repository)
    item = await service.create_item(payload)
    return InventoryResponse.model_validate(_serialize_item(item))


@router.get("", response_model=InventoryListResponse)
async def list_inventory_items(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sku: str | None = None,
    location: str | None = None,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryListResponse:
    items, total = await repository.list_items(
        sku=sku,
        location=location,
        limit=limit,
        offset=offset,
    )
    responses = [InventoryResponse.model_validate(_serialize_item(item)) for item in items]
    return InventoryListResponse(items=responses, total=total)


@router.get("/{item_id}", response_model=InventoryResponse)
async def get_inventory_item(item_id: int, repository: InventoryRepository = Depends(get_repository)) -> InventoryResponse:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    return InventoryResponse.model_validate(_serialize_item(item))


@router.patch("/{item_id}", response_model=InventoryResponse)
async def adjust_inventory_item(
    item_id: int,
    payload: InventoryAdjust,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryResponse:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    service = InventoryService(repository)
    try:
        updated = await service.adjust_stock(
            item,
            quantity_on_hand=payload.quantity_on_hand,
            safety_stock=payload.safety_stock,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InventoryResponse.model_validate(_serialize_item(updated))


@router.post("/{item_id}/restock", response_model=InventoryResponse)
async def restock_inventory_item(
    item_id: int,
    payload: InventoryReservation,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryResponse:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    service = InventoryService(repository)
    try:
        updated = await service.increment_stock(item, quantity=payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InventoryResponse.model_validate(_serialize_item(updated))


@router.post("/{item_id}/reserve", response_model=InventoryResponse)
async def reserve_inventory(
    item_id: int,
    payload: InventoryReservation,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryResponse:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    service = InventoryService(repository)
    try:
        updated = await service.reserve(item, quantity=payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryResponse.model_validate(_serialize_item(updated))


@router.post("/{item_id}/release", response_model=InventoryResponse)
async def release_inventory(
    item_id: int,
    payload: InventoryReservation,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryResponse:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    service = InventoryService(repository)
    try:
        updated = await service.release(item, quantity=payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryResponse.model_validate(_serialize_item(updated))


@router.post("/{item_id}/commit", response_model=InventoryResponse)
async def commit_inventory(
    item_id: int,
    payload: InventoryReservation,
    repository: InventoryRepository = Depends(get_repository),
) -> InventoryResponse:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    service = InventoryService(repository)
    try:
        updated = await service.commit(item, quantity=payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryResponse.model_validate(_serialize_item(updated))


@router.get("/{item_id}/events", response_model=list[InventoryEventResponse])
async def list_inventory_events(
    item_id: int,
    repository: InventoryRepository = Depends(get_repository),
) -> list[InventoryEventResponse]:
    item = await repository.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    return [InventoryEventResponse.model_validate(event) for event in _serialize_events(item)]


@router.delete("/{item_id}")
async def delete_inventory_item(
    item_id: int,
    repository: InventoryRepository = Depends(get_repository),
) -> Response:
    item = await repository.get_item(item_id)
    if item is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await repository.delete_item(item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)