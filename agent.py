#!/usr/bin/env python3
"""
Agente de Inventario - Agente IA que gestiona el inventario de una tienda
de suministros para cafeterías usando lenguaje natural.

Se conecta a GROQ (LLM) y utiliza la API REST como conjunto de herramientas.
Bucle manual: Observar → Pensar → Actuar → Actualizar → Repetir
"""

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

# ─── Configuración ──────────────────────────────────────────────────────────

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Forzar modelo con límites más altos (70B tiene 7000 TPM, 100K TPD)
# Ignoramos GROQ_MODEL del entorno porque llama-3.1-8b-instant tiene TPM muy bajo (6000)
GROQ_MODEL = "llama-3.3-70b-versatile"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversation_log.csv")


# ─── Tools del agente ──────────────────────────────────────────────────────
# Cada tool tiene: name, description, parameters (claramente tipados)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_products",
            "description": "Obtiene la lista completa de todos los productos en el inventario con su id, nombre, cantidad y unidad.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_product",
            "description": "Añade un nuevo producto al inventario. Úsalo cuando llegue un producto nuevo que no estaba registrado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Nombre descriptivo del producto (ej: 'Café Arábica Molido')",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Cantidad inicial del producto en unidades enteras",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unidad de medida (kg, litros, unidades, paquetes, etc.)",
                    },
                },
                "required": ["name", "quantity", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stock",
            "description": "Actualiza el stock de un producto existente. Usa delta POSITIVO para entradas (nuevas entregas/reposiciones) y delta NEGATIVO para salidas (ventas, productos usados). IMPORTANTE: proporciona el NOMBRE EXACTO del producto (no el ID numérico).",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Nombre EXACTO del producto a actualizar (ej: 'Café Arábica Molido', 'Leche Entera'). NO uses el ID numérico, usa el nombre.",
                    },
                    "delta": {
                        "type": "integer",
                        "description": "Cantidad a añadir (positivo, ej: +20) o restar (negativo, ej: -5) del stock actual",
                    },
                },
                "required": ["product_name", "delta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": "Obtiene los productos con stock bajo (por defecto, menos de 10 unidades). Útil para revisar qué productos están por agotarse.",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "integer",
                        "description": "Umbral de cantidad mínima para la alerta (por defecto: 10). Productos con cantidad menor a este valor serán reportados.",
                    },
                },
                "required": [],
            },
        },
    },
]


# ─── Llamadas a la API REST ────────────────────────────────────────────────

def _call_api(method: str, path: str, data: dict | None = None) -> dict:
    """Realiza una llamada HTTP a la API REST y devuelve el resultado."""
    url = f"{API_BASE_URL}{path}"
    try:
        # Filtrar valores None de los parámetros
        clean_params = None
        if data:
            clean_params = {k: v for k, v in data.items() if v is not None}

        if method == "GET":
            resp = requests.get(url, params=clean_params, timeout=10)
        elif method == "POST":
            resp = requests.post(url, json=data, timeout=10)
        elif method == "PATCH":
            resp = requests.patch(url, json=data, timeout=10)
        else:
            return {"error": f"Método HTTP no soportado: {method}"}

        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            return {"error": f"Error {resp.status_code}: {detail}"}

        try:
            return resp.json()
        except Exception:
            return {"resultado": resp.text}

    except requests.exceptions.ConnectionError:
        return {"error": f"No se pudo conectar a la API en {API_BASE_URL}. ¿Está el servidor corriendo?"}
    except requests.exceptions.Timeout:
        return {"error": "La API no respondió en el tiempo esperado."}
    except Exception as e:
        return {"error": f"Error inesperado: {str(e)}"}


def run_tool(tool_name: str, args: dict) -> str:
    """
    Ejecuta una herramienta llamando al endpoint correspondiente de la API.
    Devuelve el resultado en formato ultra-compacto para ahorrar tokens.
    """
    # Protección contra args None (ocurre cuando el LLM envía "null" como argumentos)
    if args is None:
        args = {}

    if tool_name == "list_products":
        result = _call_api("GET", "/inventory")
        # JSON claro y completo para que el LLM lo entienda bien
        if isinstance(result, list) and not isinstance(result, dict):
            products_list = []
            for p in result:
                products_list.append({
                    "id": int(p["id"]),
                    "name": p["name"],
                    "quantity": int(p["quantity"]),
                    "unit": p["unit"],
                })
            return json.dumps({"productos": products_list}, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    elif tool_name == "add_product":
        result = _call_api("POST", "/inventory", {
            "name": args["name"],
            "quantity": args["quantity"],
            "unit": args["unit"],
        })
        # Si el producto ya existe (409), actualizar stock en lugar de fallar
        if isinstance(result, dict) and "error" in result and "409" in result["error"]:
            # Buscar el producto existente para obtener su unidad y sumar cantidad
            inventory = _call_api("GET", "/inventory")
            if isinstance(inventory, list):
                for p in inventory:
                    if p["name"].lower() == args["name"].lower():
                        product_id = int(p["id"])
                        update_result = _call_api("PATCH", f"/inventory/{product_id}", {
                            "delta": args["quantity"],
                        })
                        # Añadir nota de que se actualizó en lugar de crear
                        if isinstance(update_result, dict) and "error" not in update_result:
                            update_result["_action"] = "updated_existing"
                        return json.dumps(update_result, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    elif tool_name == "update_stock":
        # Resolver product_name → product_id automáticamente
        product_name = args.get("product_name", "")
        if not product_name:
            return json.dumps({"error": "Falta el nombre del producto (product_name)"}, ensure_ascii=False)

        # Obtener lista de productos para buscar el ID por nombre
        inventory = _call_api("GET", "/inventory")
        if isinstance(inventory, list):
            product_id = None
            for p in inventory:
                if p["name"].lower() == product_name.lower():
                    product_id = int(p["id"])
                    break
            if product_id is None:
                return json.dumps({"error": f"No se encontró ningún producto con el nombre '{product_name}'"}, ensure_ascii=False)
        else:
            return json.dumps({"error": f"No se pudo obtener el inventario: {inventory}"}, ensure_ascii=False)

        result = _call_api("PATCH", f"/inventory/{product_id}", {
            "delta": args["delta"],
        })
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    elif tool_name == "get_alerts":
        params = {}
        if "threshold" in args:
            params["threshold"] = args["threshold"]
        result = _call_api("GET", "/inventory/alerts", params)
        # JSON claro para que el LLM entienda todos los productos con alerta
        if isinstance(result, list) and not isinstance(result, dict):
            if not result:
                return json.dumps({"alerts": [], "mensaje": "No hay productos con stock bajo."}, ensure_ascii=False)
            alerts_list = []
            for p in result:
                alerts_list.append({
                    "id": int(p["id"]),
                    "name": p["name"],
                    "quantity": int(p["quantity"]),
                    "unit": p["unit"],
                })
            return json.dumps({"alerts": alerts_list}, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    else:
        return json.dumps({"error": f"Tool desconocida: {tool_name}"}, ensure_ascii=False)


# ─── Formateo de resultados para terminal ─────────────────────────────────

def _format_result_display(tool_name: str, result_json: str) -> str:
    """
    Formatea el resultado de una tool en una representación legible
    para mostrar en la terminal.
    """
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return result_json or "  (vacío)"

    # Si es un error, lo mostramos tal cual
    if isinstance(data, dict) and "error" in data:
        return f"  ⚠️  {data['error']}"

    # Si es None o no es lo esperado
    if data is None:
        return "  📭  No hay datos."

    # list_products → {"productos": [...]} → tabla
    if isinstance(data, dict) and "productos" in data:
        products = data["productos"]
        if not products:
            return "  📭  No hay productos que mostrar."
        col_id = max(2, max(len(str(p.get("id", ""))) for p in products))
        col_name = max(6, max(len(p.get("name", "")) for p in products))
        col_qty = max(10, max(len(str(p.get("quantity", ""))) for p in products))
        col_unit = max(8, max(len(p.get("unit", "")) for p in products))
        sep = f"  ├{'─' * (col_id + 2)}┼{'─' * (col_name + 2)}┼{'─' * (col_qty + 2)}┼{'─' * (col_unit + 2)}┤"
        header = f"  │ {'ID'.ljust(col_id)} │ {'Nombre'.ljust(col_name)} │ {'Cantidad'.rjust(col_qty)} │ {'Unidad'.ljust(col_unit)} │"
        lines = [f"  ┌{'─' * (col_id + 2)}┬{'─' * (col_name + 2)}┬{'─' * (col_qty + 2)}┬{'─' * (col_unit + 2)}┐",
                 header, sep]
        for p in products:
            pid = str(p.get("id", ""))
            name = p.get("name", "")
            qty = str(p.get("quantity", ""))
            unit = p.get("unit", "")
            lines.append(f"  │ {pid.rjust(col_id)} │ {name.ljust(col_name)} │ {qty.rjust(col_qty)} │ {unit.ljust(col_unit)} │")
        lines.append(f"  └{'─' * (col_id + 2)}┴{'─' * (col_name + 2)}┴{'─' * (col_qty + 2)}┴{'─' * (col_unit + 2)}┘")
        lines.append(f"  📦  Total: {len(products)} productos")
        return "\n".join(lines)

    # get_alerts → {"alerts": [...]} o {"alerts": [], "mensaje": "..."}
    if isinstance(data, dict) and "alerts" in data:
        alerts = data["alerts"]
        if not alerts:
            return "  ✅  No hay productos con stock bajo. ¡Todo en orden!"
        col_id = max(2, max(len(str(a.get("id", ""))) for a in alerts))
        col_name = max(6, max(len(a.get("name", "")) for a in alerts))
        col_qty = max(10, max(len(str(a.get("quantity", ""))) for a in alerts))
        col_unit = max(8, max(len(a.get("unit", "")) for a in alerts))
        sep = f"  ├{'─' * (col_id + 2)}┼{'─' * (col_name + 2)}┼{'─' * (col_qty + 2)}┼{'─' * (col_unit + 2)}┤"
        header = f"  │ {'ID'.ljust(col_id)} │ {'Nombre'.ljust(col_name)} │ {'Cantidad'.rjust(col_qty)} │ {'Unidad'.ljust(col_unit)} │"
        lines = [f"  ┌{'─' * (col_id + 2)}┬{'─' * (col_name + 2)}┬{'─' * (col_qty + 2)}┬{'─' * (col_unit + 2)}┐",
                 header, sep]
        for a in alerts:
            aid = str(a.get("id", ""))
            name = a.get("name", "")
            qty = str(a.get("quantity", ""))
            unit = a.get("unit", "")
            lines.append(f"  │ {aid.rjust(col_id)} │ {name.ljust(col_name)} │ {qty.rjust(col_qty)} │ {unit.ljust(col_unit)} │")
        lines.append(f"  └{'─' * (col_id + 2)}┴{'─' * (col_name + 2)}┴{'─' * (col_qty + 2)}┴{'─' * (col_unit + 2)}┘")
        lines.append(f"  ⚠️  Total: {len(alerts)} productos con stock bajo")
        return "\n".join(lines)

    # list_products (raw) → lista de productos → tabla
    if isinstance(data, list):
        if not data:
            if tool_name == "get_alerts":
                return "  ✅  No hay productos con stock bajo. ¡Todo en orden!"
            return "  📭  No hay productos que mostrar."
        col_id = max(2, max(len(str(p.get("id", ""))) for p in data))
        col_name = max(6, max(len(p.get("name", "")) for p in data))
        col_qty = max(10, max(len(str(p.get("quantity", ""))) for p in data))
        col_unit = max(8, max(len(p.get("unit", "")) for p in data))
        sep = f"  ├{'─' * (col_id + 2)}┼{'─' * (col_name + 2)}┼{'─' * (col_qty + 2)}┼{'─' * (col_unit + 2)}┤"
        header = f"  │ {'ID'.ljust(col_id)} │ {'Nombre'.ljust(col_name)} │ {'Cantidad'.rjust(col_qty)} │ {'Unidad'.ljust(col_unit)} │"
        lines = [f"  ┌{'─' * (col_id + 2)}┬{'─' * (col_name + 2)}┬{'─' * (col_qty + 2)}┬{'─' * (col_unit + 2)}┐",
                 header, sep]
        for p in data:
            pid = str(p.get("id", ""))
            name = p.get("name", "")
            qty = str(p.get("quantity", ""))
            unit = p.get("unit", "")
            lines.append(f"  │ {pid.rjust(col_id)} │ {name.ljust(col_name)} │ {qty.rjust(col_qty)} │ {unit.ljust(col_unit)} │")
        lines.append(f"  └{'─' * (col_id + 2)}┴{'─' * (col_name + 2)}┴{'─' * (col_qty + 2)}┴{'─' * (col_unit + 2)}┘")
        lines.append(f"  📦  Total: {len(data)} productos")
        return "\n".join(lines)

    # add_product / update_stock → objeto único → resumen
    if isinstance(data, dict):
        name = data.get("name", "")
        qty = data.get("quantity", "")
        unit = data.get("unit", "")
        pid = data.get("id", "")
        # Si add_product detectó que ya existía y lo actualizó
        if data.get("_action") == "updated_existing":
            resultado = f"  🔄  #{pid} {name} → stock actualizado a {qty} {unit} (el producto ya existía)"
        else:
            resultado = f"  ✅  #{pid} {name} → {qty} {unit}"
        # Si es update_stock y queda poco stock (<10), avisar automáticamente
        if tool_name == "update_stock":
            try:
                qty_num = int(qty)
                if qty_num < 10:
                    resultado += f"\n  ⚠️  ¡Atención! {name} está a punto de agotarse ({qty} {unit}). Deberías reponerlo pronto."
            except (ValueError, TypeError):
                pass
        return resultado

    return result_json


# ─── Logging (conversation_log.csv) ────────────────────────────────────────
# Formato: actor, message, tool_call, timestamp
# Append-only: cada sesión añade filas sin sobrescribir

def log_event(actor: str, message: str, tool_call: str = "") -> None:
    """
    Registra un evento en conversation_log.csv.
    - actor: user, agent, tool o system
    - message: contenido del texto o resultado
    - tool_call: nombre de la tool (vacío si no aplica)
    - timestamp: ISO 8601
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    file_exists = os.path.exists(LOG_FILE)

    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists or os.path.getsize(LOG_FILE) == 0:
            writer.writerow(["actor", "message", "tool_call", "timestamp"])
        writer.writerow([actor, message, tool_call, timestamp])
        # Separador visual entre sesiones
        if message == "Sesión de agente finalizada":
            writer.writerow([])

def _compact_history(msgs: list[dict]) -> list[dict]:
    """
    Comprime el historial quitando tool_calls y tool_results intermedios,
    manteniendo solo system + pares user→assistant final.
    Así el contexto no crece sin límite.
    """
    compact: list[dict] = []
    if msgs and msgs[0]["role"] == "system":
        compact.append(msgs[0])
    for m in msgs[1:]:
        if m["role"] == "user":
            compact.append(m)
        elif m["role"] == "assistant" and "tool_calls" not in m:
            compact.append(m)
    if not any(m["role"] == "assistant" and "tool_calls" not in m for m in compact):
        compact.append({"role": "assistant", "content": "Herramientas ejecutadas."})
    return compact

# ─── Cliente GROQ ──────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """Construye el prompt del sistema con el rol y las herramientas disponibles."""
    return """Eres un asistente de IA especializado en la gestión de inventario de una tienda de suministros para cafeterías con dos locales físicos.

Tienes estas herramientas:
- list_products: Ver todo el inventario
- add_product: Añadir un nuevo producto
- update_stock: Actualizar cantidades (positivo = entrada, negativo = salida). Usa el NOMBRE del producto, no el ID.
- get_alerts: Ver productos con stock bajo (<10 unidades)

## REGLAS ABSOLUTAS (incumplirlas causará errores):

1. **UNA SOLA ACCIÓN POR VEZ**: El usuario siempre pide UNA cosa a la vez. Ejecuta SOLO las herramientas necesarias para esa acción. No añadas pasos extra no solicitados.
   - ✅ Si dice "añade 20kg de Café Arábica" o similar → llama SOLO a add_product (una vez, no list_products ni nada más). El sistema ya sabe gestionar el resto internamente, incluso si el producto ya existe (lo actualizará automáticamente sumando la cantidad).
   - ✅ Si dice "resta 5 de café arábica" o "reponemos 20 de Azúcar Blanco" → llama SOLO a update_stock con el NOMBRE del producto (no el ID).
   - ✅ Si dice "enséñame las alertas" o "dame los productos bajos" → llama SOLO a get_alerts.
   - ✅ Si dice "lista productos" o "enséñame el inventario" → llama SOLO a list_products.
   - ❌ NUNCA llames list_products después de add_product.
   - ❌ NUNCA llames get_alerts después de update_stock, a menos que el usuario lo pida explícitamente.
   - ❌ NUNCA llames list_products después de update_stock.

2. **update_stock — USA EL NOMBRE, NO EL ID**: Cuando el usuario pida actualizar stock de un producto, usa `update_stock` con el parámetro `product_name` (string con el nombre del producto). El sistema internamente resolverá el nombre al ID correcto. NO necesitas llamar a list_products primero para buscar IDs.
   - ✅ `update_stock(product_name="Café Arábica Molido", delta=-5)`
   - ✅ `update_stock(product_name="Azúcar Blanco", delta=20)`
   - ❌ NUNCA intentes pasar un ID numérico como product_id.

3. **NO necesitas buscar IDs**: update_stock acepta el nombre del producto directamente. El sistema lo resuelve automáticamente. No llames a list_products antes de update_stock.

4. **NO hagas llamadas paralelas múltiples**: Ejecuta UNA tool a la vez.

5. **Responde en español**, de forma natural, amigable y MUY CONCISA (máximo 2 líneas). No añadas información extra, solo confirma lo que se hizo y pregunta "¿Quieres algo más?".

6. **AVISO DE STOCK BAJO**: Cuando ejecutes `update_stock` con delta NEGATIVO, si la cantidad final queda por debajo de 10, avisa al usuario en tu respuesta de forma sencilla. No llames a get_alerts por tu cuenta.
   - ✅ "He registrado la venta. Quedan 8 — cuidado, está por agotarse. ¿Quieres algo más?"

7. **NO REPITAS LA TABLA EN TEXTO**: Cuando el sistema muestre un resultado (tabla de productos, alertas, stock actualizado, etc.), **NO vuelvas a enumerar los productos en tu respuesta**. Limítate a un comentario breve:
   - ✅ Si el usuario pidió ver el inventario: "Aquí tienes el inventario completo. ¿Quieres algo más?"
   - ✅ Si el usuario pidió las alertas: "Estos son los productos que tienen bajo stock. Deberías reponerlos pronto. ¿Quieres algo más?"
   - ✅ Si el usuario añadió/actualizó stock: "Hecho. ¿Quieres algo más?"
   - ❌ No menciones ningún producto concreto en tu respuesta textual.

8. **RESPUESTAS MÍNIMAS POR ACCIÓN**:
   - **Añadir producto**: confirma solo el nombre y cantidad añadidos. "Hecho. Se ha añadido [producto] con [cantidad] [unidad]. ¿Quieres algo más?"
   - **Actualizar stock**: confirma el cambio. "Listo. Stock actualizado. ¿Quieres algo más?"
   - **Ver inventario**: "Aquí tienes el inventario completo. ¿Quieres algo más?"
   - **Alertas**: "Estos son los productos que tienen bajo stock. Deberías reponerlos pronto. ¿Quieres algo más?" """


def _create_fallback_tool_call(tool_name: str, args_str: str) -> object:
    """Crea un objeto simulando una tool_call para el fallback de texto plano."""
    class _SimulatedFunction:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments
    class _SimulatedToolCall:
        def __init__(self, tname, astr):
            self.id = f"call_fallback_{tname}"
            self.function = _SimulatedFunction(tname, astr)
    return _SimulatedToolCall(tool_name, args_str)


def call_llm(messages: list[dict]) -> dict[str, Any]:
    """
    Envía los mensajes al LLM de GROQ usando la API nativa de function calling.
    Devuelve un dict con:
      - {"response": "texto"} si es respuesta final
      - {"tool": "name", "args": {...}, "message": msg_completo} si es llamada a herramienta
      - {"error": "mensaje"} si hubo un error
    """
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY no configurada. Ejecuta: export GROQ_API_KEY=tu-api-key"}

    try:
        from groq import Groq
    except ImportError:
        return {"error": "La librería 'groq' no está instalada. Ejecuta: pip install groq"}

    client = Groq(api_key=GROQ_API_KEY)

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
        )

        message = response.choices[0].message

        # ── El LLM quiere llamar a una o más herramientas (nativo) ──
        if message.tool_calls:
            return {
                "tool": message.tool_calls,
                "message": message,
            }

        # ── Fallback: El LLM a veces escribe la función como texto plano
        #    en lugar de usar tool_calls nativos. Pueden ser varios formatos:
        #    <function=list_products></function>  (sin args)
        #    <function(list_products){}></function>
        #    <function=add_product>{"name":"..."}</function>
        #    (con igual y argumentos, o con paréntesis)
        content = (message.content or "").strip()
        if content:
            import re

            # Formato 1: <function=nombre></function> (sin argumentos, ej: list_products)
            match_simple = re.search(
                r'<function=(\w+)>\s*</function>',
                content,
            )
            if match_simple:
                tool_name = match_simple.group(1)
                return {
                    "tool": [_create_fallback_tool_call(tool_name, "{}")],
                    "message": message,
                }

            # Formato 2: <function(nombre){args}</function> (con argumentos JSON y paréntesis)
            match_with_args = re.search(
                r'<function\((\w+)\)\s*(\{.*?\})\s*</function>',
                content,
                re.DOTALL,
            )
            if match_with_args:
                tool_name = match_with_args.group(1)
                tool_args_str = match_with_args.group(2)
                return {
                    "tool": [_create_fallback_tool_call(tool_name, tool_args_str)],
                    "message": message,
                }

            # Formato 3: <function=nombre>{args}</function> (con igual y argumentos JSON)
            match_equal_args = re.search(
                r'<function=(\w+)>\s*(\{.*?\})\s*</function>',
                content,
                re.DOTALL,
            )
            if match_equal_args:
                tool_name = match_equal_args.group(1)
                tool_args_str = match_equal_args.group(2)
                return {
                    "tool": [_create_fallback_tool_call(tool_name, tool_args_str)],
                    "message": message,
                }

            # ── El LLM da una respuesta textual normal ──
            return {"response": content}
        else:
            return {"response": "No tengo una respuesta para eso."}

    except Exception as e:
        return {"error": f"Error al comunicarse con GROQ: {str(e)}"}


# ─── Bucle principal del agente ────────────────────────────────────────────
# Observar → Pensar → Actuar → Actualizar → Repetir

def run_agent():
    """
    Bucle principal del agente:
    1. OBSERVAR: Lee el input del usuario desde la terminal
    2. PENSAR: Envía el mensaje al LLM con las definiciones de tools
    3. ACTUAR: Ejecuta la tool seleccionada por el LLM
    4. ACTUALIZAR: Inyecta el resultado de vuelta en el contexto del LLM
    5. REPETIR: Hasta que el LLM dé una respuesta final
    """
    print("=" * 64)
    print("  🤖  AGENTE DE INVENTARIO — Cafetería")
    print("  📦  Gestión de stock por lenguaje natural")
    print("=" * 64)
    print("  Comandos especiales:")
    print("    • salir / exit  — Terminar la sesión")
    print("    • status        — Ver configuración actual")
    print("    • Ctrl+C        — Interrumpir")
    print("-" * 64)

    # Historial completo en memoria para toda la sesión
    messages: list[dict] = [
        {"role": "system", "content": _build_system_prompt()},
    ]

    log_event("system", "Sesión de agente iniciada")

    while True:
        try:
            # ═══════════════ 1. OBSERVAR ═══════════════════════════════
            user_input = input("\n👤  Tú: ").strip()

            if user_input.lower() in ("salir", "exit", "quit"):
                print("\n🤖  Agente: ¡Hasta luego! Que tengas un buen día ☕")
                log_event("agent", "Sesión finalizada por el usuario")
                log_event("system", "Sesión de agente finalizada")
                break

            if user_input.lower() == "status":
                print(f"\n  📡  API:       {API_BASE_URL}")
                print(f"  🤖  Modelo:    {GROQ_MODEL}")
                print(f"  🔑  GROQ Key:  {'✓ Configurada' if GROQ_API_KEY else '✗ NO CONFIGURADA'}")
                print(f"  📝  Log:       {LOG_FILE}")
                continue

            if not user_input:
                continue

            log_event("user", user_input)
            messages.append({"role": "user", "content": user_input})
            # Comprimir historial: quita tool_calls/results intermedios
            # para que el contexto no crezca. Se hace aquí, ANTES del bucle
            # de herramientas, para no borrar resultados a medio procesar.
            messages = _compact_history(messages)

            # ═══════════════ BUCLE HERRAMIENTAS ═══════════════════════
            # Se repite mientras el LLM siga pidiendo llamar a tools
            # Acumula las llamadas internas y solo muestra el resultado relevante

            tool_calls_made: list[dict] = []

            while True:
                # ────────── 2. PENSAR ──────────
                print("\n🤖  Pensando...", end="", flush=True)
                result = call_llm(messages)
                print("\r" + " " * 20 + "\r", end="", flush=True)

                # ── Error de conexión / configuración ──
                if "error" in result:
                    error_msg = result["error"]
                    print(f"\n⚠️  Error: {error_msg}")
                    log_event("agent", f"Error: {error_msg}")
                    messages.append({
                        "role": "assistant",
                        "content": f"Lo siento, ocurrió un error: {error_msg}",
                    })
                    break

                # ────────── 4. RESPUESTA FINAL ──────────
                if "response" in result:
                    response_msg = result["response"]
                    # ── Mostrar solo el resultado relevante de las tools ──
                    if tool_calls_made:
                        # Si el primer tool fue list_products y no es el único,
                        # es una búsqueda interna → mostrar solo el tool final
                        first = tool_calls_made[0]["name"]
                        last = tool_calls_made[-1]
                        last_name = last["name"]
                        is_internal_lookup = (
                            first == "list_products" and len(tool_calls_made) > 1
                        )

                        if is_internal_lookup:
                            # Mostrar solo el resultado de la tool final
                            tmsg = {
                                "add_product": "✅ Producto añadido:",
                                "update_stock": "📦 Stock actualizado:",
                                "get_alerts": "⚠️ Productos con stock bajo:",
                                "list_products": "📋 Inventario completo:",
                            }.get(last_name, f"🔧 {last_name}:")
                            print(f"\n{tmsg}")
                            print(_format_result_display(last_name, last["result"]))
                        else:
                            # Mostrar todos los tools (el usuario pidió verlos)
                            for t in tool_calls_made:
                                tmsg = {
                                    "list_products": "📋 Aquí tienes la lista de productos:",
                                    "get_alerts": "⚠️ Estos son los productos con poco stock:",
                                    "add_product": "➕ Producto añadido correctamente:",
                                    "update_stock": "📦 Stock actualizado:",
                                }.get(t["name"], f"🔧  Usando: {t['name']}")
                                print(f"\n{tmsg}")
                                print(_format_result_display(t["name"], t["result"]))
                    print(f"\n🤖  Agente: {response_msg}")
                    log_event("agent", response_msg)
                    messages.append({"role": "assistant", "content": response_msg})
                    break  # Sale del bucle de herramientas

                # ────────── 3. ACTUAR (tool call/s) ──────────
                if "tool" in result:
                    tool_calls = result["tool"]  # lista de tool_calls
                    llm_message = result["message"]

                    # Procesar SOLO UNA tool call a la vez (evitar paralelismo)
                    tool_call = tool_calls[0]
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments) or {}

                    # Ejecutar la tool llamando a la API
                    try:
                        tool_result = run_tool(tool_name, tool_args)
                        log_event("tool", tool_result, tool_name)
                    except Exception as e:
                        tool_result = json.dumps({"error": str(e)}, ensure_ascii=False)
                        log_event("tool", tool_result, tool_name)

                    # Acumular la llamada para mostrarla al final
                    tool_calls_made.append({
                        "name": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                    })

                    # ────────── 4. ACTUALIZAR ──────────
                    # Construimos el mensaje del asistente con SOLO UNA tool call
                    messages.append({
                        "role": "assistant",
                        "content": llm_message.content or None,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                },
                            }
                        ],
                    })

                    # Añadir el resultado de la tool al historial
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    })

                    # ⬆ Volver a PENSAR con el nuevo contexto

        except KeyboardInterrupt:
            print("\n\n🛑  Sesión interrumpida por el usuario.")
            log_event("system", "Sesión interrumpida (Ctrl+C)")
            log_event("system", "Sesión de agente finalizada")
            break
        except EOFError:
            print("\n\n🛑  Fin de la entrada.")
            break
        except Exception as e:
            error_msg = f"Error en el bucle del agente: {str(e)}"
            print(f"\n⚠️  {error_msg}")
            log_event("system", error_msg)


if __name__ == "__main__":
    run_agent()