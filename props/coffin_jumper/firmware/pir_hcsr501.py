import machine, time

class PIRLatch:
    def __init__(self, pin_no, *, pull=machine.Pin.PULL_DOWN,
                 hold_ms=1500, debounce_ms=300, warmup_ms=5000):
        """
        hold_ms: how long 'active()' stays True after a motion edge
        debounce_ms: minimum time between edges
        warmup_ms: ignore PIR edges for this long after boot
        """
        self.pin = machine.Pin(pin_no, machine.Pin.IN, pull)
        self.hold_ms = hold_ms
        self.debounce_ms = debounce_ms
        self.warmup_deadline = time.ticks_add(time.ticks_ms(), warmup_ms)

        self._last_edge = 0
        self._latched_until = 0
        self._pending = False   # becomes True on new motion; you consume it

        # Keep ISR tiny: just timestamp + flags
        self.pin.irq(trigger=machine.Pin.IRQ_RISING, handler=self._irq)

    def _irq(self, _):
        now = time.ticks_ms()
        # ignore during warmup
        if time.ticks_diff(now, self.warmup_deadline) < 0:
            return
        # debounce
        if time.ticks_diff(now, self._last_edge) < self.debounce_ms:
            return
        self._last_edge = now
        self._latched_until = time.ticks_add(now, self.hold_ms)
        self._pending = True

    # --- You use these from your main loop ---

    def active(self) -> bool:
        """True while within the hold window after last motion edge."""
        return time.ticks_diff(self._latched_until, time.ticks_ms()) > 0

    def pending(self) -> bool:
        """
        True ONCE per new motion edge; also clears the pending flag.
        Use this to trigger your action exactly once.
        """
        if self._pending:
            self._pending = False
            return True
        return False

    def consume_for(self, quiet_ms=0):
        """
        Call right after you start your action to:
          - end the current hold immediately (quiet_ms=0), or
          - extend a quiet/lockout period to avoid re-triggers.
        """
        if quiet_ms > 0:
            self._latched_until = time.ticks_add(time.ticks_ms(), quiet_ms)
        else:
            self._latched_until = time.ticks_ms()