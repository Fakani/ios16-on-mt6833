/* Capture the one RX FIFO read already performed by the original probe.
 * A branch replaces its LDUR W19,[X20,#-4]; no extra FIFO read is added.
 * X17 is caller-saved and dead in the original continuation.
 */
.text
.global capture_rx
capture_rx:
    ldur w19, [x20, #-4]
    adrp x17, diag_rx
    str w19, [x17, :lo12:diag_rx]
    b probe_rx_continue
