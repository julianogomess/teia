"""Rate limiting em memória (janela deslizante) e limite de concorrência.

Estado em memória de processo: suficiente para uma instância única (v1).
Para múltiplas instâncias, troque a implementação por Redis mantendo a
mesma interface (hit/acquire/release) — nada mais no código precisa mudar.
"""

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._events = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int) -> bool:
        """Registra uma tentativa e devolve True se ainda está dentro do limite."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class ConcurrencyLimiter:
    def __init__(self):
        self._counts = defaultdict(int)
        self._lock = Lock()

    def acquire(self, key: str, limit: int) -> bool:
        with self._lock:
            if self._counts[key] >= limit:
                return False
            self._counts[key] += 1
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._counts[key] = max(0, self._counts[key] - 1)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


# Singletons usados pelos routers
login_limiter = SlidingWindowLimiter()   # chave: IP
chat_limiter = SlidingWindowLimiter()    # chave: user id
chat_concurrency = ConcurrencyLimiter()  # chave: user id
