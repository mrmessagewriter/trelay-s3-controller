"""Sprinklers1 early USB CDC-NCM preparation.

Install this file as /boot.py on the MicroPython writable filesystem.
The ESP32 port runs boot.py before mp_usbd_init(). Constructing USBD_NCM here
sets the real hardware-derived MAC and creates the lwIP netif before Windows
enumerates the NCM interface.

Important: do NOT call active(True) here. TinyUSB is not initialized yet.
The normal Sprinklers1 application activates NCM after USB startup.
"""

try:
    import network

    # Constructor performs ncm_init() if the singleton has not been initialized.
    # This prepares the MAC/netif before USB descriptor enumeration.
    _sprinklers1_ncm = network.USBD_NCM()

except Exception as exc:
    # Preserve boot/CDC if Python-level initialization reports an error.
    print("Sprinklers1 early NCM preparation failed:", repr(exc))
