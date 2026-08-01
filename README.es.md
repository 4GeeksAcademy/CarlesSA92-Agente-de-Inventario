# Agente de Inventario — Tienda de Suministros para Cafeterías 🤖☕

Sistema de gestión de inventario con IA que permite administrar el stock de una tienda de suministros para cafeterías mediante **lenguaje natural**. El agente se conecta a GROQ (LLM) y utiliza una API REST como conjunto de herramientas.

## 📦 ¿Qué incluye?

- **API REST** (`api/app.py`) — Construida con FastAPI, gestiona los productos en un archivo CSV.
- **Agente IA** (`agent.py`) — Bucle manual (Observar → Pensar → Actuar → Actualizar) que conversa contigo por terminal.
- **Registro de conversación** (`conversation_log.csv`) — Todas las interacciones quedan registradas automáticamente.

## ⚙️ Requisitos

- Python 3.10 o superior
- Una clave de API de [GROQ](https://console.groq.com) (gratuita)

## 🚀 Cómo usar el proyecto

Necesitarás **dos terminales** abiertas al mismo tiempo.

### 1. Clonar e instalar dependencias

```bash
git clone <tu-repo>
cd <carpeta-del-proyecto>
pip install fastapi uvicorn requests groq
```

### 2. Configurar la clave de GROQ

```bash
export GROQ_API_KEY=tu-api-key
```

> ⚠️ Es necesario ejecutar este comando en **cada terminal** que vayas a usar, o añadirlo a tu `~/.bashrc`.

### 3. Terminal 1 — Arrancar la API (primero)

La API debe estar corriendo **siempre antes** de lanzar el agente.

```bash
uvicorn api.app:app --reload
```

Esto inicia el servidor en `http://localhost:8000`. Puedes probarlo con:

```bash
curl http://localhost:8000/inventory
```

### 4. Terminal 2 — Arrancar el agente

Con la API ya en marcha, lanza el agente:

```bash
python agent.py
```

Verás la interfaz del agente:

```
================================================================
  🤖  AGENTE DE INVENTARIO — Cafetería
  📦  Gestión de stock por lenguaje natural
================================================================
  Comandos especiales:
    • salir / exit  — Terminar la sesión
    • status        — Ver configuración actual
    • Ctrl+C        — Interrumpir
----------------------------------------------------------------

👤  Tú:
```

### 5. Detener el sistema

Pulsa `Ctrl+C` primero en el agente (Terminal 2) y luego en la API (Terminal 1).

---

## 🧪 Prompts de ejemplo para cada herramienta

Pruébalos en orden para ver todas las funcionalidades:

### 📋 list_products — Ver el inventario completo

```
👤  Tú: muéstrame todos los productos del inventario
```

```
👤  Tú: qué productos tenemos en stock?
```

### ➕ add_product — Añadir un producto nuevo

```
👤  Tú: añade un nuevo producto: Leche de Almendras, 10 litros
```

```
👤  Tú: tenemos un producto nuevo, sírvenos 20 bolsas de Té Verde
```

### 📦 update_stock — Actualizar cantidades (entradas y salidas)

**Salida de stock (venta/gasto):**

```
👤  Tú: se han vendido 5 kg de Café Arábica Molido
```

```
👤  Tú: hemos gastado 3 litros de Leche Entera
```

**Entrada de stock (reposición/entrega):**

```
👤  Tú: ha llegado un pedido de 50 paquetes de Galletas de Mantequilla
```

```
👤  Tú: reponemos 20 kg de Azúcar Blanco
```

### ⚠️ get_alerts — Productos con stock bajo

```
👤  Tú: qué productos están cerca de agotarse?
```

```
👤  Tú: muéstrame los productos con menos de 15 unidades
```

### 🔄 Flujo completo (varios pasos seguidos)

```
👤  Tú: se han gastado 10 paquetes de Galletas de Mantequilla y 3 kg de Chocolate en Polvo
```

El agente debería:
1. Usar `list_products` para obtener los IDs
2. Usar `update_stock` para cada producto
3. Usar `get_alerts` para avisar si algo está bajo de stock

---

## 📁 Estructura del proyecto

```
├── api/
│   ├── app.py          # API REST con FastAPI
│   └── products.csv    # Datos del inventario (persistente)
├── agent.py            # Agente IA (bucle manual con GROQ)
├── conversation_log.csv # Historial de todas las sesiones
├── context.md          # Contexto del proyecto
├── learn.json          # Metadatos del template
├── main.py             # Script de inicio (no usado)
├── server.py           # Servidor alternativo (no usado)
├── README.md           # Este archivo en inglés
└── README.es.md        # Este archivo en español
```

## 📝 Registro de conversación

Cada interacción se guarda automáticamente en `conversation_log.csv` con el formato:

| actor | message | tool_call | timestamp |
|-------|---------|-----------|-----------|
| user | se han gastado 5 kg de Café | | 2026-08-01T10:45:10+00:00 |
| tool | LISTA\|1:Café(20kg)\|... | list_products | 2026-08-01T10:45:51+00:00 |
| tool | {"id":1,"quantity":15} | update_stock | 2026-08-01T10:45:52+00:00 |
| agent | Stock actualizado correctamente | | 2026-08-01T10:45:53+00:00 |

## 🛠️ Comandos especiales del agente

Dentro del agente puedes usar:

- `salir` / `exit` — Termina la sesión
- `status` — Muestra la configuración actual (API, modelo, clave, archivo de log)

---

## 📚 Tecnologías utilizadas

- **FastAPI** — Framework para la API REST
- **GROQ (Llama 3.3 70B)** — Modelo de lenguaje para el agente
- **Python 3** — Lenguaje de programación
- **CSV** — Almacenamiento persistente de productos
