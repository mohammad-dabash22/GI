"""BFS shortest path finder and DFS all-paths finder between two nodes in the graph."""

from collections import deque


def find_shortest_path(entities: list[dict], relationships: list[dict],
                       from_id: str, to_id: str, max_depth: int = 10) -> dict:
    entity_ids = {e["id"] for e in entities}
    if from_id not in entity_ids or to_id not in entity_ids:
        return {"found": False, "error": "Invalid node ID(s)"}

    adj = {}
    edge_map = {}
    for i, r in enumerate(relationships):
        fid, tid = r["from_id"], r["to_id"]
        adj.setdefault(fid, []).append(tid)
        adj.setdefault(tid, []).append(fid)
        edge_map[(fid, tid)] = i
        edge_map[(tid, fid)] = i

    if from_id == to_id:
        return {"found": True, "path_nodes": [from_id], "path_edges": [], "length": 0}

    visited = {from_id}
    queue = deque([(from_id, [from_id], [])])

    while queue:
        current, path_nodes, path_edges = queue.popleft()
        if len(path_nodes) > max_depth:
            break
        for neighbor in adj.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            eidx = edge_map.get((current, neighbor))
            new_edges = path_edges + [eidx]
            new_path = path_nodes + [neighbor]
            if neighbor == to_id:
                return {
                    "found": True,
                    "path_nodes": new_path,
                    "path_edges": [f"edge_{e}" for e in new_edges if e is not None],
                    "length": len(new_path) - 1,
                }
            queue.append((neighbor, new_path, new_edges))

    return {"found": False, "error": f"No path found within {max_depth} hops"}


def find_all_paths(entities: list[dict], relationships: list[dict],
                   from_id: str, to_id: str, max_depth: int = 5, max_paths: int = 10) -> list[dict]:
    entity_ids = {e["id"] for e in entities}
    if from_id not in entity_ids or to_id not in entity_ids:
        return []

    adj = {}
    edge_map = {}
    for i, r in enumerate(relationships):
        fid, tid = r["from_id"], r["to_id"]
        adj.setdefault(fid, []).append(tid)
        adj.setdefault(tid, []).append(fid)
        edge_map[(fid, tid)] = i
        edge_map[(tid, fid)] = i

    results = []

    def dfs(current, visited, path_nodes, path_edges):
        if len(results) >= max_paths:
            return
        if current == to_id:
            results.append({
                "path_nodes": list(path_nodes),
                "path_edges": [f"edge_{e}" for e in path_edges if e is not None],
                "length": len(path_nodes) - 1,
            })
            return
        if len(path_nodes) > max_depth:
            return
        for neighbor in adj.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            eidx = edge_map.get((current, neighbor))
            path_nodes.append(neighbor)
            path_edges.append(eidx)
            dfs(neighbor, visited, path_nodes, path_edges)
            path_nodes.pop()
            path_edges.pop()
            visited.discard(neighbor)

    dfs(from_id, {from_id}, [from_id], [])
    results.sort(key=lambda p: p["length"])
    return results
