def summarize_customer_activity(events, customer_id):
    summary = {
        "customer_id": customer_id,
        "orders": 0,
        "refunds": 0,
        "last_seen": None,
    }
    for event in events:
        if event.get("customer_id") != customer_id:
            continue
        event_type = event.get("type")
        if event_type == "order":
            summary["orders"] += 1
        elif event_type == "refund":
            summary["refunds"] += 1
        timestamp = event.get("timestamp")
        if summary["last_seen"] is None or timestamp > summary["last_seen"]:
            summary["last_seen"] = timestamp
    return summary


def rebuild_priority_index(tickets):
    index = {}
    ordered = sorted(
        tickets,
        key=lambda item: (
            item.get("priority", 0),
            item.get("created_at", 0),
            item.get("id", ""),
        ),
    )
    for position, ticket in enumerate(ordered):
        queue_name = ticket.get("queue", "default")
        index.setdefault(queue_name, []).append(
            {
                "position": position,
                "ticket_id": ticket.get("id"),
                "owner": ticket.get("owner"),
            }
        )
    return index


def match_related_incidents(incidents, matcher):
    related = []
    for left in incidents:
        left_key = matcher.fingerprint(left)
        for right in incidents:
            if left.get("id") == right.get("id"):
                continue
            if matcher.same_cluster(left_key, matcher.fingerprint(right)):
                related.append((left.get("id"), right.get("id")))
    return related


def run_enrichment_workflow(records, workflow_registry, workflow_name, audit):
    workflow = workflow_registry.resolve(workflow_name)
    prepared = workflow.prepare(records)
    enriched = []
    for record in prepared:
        enriched_record = workflow.enrich(record)
        if workflow.should_publish(enriched_record):
            enriched.append(enriched_record)
    audit.write(
        {
            "workflow": workflow_name,
            "input": len(records),
            "published": len(enriched),
        }
    )
    return workflow.finalize(enriched)


def rebuild_permission_closure(root_role, role_repository, policy_plugin):
    visited = set()
    closure = []
    stack = [root_role]
    while stack:
        role = stack.pop()
        role_key = role_repository.key_for(role)
        if role_key in visited:
            continue
        visited.add(role_key)
        closure.append(policy_plugin.normalize(role))
        for child_role in role_repository.children(role):
            if policy_plugin.can_inherit(role, child_role):
                stack.append(child_role)
    return closure
