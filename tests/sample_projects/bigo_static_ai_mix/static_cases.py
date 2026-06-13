def count_positive_orders(orders, minimum_total):
    summary = {
        "accepted": 0,
        "skipped": 0,
        "total_amount": 0,
    }
    for order in orders:
        amount = order.get("amount", 0)
        if amount >= minimum_total and order.get("status") == "paid":
            summary["accepted"] += 1
            summary["total_amount"] += amount
        else:
            summary["skipped"] += 1
    summary["average"] = (
        summary["total_amount"] / summary["accepted"]
        if summary["accepted"]
        else 0
    )
    return summary


def normalize_and_sort_events(events):
    normalized = []
    for event in events:
        if not event.get("enabled", True):
            continue
        normalized.append(
            {
                "id": event.get("id"),
                "timestamp": event.get("timestamp", 0),
                "priority": event.get("priority", 0),
            }
        )
    normalized.sort(key=lambda row: (row["priority"], row["timestamp"]))
    return normalized


def build_similarity_matrix(items):
    tag_sets = {}
    for item in items:
        tag_sets[item["id"]] = set(item.get("tags", ()))

    matrix = {}
    for left in items:
        row = {}
        for right in items:
            if left["id"] == right["id"]:
                row[right["id"]] = 1.0
            else:
                shared = tag_sets[left["id"]] & tag_sets[right["id"]]
                row[right["id"]] = len(shared)
        matrix[left["id"]] = row
    return matrix


def find_event_by_timestamp(events, target_timestamp):
    left = 0
    right = len(events) - 1
    candidate = None
    while left <= right:
        mid = (left + right) // 2
        current = events[mid]["timestamp"]
        if current == target_timestamp:
            return events[mid]
        if current < target_timestamp:
            left = mid + 1
        else:
            candidate = events[mid]
            right = mid - 1
    return candidate


def group_orders_by_region(orders):
    grouped = {}
    for order in orders:
        region = order.get("region") or "unknown"
        bucket = grouped.setdefault(
            region,
            {
                "count": 0,
                "amount": 0,
                "customers": set(),
            },
        )
        bucket["count"] += 1
        bucket["amount"] += order.get("amount", 0)
        customer_id = order.get("customer_id")
        if customer_id:
            bucket["customers"].add(customer_id)
    return grouped


def build_daily_error_report(log_entries):
    report = {}
    for entry in log_entries:
        if entry.get("level") not in {"error", "critical"}:
            continue
        day = entry.get("timestamp", "")[:10]
        service = entry.get("service", "unknown")
        day_bucket = report.setdefault(day, {})
        service_bucket = day_bucket.setdefault(service, {"count": 0, "samples": []})
        service_bucket["count"] += 1
        if len(service_bucket["samples"]) < 5:
            service_bucket["samples"].append(entry.get("message", ""))
    return report


def compute_region_pair_overlaps(regions):
    region_sets = {}
    for region_name, customers in regions.items():
        region_sets[region_name] = set(customers)

    overlaps = {}
    for left_name, left_customers in region_sets.items():
        row = {}
        for right_name, right_customers in region_sets.items():
            if left_name == right_name:
                row[right_name] = len(left_customers)
                continue
            shared = left_customers & right_customers
            row[right_name] = len(shared)
        overlaps[left_name] = row
    return overlaps
