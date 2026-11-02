# Módulo B · Recorrido del día

Pantalla **Recorrido del día** (misma clave que el panel de admin). Flujo: anotaciones de Martín → reglas de Agua Clara → clientes → orden de visita → horarios → un mensaje por zona y equipo.

## Cómo se usa
1. Panel → *Recorrido del día* → **Base de clientes** → cargar el CSV de clientes (`Nombre, Teléfono, Maps, Observaciones`; opcionales: `Zona, Alias, Día habitual, Vehículo, Dirección`). Sin importar nada funciona con clientes ficticios de demostración.
2. Pegar las anotaciones del día (formato abajo), elegir **hora de inicio** y tocar **Armar recorrido**.
3. Por cada zona y equipo se obtiene el mensaje listo (*Copiar mensaje* o *Abrir en WhatsApp*).

## Formato de la lista
```
VIERNES                       ← día
ALTA GRACIA 11 y 11           ← zona (los números: total de piletas de cada equipo; es un control)
CLIO AZUL:                    ← equipo
//Vale Maizon 0 limp 2c 1p 13:30
```
Cada línea de cliente: `[prefijo][Nombre] [N limp] [productos] [notas] [horario]`. Sólo el nombre es obligatorio.

| Prefijo | Significado | ¿Va? | Divisor |
|---|---|---|---|
| `//` | Quincenal, le toca esta semana | Sí | 2 |
| `/` | Quincenal, no le toca | No | — |
| `.` | Limpieza única | Sí | sin productos |
| (ninguno) + `N limp` | Semanal | Sí | 4 |
| (ninguno) sin `limp` | Mensual o eventual | Sí | sin productos |

- **`N limp`** nunca aparece en el mensaje. `0 limp` con productos = primera limpieza del mes → *Dejar* (productos del mes) y además *Colocar* (dosis del día). `-1 limp` (le deben la limpieza) → *Colocar* normal. Otro valor → sólo *Colocar*.
- **Productos**: `Nc` = N kg de cloro, `Np` = N kg de pastillas (4 por kg). Negativo (`-1c`, `-1p`) = el cliente debe ese producto: no se deja ni se coloca. Dosis: cloro = kg ÷ divisor; pastillas = (p × 4) ÷ divisor. Ejemplos: `2c 1p` quincenal → *Colocar 1 kg cloro + 2 pastillas*; semanal → *Colocar ½ kg cloro + 1 pastilla*.
- **Notas**: texto suelto (`llevar sacahojas`) va entre paréntesis con mayúscula inicial; lo que ya viene entre paréntesis se copia tal cual. Un `1c` dentro de una nota (`llevar 1c`) no es un producto.
- **Indicación puntual** (`esta vez solo dejar 1c`, `solo colocar`, `no dejar`…) reemplaza la regla automática.
- **Línea sin cliente propio** (`Dejar 1c a Franco Soriano`): entra como ítem con el texto tal cual, más teléfono y ubicación de ese cliente. No cuenta como pileta en el título.
- **Cambios de último momento**: `Cancela Vale Maizon` saca al cliente y recalcula la cantidad del título; `Correr las siguientes 3 piletas` (opcional `15 min`) resta 30 min (o el valor indicado) sólo a esas piletas, las siguientes anotadas después de esa línea.

## Mensaje
```
VIERNES
ALTA GRACIA – CLIO AZUL (9)

13:30 Vale Maizon (Dejar 2 kg cloro + 1 kg pastillas, Colocar 1 kg cloro + 2 pastillas)
📞 3513453993
🏠 Maipú 146        ← sólo si el cliente tiene dirección
📝 notas fijas      ← sólo si el cliente tiene notas fijas en la base
📍 https://maps.google.com/?q=...
```
Sin productos, el nombre va sin paréntesis. Si el cliente no está en la base (o hay dudas), igual figura con `FALTA` en teléfono y ubicación y se lista en *A confirmar*.

## Horarios
- Se ingresa una **hora de inicio**; cada pileta cuenta **30 minutos** (configurable en pantalla). Por defecto no se suma traslado: casilla *Sumar tiempo de traslado* si se quiere.
- Una pileta con horario escrito (`13:30`) **se respeta**: el equipo espera si llega antes, y si no llega a tiempo se avisa. El resto se acomoda alrededor.
- Un mismo equipo con dos zonas continúa el reloj de la zona anterior; una entrega suelta ("Dejar 1c a …") no suma tiempo; una pileta con hora fija se atiende a esa hora y el reloj sigue desde ahí (+30 min).

## Equipos
El encabezado de la lista manda; si no hay, se usa el *Vehículo* de la base; si no, y la zona declara dos números (`11 y 11`), se reparte por cercanía respetando esos tamaños.

## Base de clientes
Teléfono normalizado a 10 dígitos (sin +54 9, espacios ni guiones). Búsqueda sin tildes ni mayúsculas, con parte del nombre (`Marcos Lamber`) y con **alias** (`Coty`). Si hay varias coincidencias se elige la de la misma zona (`Daniela` en Alta Gracia ≠ en Despeñaderos); mismo nombre con distinto teléfono se distingue escribiendo el teléfono de 10 dígitos en la línea. La dirección se toma de la columna Dirección o se reconoce en Observaciones (`Maipú 146`).

## Orden de visita
Dentro de cada zona y equipo: solución exacta hasta 12 paradas y heurística (inserción + 2-opt + or-opt) con más, con penalización por llegar tarde a un horario escrito. Google OR-Tools sólo se usa como referencia (`scripts/benchmark_ruteo.py`, requiere `pip install ortools`): brecha ≤ 0,02 % hasta 12 paradas y ≤ 0,7 % con 18 (`docs/benchmark_ruteo.txt`). Distancia = línea recta × 1,35 (ajustable en `app/data/ruteo.yaml`).

## Archivos
`app/services/route_rules.py` (productos y dosis) · `route_parser.py` (lista y nombres) · `route_service.py` (bloques, horarios, mensaje) · `routing_engine.py` · `client_base.py` · `route_geo.py` · `src/route.js`.

## Pruebas
`python -m pytest tests -q` → 159 pruebas (72 del Módulo B): tabla de dosis, prefijos, notas, formato, horarios, cancelaciones, correr piletas, alias, teléfono, importación y API.

## Datos personales y límites
- La base real de clientes **no va en el repositorio ni en el ZIP**: se importa desde el panel. `app/data/clientes_demo.csv` es ficticio.
- Un link corto de Maps (`maps.app.goo.gl`) no tiene coordenadas legibles: se usa el centro de la zona y se avisa. Con `maps.google.com/?q=lat,lng` queda exacto.
- Distancias estimadas, sin tráfico ni calles. El mensaje se envía copiando o con `wa.me`; el envío automático a empleados es Fase 2.


## Analíticas del recorrido (v6)

Cada recorrido calculado guarda un registro numérico (sin nombres ni teléfonos) y la vista **Analíticas** lo resume.

- **Tres criterios comparados:** orden en que se anotó, vecino más cercano y optimizado. El vecino más cercano ignora los horarios pedidos, por eso solo se compara en los bloques sin hora fija (misma restricción para los tres).
- **Ahorro:** kilómetros, minutos de traslado (38 km/h), litros y pesos de combustible (9 L/100 km y $1.500/L, editables en `app/data/ruteo.yaml`). Un recorrido con horas fijas puede resultar más largo que el orden anotado: cumplir los horarios tiene prioridad sobre los kilómetros.
- **Calidad de la solución:** bloques resueltos de forma exacta (Held-Karp, hasta 12 paradas) o con heurística, porcentaje de paradas con ubicación exacta y tiempo de cálculo.
- **Resultado real:** en "Recorridos guardados" se cargan kilómetros reales y hora de fin (`PATCH /api/admin/routes/{id}/real`). Analíticas calcula MAE, MAPE y sesgo de la estimación.
- **Exportación:** `GET /api/admin/export/rutas` (CSV).
- **Limitación:** las distancias son línea recta x 1,35, no calles reales; los ahorros son estimaciones del modelo hasta contar con resultados reales cargados.
