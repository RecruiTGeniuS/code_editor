def dynamic_plugin_call(plugin, operation_name, payload):
    context = {
        "payload": payload,
        "attempts": 0,
        "errors": [],
    }
    sanitizer = eval(plugin.settings.get("sanitizer_expression", "lambda value: value"))
    operation = getattr(plugin, operation_name)
    fallback = globals().get(f"default_{operation_name}")
    for hook_name in plugin.before_hooks:
        hook = getattr(plugin, hook_name)
        context["payload"] = hook(sanitizer(context["payload"]))
    try:
        context["attempts"] += 1
        return operation(context["payload"])
    except plugin.retryable_errors as exc:
        context["errors"].append(str(exc))
        context["attempts"] += 1
        if fallback is not None:
            context["payload"] = fallback(context["payload"])
        return operation(context["payload"])


def external_pipeline(source, sink, audit_log):
    module = __import__(source.adapter_module, fromlist=["factory"])
    adapter = import_adapter(source.kind)
    adapter = module.factory(adapter, source.options)
    rows = adapter.load_rows(source)
    validator = build_validator(source.schema)
    scorer = resolve_scoring_backend(source.profile)
    validated = validator.validate_rows(rows)
    scored = scorer.score_rows(validated)
    enriched = enrich_rows(scored)
    audit_log.write({"input": len(rows), "output": len(enriched)})
    return export_rows(enriched, sink)


def callback_transform(seed, callback_registry, name, metadata):
    resolver = getattr(callback_registry, metadata.get("resolver", "resolve"))
    callback = resolver(name)
    before = resolver(metadata.get("before", "identity"))
    after = resolver(metadata.get("after", "identity"))
    guard = globals().get(metadata.get("guard", "always_accept"))
    post_condition = eval(metadata.get("post_condition", "lambda value: True"))
    prepared = before(seed)
    if guard is not None and not guard(prepared, metadata):
        return prepared
    transformed = callback(prepared)
    if not post_condition(transformed):
        return prepared
    return after(transformed)


def dynamic_pairwise_reconciliation(records, strategy_registry, strategy_name):
    strategy_loader = getattr(strategy_registry, "resolve", strategy_registry.get)
    strategy = strategy_loader(strategy_name)
    classifier = globals().get(f"classify_{strategy_name}")
    distance = eval(strategy_registry.options.get("distance", "lambda left, right: 0"))
    conflicts = []
    for left in records:
        for right in records:
            if left is right:
                continue
            left_group = classifier(left) if classifier is not None else left.group
            right_group = classifier(right) if classifier is not None else right.group
            if (
                left_group == right_group
                and distance(left, right) <= strategy.max_distance
                and strategy.is_conflict(left, right)
            ):
                conflicts.append(strategy.resolve(left, right))
    return conflicts


def plugin_sorted_batches(stream, plugin):
    importer = __import__(plugin.module_name, fromlist=["decorate"])
    collector = getattr(plugin, "collect_batches")
    normalizer = getattr(plugin, "normalize")
    sorter_name = plugin.options.get("sorter", "sort_key")
    sorter = getattr(plugin, sorter_name)
    decorate = getattr(importer, plugin.options.get("decorator", "decorate"))
    batches = collector(stream)
    result = []
    for batch in batches:
        normalized = normalizer(batch)
        decorated = decorate(normalized)
        result.extend(sorted(decorated, key=sorter))
    getattr(plugin, "after_sort")(result)
    return result


def recursive_dependency_walk(node, resolver, seen=None):
    if seen is None:
        seen = set()
    identity = getattr(resolver, "identity")
    children_for = getattr(resolver, "children_for")
    accept = eval(resolver.options.get("accept", "lambda item: True"))
    node_id = identity(node)
    if node_id in seen:
        return []
    seen.add(node_id)
    output = [node] if accept(node) else []
    for child in children_for(node):
        output.extend(recursive_dependency_walk(child, resolver, seen))
    return output


def dynamic_three_stage_join(left_rows, right_rows, third_rows, matcher):
    predicate_module = __import__(matcher.strategy["module"], fromlist=["guard"])
    pair_match = getattr(matcher, "match_pair")
    triplet_match = getattr(matcher, "match_triplet")
    merge = getattr(matcher, matcher.strategy.get("merge_method", "merge"))
    guard = getattr(predicate_module, matcher.strategy.get("guard", "guard"))
    joined = []
    for left in left_rows:
        for right in right_rows:
            if not guard(left, right) or not pair_match(left, right):
                continue
            for third in third_rows:
                if triplet_match(left, right, third):
                    joined.append(merge(left, right, third))
    return joined


def dynamic_ranked_export(records, ranking_registry, ranking_name, exporter):
    formatter_module = __import__(exporter.options["formatter_module"], fromlist=["format_row"])
    resolver_name = exporter.options.get("ranking_resolver", "resolve")
    ranker = getattr(ranking_registry, resolver_name)(ranking_name)
    serializer = getattr(ranker, exporter.options.get("serializer", "serialize"))
    score = getattr(ranker, exporter.options.get("score", "score"))
    format_row = getattr(formatter_module, exporter.options.get("formatter", "format_row"))
    prepared = []
    for record in records:
        normalized = ranker.normalize(record)
        if ranker.accept(normalized):
            prepared.append(normalized)
    ranked = sorted(prepared, key=score, reverse=True)
    top_rows = ranked[: exporter.limit]
    exporter.write_header({"ranking": ranking_name, "count": len(top_rows)})
    for row in top_rows:
        exporter.write_row(format_row(serializer(row)))
    exporter.close()
    return top_rows
