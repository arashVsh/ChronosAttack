"""Explicit budget reservation for one approved event; raw evidence is untouched."""
import hashlib
import json


def fingerprint(event):
    return hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()


def evidence_class(base, approved_fingerprint, reserve_usd):
    if not isinstance(approved_fingerprint, str) or len(approved_fingerprint) != 64:
        raise ValueError('Invalid approved event fingerprint')
    if reserve_usd != 0.10:
        raise ValueError('Only the approved ten-cent reserve is supported')

    class ReservedEvidence(base):
        def _accept(self, event):
            self._reserved_seen = getattr(self, '_reserved_seen', False)
            self._uncovered_unknown = getattr(self, '_uncovered_unknown', False)
            reserved = fingerprint(event) == approved_fingerprint
            if reserved:
                if (event.get('event') != 'call_failed' or
                        event.get('error_type') != 'RateLimitError' or
                        event.get('cost_usd') is not None or self._reserved_seen):
                    raise ValueError('Invalid or duplicate reserved event')
                self._reserved_seen = True
            if event.get('event') in ('call_complete', 'call_failed') and event.get('cost_usd') is None:
                self._uncovered_unknown |= not reserved
            super()._accept(event)
            if reserved:
                self.spent += reserve_usd
            # This flag governs permission for calls/retries, not raw-cost reporting.
            self.unknown_cost = self._uncovered_unknown

    return ReservedEvidence


class AccountingOutput:
    """Do not mislabel the runner's reserve-inclusive total as measured cost."""
    def __init__(self, stream):
        self.stream = stream
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                event = None
            if isinstance(event, dict) and event.get('event') == 'run_complete':
                event['event'] = 'budget_accounted_run_summary'
                event['budget_accounted_usd'] = event.pop('measured_cost_usd')
                event['uncovered_unknown_cost'] = event.pop('unknown_cost')
                event['approved_reserve_usd'] = 0.10
                event['raw_cost_still_unreported'] = True
                line = json.dumps(event, sort_keys=True)
            self.stream.write(line + '\n')
        return len(text)

    def flush(self):
        self.stream.flush()
