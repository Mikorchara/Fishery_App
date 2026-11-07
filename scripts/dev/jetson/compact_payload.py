# Compact v1 packing uses the existing publisher codec, clock and size limit.


def _compact_v1_fields(value, names):
    return {name: value[name] for name in names if name in value}


def _compact_v1_task(packet, channel):
    if packet is None:
        return None
    if not isinstance(packet, dict):
        raise ValueError('unknown_task_shape')
    body = packet.get(channel, packet)
    if not isinstance(body, dict):
        raise ValueError('unknown_task_result')
    metadata = ('source_kind', 'capture_timestamp')
    result = _compact_v1_fields(packet, metadata)
    # The web reader gives nested task metadata precedence over its envelope.
    result.update({name: body[name] for name in metadata if isinstance(body.get(name), str)})
    if channel == 'measurement':
        counts = ('fish_detected', 'fish_measured', 'fish_uncertain', 'fish_computed',
                  'fish_with_pixel_length', 'fish_geometry_failed', 'fish_skipped')
        if 'fishes' not in body and not any(name in body for name in counts):
            raise ValueError('unknown_measurement_shape')
        result.update(_compact_v1_fields(body, (*counts, 'status', 'calibration_status', 'measurement_note')))
        if 'fishes' in body:
            fishes = body['fishes']
            if not isinstance(fishes, list) or any(not isinstance(fish, dict) for fish in fishes):
                raise ValueError('unknown_fish_shape')
            fish_fields = ('display_id', 'fish_id', 'status', 'status_text', 'length_px', 'length_mm',
                           'physical_length_mm', 'quality_warnings', 'association_status')
            result['fishes'] = [_compact_v1_fields(fish, fish_fields) for fish in fishes]
    else:
        clips = body.get('clips')
        if not isinstance(clips, list) or any(not isinstance(clip, dict) for clip in clips):
            raise ValueError('unknown_behavior_shape')
        result.update(_compact_v1_fields(body, ('source', 'anomalous')))
        result['clips'] = [_compact_v1_fields(clip, ('start_s', 'end_s', 'score', 'anomaly')) for clip in clips]
    return result


def make_compact_v1_packets(source, context, device_id, source_key, now=None):
    """Return one v1 packet, or None so the unchanged full packer can take over."""
    inputs = source.get('inputs')
    if source.get('device_id') != device_id or not isinstance(inputs, dict):
        return None
    if not set(inputs).issubset({'measurement', 'behavior', 'detection'}):
        return None
    if not IDENTIFIER.fullmatch(device_id) or len(source_key) != 64 or any(c not in '0123456789abcdef' for c in source_key):
        return None
    now = now or datetime.now(timezone.utc)
    if instant(context['window']['end']) > now:
        return None
    detection = inputs.get('detection')
    if detection is not None and not isinstance(detection, dict):
        return None
    text = ('精简设备报文 v1。窗口为检测统计时间，体长和行为各用原任务采集时间，各任务未保证逐帧关联。'
            '毫米估计须核对标定状态；异常信号需核查。\n源记录标识：' + source_key)
    if detection is not None and type(detection.get('timestamp')) is int:
        text += '\n独立检测时间（Unix 毫秒）：' + str(detection['timestamp'])
    try:
        measurement = _compact_v1_task(inputs.get('measurement'), 'measurement')
        behavior = _compact_v1_task(inputs.get('behavior'), 'behavior')
        packet = dict(schema_version=1, report_id='webc1-' + source_key[:40],
                      device_id=device_id, sent_at=now.isoformat(), **context,
                      has_abnormality=bool(context['abnormalities']), report_text=text,
                      measurement=measurement, behavior=behavior)
        raw = encode(packet)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None
    if len(raw) > min(LIMIT, 16 * 1024):
        return None
    return [raw], text
