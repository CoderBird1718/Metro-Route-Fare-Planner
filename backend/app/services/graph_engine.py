import heapq
from app.db.sqlite_client import get_sqlite_conn


def _load_graph(conn):
    """
    Loads stations, ride edges (connections) and walking edges (interchanges)
    from SQLite and builds an in-memory adjacency list representation of the
    metro network graph.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, line FROM stations;")
    stations = {row["id"]: {"name": row["name"], "line": row["line"]} for row in cursor.fetchall()}

    # adjacency[node_id] = list of (neighbour_id, weight_minutes, fare_inr, edge_type)
    adjacency = {station_id: [] for station_id in stations}

    cursor.execute("SELECT station_a_id, station_b_id, travel_time_minutes, fare_inr FROM connections;")
    for row in cursor.fetchall():
        adjacency.setdefault(row["station_a_id"], []).append(
            (row["station_b_id"], row["travel_time_minutes"], row["fare_inr"], "ride")
        )

    cursor.execute("SELECT station_from_id, station_to_id, transfer_time_minutes FROM interchanges;")
    for row in cursor.fetchall():
        adjacency.setdefault(row["station_from_id"], []).append(
            (row["station_to_id"], row["transfer_time_minutes"], 0, "interchange")
        )

    return stations, adjacency


def _dijkstra(adjacency, source_ids):
    """
    Multi-source Dijkstra over the metro graph. Returns (dist, prev) dicts where
    prev[node_id] = (previous_node_id, weight, fare, edge_type).
    """
    dist = {node_id: float("inf") for node_id in adjacency}
    prev = {}

    heap = []
    for sid in source_ids:
        dist[sid] = 0
        heapq.heappush(heap, (0, sid))

    visited = set()

    while heap:
        current_dist, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)

        for neighbour, weight, fare, edge_type in adjacency.get(node, []):
            new_dist = current_dist + weight
            if new_dist < dist.get(neighbour, float("inf")):
                dist[neighbour] = new_dist
                prev[neighbour] = (node, weight, fare, edge_type)
                heapq.heappush(heap, (new_dist, neighbour))

    return dist, prev


def get_metro_route(source_name: str, destination_name: str):
    """
    Computes the shortest route (based on travel time) between the source and
    destination metro stations using Dijkstra's algorithm.
    Reads station, connection, and interchange graphs dynamically from SQLite.
    """
    with get_sqlite_conn() as conn:
        stations, adjacency = _load_graph(conn)

    source_ids = [sid for sid, info in stations.items() if info["name"] == source_name]
    destination_ids = [sid for sid, info in stations.items() if info["name"] == destination_name]

    if not source_ids:
        raise ValueError(f"Unknown source station: '{source_name}'")
    if not destination_ids:
        raise ValueError(f"Unknown destination station: '{destination_name}'")

    dist, prev = _dijkstra(adjacency, source_ids)

    reachable_destinations = [
        did for did in destination_ids if dist.get(did, float("inf")) < float("inf")
    ]
    if not reachable_destinations:
        raise ValueError(f"No route found between '{source_name}' and '{destination_name}'")

    end_node = min(reachable_destinations, key=lambda did: dist[did])

    # Reconstruct the path of node ids from source to destination.
    path_ids = [end_node]
    node = end_node
    while node in prev:
        node, _, _, _ = prev[node]
        path_ids.append(node)
    path_ids.reverse()

    # Build ordered itinerary and compute totals.
    ordered_itinerary = []
    total_fare = 0
    total_time = 0
    interchange_count = 0

    for idx, node_id in enumerate(path_ids):
        station_info = stations[node_id]
        entry = {
            "station_name": station_info["name"],
            "line": station_info["line"],
            "is_interchange": False,
            "transfer_to": None,
        }

        if idx < len(path_ids) - 1:
            next_id = path_ids[idx + 1]
            _, weight, fare, edge_type = prev[next_id]
            total_time += weight
            total_fare += fare
            if edge_type == "interchange":
                interchange_count += 1
                entry["is_interchange"] = True
                entry["transfer_to"] = stations[next_id]["line"]

        ordered_itinerary.append(entry)

    return {
        "route_summary": {
            "source": source_name,
            "destination": destination_name,
            "total_fare_inr": total_fare,
            "total_travel_time_minutes": total_time,
            "interchanges_count": interchange_count,
        },
        "ordered_itinerary": ordered_itinerary,
    }
