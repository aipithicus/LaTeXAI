"""Remaining work is independent of whether a source occurrence needs a file."""


def work_classification(reason, stage, *, dependency="none", materialization=None, next_step=None):
    if dependency not in {"none", "possible", "required"}:
        raise ValueError("Unknown dependency certainty")
    if materialization is None:
        materialization = {"none": "not_required", "possible": "undetermined", "required": "pending"}[dependency]
    if materialization not in {"not_required", "undetermined", "pending", "prepared"}:
        raise ValueError("Unknown materialization state")
    if dependency == "possible" and materialization == "pending":
        raise ValueError("A possible dependency is not an established payload request")
    if next_step is None:
        next_step = ("binding_knowledge" if stage == "binding" else
            "dependency_context" if dependency == "possible" else
            "resource_resolution" if materialization == "pending" else
            "reading_resolution" if stage == "preparation" else "interpretation")
    return {"dependency": dependency, "materialization": materialization, "next_step": next_step}
