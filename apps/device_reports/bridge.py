"""Local inbox-to-event bridge; existing simulator ingestion is never called."""
from datetime import datetime,timezone
import threading


class DeviceEventBridge:
    def __init__(self,store,repository,device_id,*,clock=None,interval=2):
        self.store,self.repository,self.device_id=store,repository,device_id
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.interval=interval;self._stop=threading.Event();self._thread=None
        self._lock=threading.Lock();self.code=None;self.processed=0

    def sync_once(self):
        with self._lock:
            cursor=self.repository.device_report_cursor(self.device_id)
            rows=self.store.pending(self.device_id,after=cursor,limit=100)
            for row in rows:
                self.repository.import_device_report(row['report'],received_at=row['received_at'],
                    inbox_cursor=row['cursor'],now=self.clock())
                self.processed+=1
            self.code=None
            return len(rows)

    def start(self):
        if self._thread is not None:raise ValueError('DEVICE_EVENT_BRIDGE_ALREADY_STARTED')
        def work():
            while not self._stop.is_set():
                try:self.sync_once()
                except Exception as error:
                    # Saved inbox remains pending; no wire/body/exception details.
                    self.code=getattr(error,'code','DEVICE_EVENT_BRIDGE_UNAVAILABLE')
                self._stop.wait(self.interval)
        self._thread=threading.Thread(target=work,name='device-event-bridge',daemon=False)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(7)
            if self._thread.is_alive():raise ValueError('DEVICE_EVENT_BRIDGE_STOP_FAILED')
