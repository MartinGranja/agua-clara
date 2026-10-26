"""Compara el motor propio contra Google OR-Tools (referencia) en recorridos de prueba.

Uso:  pip install ortools   y luego   python scripts/benchmark_ruteo.py
OR-Tools NO es dependencia del sistema: sólo sirve para medir qué tan cerca del óptimo queda el motor propio.
"""
import random
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import routing_engine as eng
from app.services.route_service import CFG


def ortools_best(matrix, n):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    scale = 1000
    # Camino abierto desde la base: nodo ficticio de regreso con costo 0.
    size = n + 2
    d = [[0] * size for _ in range(size)]
    for i in range(n + 1):
        for j in range(n + 1):
            d[i][j] = int(matrix.km[i][j] * scale)
    manager = pywrapcp.RoutingIndexManager(size, 1, [0], [n + 1])
    routing = pywrapcp.RoutingModel(manager)
    cb = routing.RegisterTransitCallback(lambda a, b: d[manager.IndexToNode(a)][manager.IndexToNode(b)])
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = 2
    sol = routing.SolveWithParameters(params)
    return sol.ObjectiveValue() / scale


def main():
    random.seed(7)
    base = (CFG['base']['lat'], CFG['base']['lng'])
    zonas = list(CFG['zonas'].values())
    print('paradas | propio km | OR-Tools km | brecha | propio s | método')
    for n in (6, 8, 10, 12, 14, 18):
        gaps = []
        for _ in range(5):
            z = random.choice(zonas)
            pts = [(z['lat'] + random.uniform(-.03, .03), z['lng'] + random.uniform(-.03, .03)) for _ in range(n)]
            m = eng.Matrix(base, pts, CFG['factor_ruta'], CFG['velocidad_kmh'])
            stops = [{} for _ in pts]
            t0 = time.perf_counter()
            order, method = eng.solve(stops, m)
            own_t = time.perf_counter() - t0
            own = eng.path_cost([i + 1 for i in order], m.km)
            ref = ortools_best(m, n)
            gaps.append((own - ref) / ref * 100)
        print(f'{n:7d} | {own:9.1f} | {ref:11.1f} | {sum(gaps)/len(gaps):5.2f}% | {own_t:8.3f} | {method}')


if __name__ == '__main__':
    main()
