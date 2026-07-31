import csv
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(
    title="Inventario - Tienda de Suministros para Cafeterías",
    description="API REST para gestionar el inventario de una tienda de suministros para cafeterías con dos locales físicos.",
    version="1.0.0",
)

CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products.csv")


# ─── Modelos ────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    quantity: int
    unit: str


class ProductUpdate(BaseModel):
    delta: int


class Product(BaseModel):
    id: int
    name: str
    quantity: int
    unit: str


# ─── Funciones auxiliares CSV ───────────────────────────────────────────────

def _read_products() -> list[dict]:
    """Lee todos los productos del CSV y los devuelve como lista de diccionarios."""
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, mode="r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def _write_products(products: list[dict]) -> None:
    """Sobrescribe el CSV con la lista completa de productos."""
    fieldnames = ["id", "name", "quantity", "unit"]
    with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)


def _next_id(products: list[dict]) -> int:
    """Devuelve el siguiente ID disponible."""
    if not products:
        return 1
    return max(int(p["id"]) for p in products) + 1


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/inventory", response_model=list[Product])
def list_products():
    """Devuelve la lista completa de productos en el inventario."""
    return _read_products()


@app.post("/inventory", response_model=Product, status_code=201)
def add_product(product: ProductCreate):
    """Añade un nuevo producto al inventario."""
    products = _read_products()

    # Validar que no exista un producto con el mismo nombre
    if any(p["name"].lower() == product.name.lower() for p in products):
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un producto con el nombre '{product.name}'",
        )

    new_product = {
        "id": _next_id(products),
        "name": product.name,
        "quantity": product.quantity,
        "unit": product.unit,
    }
    products.append(new_product)
    _write_products(products)
    return new_product


@app.patch("/inventory/{product_id}", response_model=Product)
def update_stock(product_id: int, update: ProductUpdate):
    """
    Actualiza el stock de un producto existente.

    - `delta` positivo → entrada de stock (ej: +10)
    - `delta` negativo → salida de stock (ej: -3)
    """
    products = _read_products()

    for p in products:
        if int(p["id"]) == product_id:
            new_quantity = int(p["quantity"]) + update.delta
            if new_quantity < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"No hay suficiente stock. Cantidad actual: {p['quantity']}, salida solicitada: {abs(update.delta)}",
                )
            p["quantity"] = new_quantity
            _write_products(products)
            return {
                "id": int(p["id"]),
                "name": p["name"],
                "quantity": p["quantity"],
                "unit": p["unit"],
            }

    raise HTTPException(
        status_code=404,
        detail=f"Producto con id {product_id} no encontrado",
    )


@app.get("/inventory/alerts", response_model=list[Product])
def stock_alerts(threshold: int = Query(10, description="Umbral mínimo de stock para generar alerta")):
    """
    Devuelve todos los productos cuya cantidad sea inferior al umbral especificado.
    Por defecto, el umbral es 10.
    """
    products = _read_products()
    alerts = [
        p for p in products if int(p["quantity"]) < threshold
    ]
    return alerts


# ─── Punto de entrada ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)