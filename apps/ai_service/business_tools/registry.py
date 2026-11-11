"""Explicit business Tool assembly; known Policy names never create handlers."""
from functools import partial
from apps.ai_backend.tools import ToolRegistry, ToolDefinition
from . import active_events, current_water_quality, fishery_knowledge, water_quality_history, water_quality_score


# A stored name remains inert unless the separate score trial is approved.
WATER_QUALITY_SCORE = water_quality_score.WATER_QUALITY_SCORE
KNOWN_TOOL_NAMES = (current_water_quality.CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE,
                    fishery_knowledge.SEARCH_FISHERY_KNOWLEDGE)
# The shared user Policy file keeps its original names. Candidates use an
# isolated Policy; product History assembly requires its own approved trial.
FORMAL_TOOL_NAMES = (current_water_quality.CURRENT_WATER_QUALITY, fishery_knowledge.SEARCH_FISHERY_KNOWLEDGE)
HISTORY_CANDIDATE_TOOL_NAMES = (*FORMAL_TOOL_NAMES, water_quality_history.WATER_QUALITY_HISTORY)


def bind_tools(monitoring, device_id, knowledge, *, formal=None, include_history=False,
               include_knowledge=True, include_score=False, include_active_events=False,
               board_device_id=None):
    # Internal composition only. Existing Web callers retain their two/three
    # tools and Knowledge requirement; no channel/authorization entry is added.
    if type(include_history) is not bool or type(include_knowledge) is not bool or type(include_score) is not bool:
        raise ValueError("INVALID_BUSINESS_TOOL_ASSEMBLY")
    if formal is not None and (water_quality_history.WATER_QUALITY_HISTORY in
            tuple(d.name for d in formal.model_definitions())) != include_history:
        raise ValueError("INVALID_BUSINESS_TOOL_ASSEMBLY")
    if formal is not None and (WATER_QUALITY_SCORE in tuple(d.name for d in formal.model_definitions())) != include_score:
        raise ValueError('INVALID_BUSINESS_TOOL_ASSEMBLY')
    if type(include_active_events) is not bool or (board_device_id is not None and not include_active_events):
        raise ValueError('INVALID_BUSINESS_TOOL_ASSEMBLY')
    # One formal definition owner; only the frozen device's water Handler changes.
    water_definition = (formal.lookup(current_water_quality.WATER_DEFINITION.name).model_definition
        if formal else current_water_quality.WATER_DEFINITION)
    entries = [ToolDefinition(water_definition,
        partial(current_water_quality.water_payload, monitoring, device_id))]
    if include_knowledge:
        entries.append(formal.lookup(fishery_knowledge.KNOWLEDGE_DEFINITION.name) if formal else ToolDefinition(
            fishery_knowledge.KNOWLEDGE_DEFINITION,
            partial(fishery_knowledge.search_fishery_knowledge, service=knowledge),
            validate_arguments=fishery_knowledge.validate_arguments))
    if include_history:
        definition = (formal.lookup(water_quality_history.WATER_QUALITY_HISTORY).model_definition
                      if formal else water_quality_history.HISTORY_DEFINITION)
        entries.append(ToolDefinition(definition,
            partial(water_quality_history.history_payload, monitoring=monitoring, device_id=device_id),
            validate_arguments=water_quality_history.validate_arguments))
    if include_score:
        definition=formal.lookup(WATER_QUALITY_SCORE).model_definition if formal else water_quality_score.SCORE_DEFINITION
        entries.append(ToolDefinition(definition,partial(water_quality_score.score_payload,monitoring,device_id)))
    if include_active_events:
        entries.append(ToolDefinition(active_events.ACTIVE_EVENTS_DEFINITION,
            partial(active_events.active_events_payload, monitoring, device_id, board_device_id=board_device_id)))
    return ToolRegistry(entries)
