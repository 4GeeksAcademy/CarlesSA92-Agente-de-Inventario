# Contexto del Proyecto
- **Objetivo**: Construir un sistema API REST gestionado por un agente IA.
- Diseñado por un desarrollador frontend senior.
- Gestor de inventario de una tienda de suministros para cafeterias con dos locales fisicos. 
- El sistema tiene que registrar entregas, apuntar ventas y avisar cuando un producto este a punto de agotarse (<10 productos)
- Tiene que usarse sistema de lenguaje natural.
- No usar ningun framework de agentes(LanChain, LlamaIndex, AutoGen, etc). El bucle debe implementarse manualmente en Python puro.

# Contexto de la Tarea

## API REST (api/app.py):
- Construida con FastAPI, gestiona los datos de inventario. 
- Expone endpoints para listar productos, registrar nuevos, actualizar cantidades y obtener alertas de stock bajo.
- Los productos se almacenan en un fichero CSV para que los datos persistan entre sesiones.
    - La API almacenará los datos en el fichero llamado "products.csv".
    - Generar este archivo con unos 10 productos base a modo de muestra. Los datos almacenados son: "name", "quantity" y "unit"
- Endpoints: 
    - **GET /inventory**: Devuelve la lista de productos
    - **POST /inventory**: añade un nuevo producto (name, quantity, unit)
    - **PATCH /inventory/{product_id}**: actualiza el stock de un producto existente (acepta valor delta: positivo para entradas de stock, negativo para salidas)
    - **GET /inventory/alerts**: devuelve todos los productos cuya cantidad sea inferior al umbral configurable (por defecto: inferior a 10)
- Todos los endpoints deben devolver codigos de estado HTTP apropiados y mensajes descriptivos de error.

## Agente de IA (agent.py):
- Escrito en Python que se conecte a un LLM (GROQ).
- Utiliza la API REST anterior como conjunto de herramientas.
- El agente funciona en bucle: 
    - **Observar**: leer el mensaje input del usuario
    - **Pensar**: enviar al LLM con las definiciones de tools
    - **Actuar**: llamar a la tool que el LLM seleccionó
    - **Actualizar**: inyectar el resultado de vuelta en el contexto del LLM
    - **Repetir**: hasta que el LLM dé una respuesta final
- Todos los pasos que se hagan deben registrarse en un fichero "conversation_log.csv".
    - Debe mantener en memoria el historial completo de mensajes durante la sesion para que el LLM pueda razonar sobre intercambios anteriores.
    - Cada evento del bucle debe añadirse al fichero "conversation_log.csv" con 4 campos:
        - **actor**: quien escribe el mensaje (user, agent o tool)
        - **message**: contenido del texto o resultado del evento
        - **tool_call**: nombre de la tool llamada (vacío si no aplica)
        - **timestamp**: fecha y hora del evento en formato ISO 8601
    - El fichero es solo de adición (append-only). Cada sesion añade filas, no las sobreescribe.
- El agente debe implementar este ciclo en un unico archivo Python llamado "agent.py".
- Los endpoints de la API seran las tools del Agente. Cada tool debe tener claramente tipados:
    - **name**
    - **descrpition**
    - **parameters**
- Cuando se llame a una tool, el agente debe llamar al endpoint de la API correspondiente e inyectar el resultado de vuelta en el contexto.

# Contexto de la Salida
- Se espera conversación por terminal, no se requiere generar una interface, pagina web o similar para mostrar los resultados.
- Detener el sistema con Ctrl+C, primero el agente y luego la API.
- El fichero conversation_log.csv se escribe de forma incremental, no se pierden datos al denter la ejecución.
- El historial de conversaciones anteriores permanece intacto entre sesiones.
- El bucle debe terminar de forma limpia cuando el LLM devuelva una respuesta final sin llamadas a tools pendientes.
- El agente debe exponer una interfaz CLI sencilla: leer input del usuario en terminal e imprimir respuesta del agente.