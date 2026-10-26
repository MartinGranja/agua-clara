"""Módulo B · ordena las paradas de cada equipo para minimizar el tiempo de traslado.

Método: solución exacta (Held-Karp) hasta 12 paradas libres y heurística (inserción más barata + 2-opt + or-opt)
con hora fija respetada cuando hay más. Google OR-Tools se usa sólo como referencia de comparación (scripts/).
"""
from itertools import combinations
from math import asin, cos, radians, sin, sqrt

EXACT_LIMIT = 12


def haversine_km(a, b):
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(h))


class Matrix:
    def __init__(self, depot, points, road_factor, speed_kmh, clock_travel=True):
        self.nodes = [depot] + list(points)          # índice 0 = origen; i+1 = parada i
        self.km = [[haversine_km(a, b) * road_factor for b in self.nodes] for a in self.nodes]
        self.speed = speed_kmh
        self.clock_travel = clock_travel             # False: el horario avanza sólo por el tiempo de cada pileta

    def minutes(self, i, j):
        return self.km[i][j] / self.speed * 60

    def clock(self, i, j):
        return self.minutes(i, j) if self.clock_travel else 0.0


def path_cost(order, dist):
    """Costo de un camino abierto que sale de la base (nodo 0). `order` usa índices de nodo (1..n)."""
    total, prev = 0.0, 0
    for n in order:
        total += dist[prev][n]
        prev = n
    return total


def held_karp(nodes, dist):
    """Camino abierto óptimo desde la base por todos los nodos (n ≤ EXACT_LIMIT)."""
    n = len(nodes)
    if n <= 1:
        return list(nodes)
    best = {}
    for k, node in enumerate(nodes):
        best[(1 << k, k)] = (dist[0][node], None)
    for size in range(2, n + 1):
        for subset in combinations(range(n), size):
            mask = sum(1 << k for k in subset)
            for k in subset:
                prev_mask = mask ^ (1 << k)
                options = [(best[(prev_mask, m)][0] + dist[nodes[m]][nodes[k]], m) for m in subset if m != k]
                best[(mask, k)] = min(options)
    full = (1 << n) - 1
    end = min(range(n), key=lambda k: best[(full, k)][0])
    order, mask, k = [], full, end
    while k is not None:
        order.append(nodes[k])
        prev = best[(mask, k)][1]
        mask ^= 1 << k
        k = prev
    return order[::-1]


LATE_PENALTY = 20  # cada minuto de retraso sobre la hora pedida pesa como 20 minutos de ruta


def objective(order, stops, matrix, start_min):
    """Hora de fin + penalización por llegar tarde a una hora pedida (las paradas sin hora no tienen penalización)."""
    t, prev, late, travel = start_min, 0, 0.0, 0.0
    for idx in order:
        node = idx + 1
        t += matrix.clock(prev, node)
        travel += matrix.minutes(prev, node)
        want = stops[idx].get('time')
        if want is not None:
            if t < want:
                t = want
            else:
                late += t - want
        t += stops[idx].get('service', 25)
        prev = node
    # Con reloj plano el fin no depende del orden: el traslado desempata y se minimiza igual.
    return t + LATE_PENALTY * late + (0 if matrix.clock_travel else travel)


def local_search(order, cost):
    """2-opt y or-opt (mover 1 a 3 paradas) hasta que ninguna mejora baje el costo."""
    order, best = list(order), cost(order)
    improved = True
    while improved:
        improved = False
        n = len(order)
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                c = cost(cand)
                if c < best - 1e-9:
                    order, best, improved = cand, c, True
        for size in (1, 2, 3):
            for i in range(len(order) - size + 1):
                seg, rest = order[i:i + size], order[:i] + order[i + size:]
                for pos in range(len(rest) + 1):
                    cand = rest[:pos] + seg + rest[pos:]
                    c = cost(cand) if cand != order else best
                    if c < best - 1e-9:
                        order, best, improved = cand, c, True
    return order


def cheapest_insertion(seed, free, cost):
    order = list(seed)
    for node in free:
        order.insert(min((cost(order[:p] + [node] + order[p:]), p) for p in range(len(order) + 1))[1], node)
    return order


def solve(stops, matrix, start_min=0):
    """Orden de visita (índices de `stops`). Una parada puede traer 'time' (minutos del día) como hora pedida."""
    n = len(stops)
    if n == 0:
        return [], 'exacto'
    dist = matrix.km
    if all(s.get('time') is None for s in stops) and n <= EXACT_LIMIT:
        return [k - 1 for k in held_karp(list(range(1, n + 1)), dist)], 'exacto'
    cost = lambda o: objective(o, stops, matrix, start_min)
    idx = list(range(n))
    nn, cur, left = [], 0, set(idx)
    while left:
        nxt = min(left, key=lambda x: dist[cur][x + 1])
        nn.append(nxt)
        left.remove(nxt)
        cur = nxt + 1
    by_time = sorted(idx, key=lambda i: (stops[i].get('time') is None, stops[i].get('time') or 0))
    starts = [nn, cheapest_insertion([], idx, cost), by_time]
    return min((local_search(s, cost) for s in starts), key=cost), 'heurístico'


def schedule(order, stops, matrix, start_min, tolerance):
    """Horario estimado: traslado + tiempo de servicio; si hay hora fija y se llega antes, espera."""
    t, prev, rows, km = start_min, 0, [], 0.0
    for idx in order:
        node = idx + 1
        t += matrix.clock(prev, node)
        km += matrix.km[prev][node]
        want = stops[idx].get('time')
        late = 0
        if want is not None:
            if t < want:
                t = want
            elif t - want > tolerance:
                late = round(t - want)
        arrive = t
        t += stops[idx].get('service', 25)
        rows.append({'index': idx, 'arrive': round(arrive), 'leave': round(t), 'late': late})
        prev = node
    return rows, km


def evaluate(order, stops, matrix, start_min, tolerance):
    rows, km = schedule(order, stops, matrix, start_min, tolerance)
    travel = sum(matrix.minutes(a, b) for a, b in zip([0] + [i + 1 for i in order[:-1]], [i + 1 for i in order]))
    return {'rows': rows, 'km': km, 'travel': travel, 'end': rows[-1]['leave'] if rows else start_min}
