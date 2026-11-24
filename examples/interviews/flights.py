sample_flights = [
    # (origin, destination, takeoff-time, landing-time, cost)
    ("ATL", "LAX", "2024-10-27T08:00:00", "2024-10-27T11:00:00", 300),
    ("LAX", "ORD", "2024-10-27T13:00:00", "2024-10-27T19:00:00", 250),
    ("ORD", "JFK", "2024-10-27T20:00:00", "2024-10-27T22:00:00", 200),
    ("JFK", "ATL", "2024-10-28T09:00:00", "2024-10-28T11:00:00", 150),
    ("ATL", "DFW", "2024-10-28T12:00:00", "2024-10-28T13:30:00", 220),
    ("DFW", "SFO", "2024-10-28T14:30:00", "2024-10-28T16:30:00", 280),
    ("SFO", "SEA", "2024-10-28T17:00:00", "2024-10-28T18:30:00", 150),
    ("SEA", "MIA", "2024-10-28T20:00:00", "2024-10-29T04:00:00", 350),
    ("MIA", "IAH", "2024-10-29T06:00:00", "2024-10-29T08:00:00", 180),
    ("IAH", "BOS", "2024-10-29T09:00:00", "2024-10-29T12:00:00", 220),
    ("BOS", "ORD", "2024-10-29T13:00:00", "2024-10-29T15:00:00", 210),
    ("ORD", "SFO", "2024-10-29T16:00:00", "2024-10-29T18:00:00", 270),
    ("SFO", "ATL", "2024-10-29T19:00:00", "2024-10-29T21:00:00", 320),
    ("MIA", "JFK", "2024-10-30T09:00:00", "2024-10-30T11:00:00", 190),
    ("JFK", "DFW", "2024-10-30T12:00:00", "2024-10-30T14:00:00", 260),
    ("DFW", "SEA", "2024-10-30T15:00:00", "2024-10-30T16:00:00", 200),
    ("SEA", "LAX", "2024-10-30T17:00:00", "2024-10-30T18:00:00", 230),
    ("LAX", "MIA", "2024-10-30T19:00:00", "2024-11-01T04:00:00", 340),
    ("MIA", "BOS", "2024-11-01T06:00:00", "2024-11-01T08:00:00", 160),
    ("BOS", "ATL", "2024-11-01T09:00:00", "2024-11-01T11:00:00", 210),
]

# Given a list of available flights (sorted by takeoff time)
# find the cheapest possible route between 2 cities
#  - leave at any time, any number/duration of layovers
#  - assume we can make instant connections
#  - if no route is possible return None


###########################################################
# Solution

from datetime import datetime  # noqa
from collections import namedtuple, defaultdict
from heapq import heappush, heappop

Flight = namedtuple("Flight", ["origin", "destination", "start", "end", "cost"])


def _debug_print(txt):
    print(txt)


def find_best_route_dfs(flights, origin, destination):
    allflights = [
        Flight(
            row[0],
            row[1],
            datetime.fromisoformat(row[2]),
            datetime.fromisoformat(row[3]),
            row[4],
        )
        for row in flights
    ]

    # Idea is to build a graph of makeable connections
    # this will let us search the graph efficiently using BFS/DFS

    graph = defaultdict(list)

    for flight in allflights:
        graph[flight.origin].append(flight)

    _debug_print("\n\n==== FULL GRAPH ===\n")
    for k, v in graph.items():
        _debug_print(k)
        for flight in v:
            _debug_print(f"\t{flight}")

    def dfs(origin, finaldest, start, depth=0):
        """Depth first search for routes from origin to dest starting at time"""
        bestcost = None
        dbg_indent = "\t" * depth
        _debug_print(f"{dbg_indent} DFS {origin}->{finaldest} start={start}")
        connections = [f for f in graph[origin] if f.start > start]
        for connection in connections:
            _debug_print(f"{dbg_indent} Connect {connection}")
            if connection.destination == finaldest:
                _debug_print(f"{dbg_indent} FOUND DEST")
                return connection.cost

            remainder = dfs(
                connection.destination, finaldest, connection.end, depth + 1
            )
            if remainder is not None:
                cost = connection.cost + remainder
                _debug_print(f"{dbg_indent} viable route cost={cost}")
                bestcost = cost if not bestcost else min(cost, bestcost)
        return bestcost

    cost = dfs(origin, destination, datetime.min)
    return cost


def find_best_route_dijkstras(flights, origin, destination):
    """A more efficient graph search using Dijkstra's"""
    allflights = [
        Flight(
            row[0],
            row[1],
            datetime.fromisoformat(row[2]),
            datetime.fromisoformat(row[3]),
            row[4],
        )
        for row in flights
    ]
    graph = defaultdict(list)

    for flight in allflights:
        graph[flight.origin].append(flight)

    min_heap = [(0, origin, datetime.min)]
    visited = {}

    _debug_print(f"find_best_route_dijkstras {origin} -> {destination}")
    while min_heap:
        cur_cost, cur_city, cur_time = heappop(min_heap)
        _debug_print(
            f"Heap iter cur_cost={cur_cost} cur_city={cur_city} cur_time={cur_time}"
        )

        if cur_city == destination:
            return cur_cost

        if cur_city in visited and visited[cur_city] <= cur_cost:
            continue
        visited[cur_city] = cur_cost

        for flight in graph[cur_city]:
            if flight.start >= cur_time:
                total_cost = cur_cost + flight.cost
                heappush(min_heap, (total_cost, flight.destination, flight.end))

    return None


def find_best_route(flights, origin, destination):
    # return find_best_route_dfs(flights, origin, destination)
    return find_best_route_dijkstras(flights, origin, destination)


def test_routing():
    assert find_best_route(sample_flights, "ATL", "ORD") == 550
    assert find_best_route(sample_flights, "ATL", "MIA") == 640


def test_no_route():
    assert find_best_route(sample_flights, "ATL", "The Moon") is None
