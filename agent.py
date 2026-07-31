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
            "description": "Actualiza el stock de un producto existente. Usa delta POSITIVO para entradas (nuevas entregas/reposiciones) y delta NEGATIVO para salidas (ventas, productos usados).",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "ID numérico del producto a actualizar (obtenido de list_products)",
                    },
                    "delta": {
                        "type": "integer",
                        "description": "Cantidad a añadir (positivo, ej: +20) o restar (negativo, ej: -5) del stock actual",
                    },
                },
                "required": ["product_id", "delta"],
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
    if tool_name == "list_products":
        result = _call_api("GET", "/inventory")
        # Compactar: solo IDs, nombres, cantidades para ahorrar tokens
        if isinstance(result, list) and not isinstance(result, dict):
            items = []
            for p in result:
                items.append(f"{p['id']}:{p['name']}({p['quantity']}{p['unit']})")
            return f"LISTA|{'|'.join(items)}"
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    elif tool_name == "add_product":
        result = _call_api("POST", "/inventory", {
            "name": args["name"],
            "quantity": args["quantity"],
            "unit": args["unit"],
        })
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    elif tool_name == "update_stock":
        result = _call_api("PATCH", f"/inventory/{args['product_id']}", {
            "delta": args["delta"],
        })
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    elif tool_name == "get_alerts":
        params = {}
        if "threshold" in args:
            params["threshold"] = args["threshold"]
        result = _call_api("GET", "/inventory/alerts", params)
        # Compactar alertas igual que list_products
        if isinstance(result, list) and not isinstance(result, dict):
            items = []
            for p in result:
                items.append(f"{p['id']}:{p['name']}({p['quantity']}{p['unit']})")
            if not items:
                return "ALERTAS|sin_alertas"
            return f"ALERTAS|{'|'.join(items)}"
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    else:
        return json.dumps({"error": f"Tool desconocida: {tool_name}"}, ensure_ascii=False)


# ─── Formateo de resultados para terminal ─────────────────────────────────

def _format_result_display(tool_name: str, result_json: str) -> str:
    """
    Formatea el resultado de una tool en una representación legible
    para mostrar en la terminal.
    Soporta tanto el formato JSON clásico como el nuevo formato compacto
    (LISTA|... y ALERTAS|...) para ahorrar tokens en el LLM.
    """
    # ── Formato compacto: LISTA|id:nombre(cantidad)|... ──
    if result_json.startswith("LISTA|"):
        parts = result_json.split("|")[1:]  # ["id:nombre(cantidad)", ...]
        if not parts:
            return "  📭  No hay productos que mostrar."
        productos = []
        for p in parts:
            pid, resto = p.split(":", 1)
            # resto tiene formato "Nombre(cantidadunidad)"
            nombre = resto.split("(")[0]
            cant_resto = resto.split("(")[1].rstrip(")")
            productos.append({"id": pid, "name": nombre, "cant_raw": cant_resto})
        # Tabla bonita
        col_id = max(2, max(len(p["id"]) for p in productos))
        col_name = max(6, max(len(p["name"]) for p in productos))
        col_cant = max(10, max(len(p["cant_raw"]) for p in productos))

        sep = f"  ├{'─' * (col_id + 2)}┼{'─' * (col_name + 2)}┼{'─' * (col_cant + 2)}┤"
        header = f"  │ {'ID'.ljust(col_id)} │ {'Nombre'.ljust(col_name)} │ {'Cantidad'.rjust(col_cant)} │"
        lines = [
            f"  ┌{'─' * (col_id + 2)}┬{'─' * (col_name + 2)}┬{'─' * (col_cant + 2)}┐",
            header,
            sep,
        ]
        for p in productos:
            lines.append(f"  │ {p['id'].rjust(col_id)} │ {p['name'].ljust(col_name)} │ {p['cant_raw'].rjust(col_cant)} │")
        lines.append(f"  └{'─' * (col_id + 2)}┴{'─' * (col_name + 2)}┴{'─' * (col_cant + 2)}┘")
        lines.append(f"  📦  Total: {len(productos)} productos")
        return "\n".join(lines)

    # ── Formato compacto: ALERTAS|... ──
    if result_json.startswith("ALERTAS|"):
        parts = result_json.split("|")[1:]
        if not parts or parts[0] == "sin_alertas":
            return "  ✅  No hay productos con stock bajo. ¡Todo en orden!"
        alertas = []
        for p in parts:
            pid, resto = p.split(":", 1)
            nombre = resto.split("(")[0]
            cant_resto = resto.split("(")[1].rstrip(")")
            alertas.append({"id": pid, "name": nombre, "cant_raw": cant_resto})
        col_id = max(2, max(len(a["id"]) for a in alertas))
        col_name = max(6, max(len(a["name"]) for a in alertas))
        col_cant = max(10, max(len(a["cant_raw"]) for a in alertas))
        sep = f"  ├{'─' * (col_id + 2)}┼{'─' * (col_name + 2)}┼{'─' * (col_cant + 2)}┤"
        header = f"  │ {'ID'.ljust(col_id)} │ {'Nombre'.ljust(col_name)} │ {'Cantidad'.rjust(col_cant)} │"
        lines = [
            f"  ┌{'─' * (col_id + 2)}┬{'─' * (col_name + 2)}┬{'─' * (col_cant + 2)}┐",
            header,
            sep,
        ]
        for a in alertas:
            lines.append(f"  │ {a['id'].rjust(col_id)} │ {a['name'].ljust(col_name)} │ {a['cant_raw'].rjust(col_cant)} │")
        lines.append(f"  └{'─' * (col_id + 2)}┴{'─' * (col_name + 2)}┴{'─' * (col_cant + 2)}┘")
        lines.append(f"  ⚠️  Total: {len(alertas)} productos con stock bajo")
        return "\n".join(lines)

    # ── Formato JSON clásico ──
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

    # list_products / get_alerts → lista de productos → tabla
    if isinstance(data, list):
        if not data:
            if tool_name == "get_alerts":
                return "  ✅  No hay productos con stock bajo. ¡Todo en orden!"
            return "  📭  No hay productos que mostrar."
        # Calcular anchos de columna (mínimo el ancho del encabezado)
        col_id = max(2, max(len(str(p.get("id", ""))) for p in data))
        col_name = max(6, max(len(p.get("name", "")) for p in data))
        col_qty = max(10, max(len(str(p.get("quantity", ""))) for p in data))
        col_unit = max(8, max(len(p.get("unit", "")) for p in data))

        sep = f"  ├{'─' * (col_id + 2)}┼{'─' * (col_name + 2)}┼{'─' * (col_qty + 2)}┼{'─' * (col_unit + 2)}┤"
        header = f"  │ {'ID'.ljust(col_id)} │ {'Nombre'.ljust(col_name)} │ {'Cantidad'.rjust(col_qty)} │ {'Unidad'.ljust(col_unit)} │"

        lines = [f"  ┌{'─' * (col_id + 2)}┬{'─' * (col_name + 2)}┬{'─' * (col_qty + 2)}┬{'─' * (col_unit + 2)}┐",
                 header,
                 sep]

        for p in data:
            pid = str(p.get("id", ""))
            name = p.get("name", "")
            qty = str(p.get("quantity", ""))
            unit = p.get("unit", "")
            lines.append(
                f"  │ {pid.rjust(col_id)} │ {name.ljust(col_name)} │ {qty.rjust(col_qty)} │ {unit.ljust(col_unit)} │"
            )

        lines.append(f"  └{'─' * (col_id + 2)}┴{'─' * (col_name + 2)}┴{'─' * (col_qty + 2)}┴{'─' * (col_unit + 2)}┘")
        lines.append(f"  📦  Total: {len(data)} productos")
        return "\n".join(lines)

    # add_product / update_stock → objeto único → resumen
    if isinstance(data, dict):
        name = data.get("name", "")
        qty = data.get("quantity", "")
        unit = data.get("unit", "")
        pid = data.get("id", "")
        return f"  ✅  #{pid} {name} → {qty} {unit}"

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

Tus funciones principales:
1. Consultar el inventario para ver productos y sus cantidades
2. Añadir nuevos productos cuando lleguen
3. Registrar entradas de stock (reposiciones/entregas) y salidas (ventas) SIEMPRE usando la herramienta update_stock
4. Alertar cuando un producto esté cerca de agotarse (menos de 10 unidades)

Tienes acceso a las siguientes herramientas:
- list_products: Ver todo el inventario
- add_product: Añadir un nuevo producto
- update_stock: Actualizar cantidades (positivo = entrada, negativo = salida)
- get_alerts: Ver productos con stock bajo

REGLAS OBLIGATORIAS (incumplirlas causará errores graves):
1. NUNCA digas que actualizaste el stock sin haber llamado a update_stock. Si necesitas modificar cantidades, DEBES usar la herramienta.
2. Cuando el usuario mencione ventas, gastos o salidas de productos: llama a update_stock con delta NEGATIVO.
3. Cuando el usuario mencione entregas, reposiciones o entradas de productos: llama a update_stock con delta POSITIVO.
4. Antes de llamar a update_stock, SIEMPRE usa list_products para obtener el ID correcto del producto.
5. Si hay múltiples productos que actualizar, hazlo UNO POR UNO llamando a update_stock cada vez.
6. Después de cada update_stock, llama a get_alerts para avisar si algún producto está cerca de agotarse.
7. Cuando te pregunten por el inventario, USA SIEMPRE list_products, no respondas de memoria.
8. Responde en español de forma natural y amigable, como un encargado de tienda resolutivo.
9. Al listar productos, formatea cada uno como: "Nombre (cantidad unidad)". Por ejemplo: "Café Arábica Molido (25 kg)", no uses la palabra "con"."""


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
        )

        message = response.choices[0].message

        # ── El LLM quiere llamar a una o más herramientas ──
        if message.tool_calls:
            return {
                "tool": message.tool_calls,
                "message": message,
            }

        # ── El LLM da una respuesta textual ──
        content = (message.content or "").strip()
        if content:
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
                    print(f"\n🤖  Agente: {response_msg}")
                    log_event("agent", response_msg)
                    messages.append({"role": "assistant", "content": response_msg})
                    break  # Sale del bucle de herramientas

                # ────────── 3. ACTUAR (tool call/s) ──────────
                if "tool" in result:
                    tool_calls = result["tool"]  # lista de tool_calls
                    llm_message = result["message"]
                    tool_messages = []  # acumulador para todas las respuestas

                    # Procesar CADA tool call que el LLM haya solicitado
                    for tool_call in tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)

                        print(f"\n🔧  Usando: {tool_name}")
                        if tool_args:
                            args_preview = json.dumps(tool_args, ensure_ascii=False)
                            print(f"     Args: {args_preview}")

                        # Ejecutar la tool llamando a la API (con protección)
                        try:
                            tool_result = run_tool(tool_name, tool_args)
                            print(_format_result_display(tool_name, tool_result))
                            log_event("tool", tool_result, tool_name)
                        except Exception as e:
                            tool_result = json.dumps({"error": str(e)}, ensure_ascii=False)
                            print(f"  ⚠️  Error: {e}")
                            log_event("tool", tool_result, tool_name)

                        # Inyectar el resultado de la tool en el historial
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        })

                    # ────────── 4. ACTUALIZAR ──────────
                    # Construimos el mensaje del asistente con TODAS las tool_calls
                    messages.append({
                        "role": "assistant",
                        "content": llm_message.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in llm_message.tool_calls
                        ],
                    })

                    # Añadir todos los resultados de tools al historial
                    messages.extend(tool_messages)

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