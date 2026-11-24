"""Turn-local selection for explicit questions that need no prior conversation."""

from dataclasses import replace
import re

from apps.ai_backend.history_projection import ProjectionId, project_retained_history

from .sources import SourceRequirement


_CURRENT_OXYGEN = r"(?:此刻|现在|当前)(?:的)?\s*溶解氧(?:\s*(?:数值|读数|值))?"
_AMOUNT = r"(?:是|为)?多少"
_STANDALONE_OXYGEN_READING = re.compile(
    rf"(?:(?:请帮我|帮我|请)\s*)?(?:查询|查|看)(?:一下)?\s*{_CURRENT_OXYGEN}(?:\s*{_AMOUNT})?"
    rf"|(?:请问\s*)?{_CURRENT_OXYGEN}\s*{_AMOUNT}"
)


def current_oxygen_for_turn(request, *, water_allowed):
    query = request.question.strip().rstrip("？?。！!").rstrip()
    return (water_allowed and request.source_requirement is SourceRequirement.AUTO
            and _STANDALONE_OXYGEN_READING.fullmatch(query) is not None)


def project_turn_history(request, native, projection_id, *, water_allowed):
    """Withhold history from the model only when the current readout stands alone."""
    if (projection_id is ProjectionId.UNTRUSTED_TRANSCRIPT_V1
            and native.history_turns_sent and current_oxygen_for_turn(request, water_allowed=water_allowed)):
        messages = native.model_request.messages
        model_request = replace(native.model_request, messages=(messages[0], messages[-1]))
        return replace(native, model_request=model_request, history_turns_sent=0,
                       history_bytes_sent=2), 0  # Serialized empty pairs: [].
    return project_retained_history(request, native, projection_id)
