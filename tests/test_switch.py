"""Testy přepínače nabíjení a učení IP wallboxu.

Běží na stdlib `unittest` (pytest je spustí taky), potřebují jen nainstalovaný
Home Assistant — např. přímo v kontejneru HA:

    python3 -m unittest discover -s tests -t .
"""
import asyncio
import unittest
from unittest import mock

from homeassistant.exceptions import HomeAssistantError

from custom_components.scharge import coordinator as coord_mod
from custom_components.scharge import switch as sw_mod
from custom_components.scharge.const import CONF_HOST


class _FakeCoordinator:
    """Jen to, co z koordinátoru potřebuje přepínač nabíjení."""

    serial = "TESTSN0000000001"

    def __init__(self, status, accept=True):
        self.status = status
        self.accept = accept
        self.last_authorized_current = {}
        self.sent = []

    def connector_status(self, _cid):
        return self.status

    async def send_authorize(self, cid, purpose, current):
        self.sent.append((cid, purpose, current))
        return self.accept


def _switch(coord):
    s = sw_mod.SchargeChargingSwitch(coord, 1)
    s.async_write_ha_state = lambda: None     # bez hass
    return s


class ChargingSwitchTest(unittest.TestCase):

    def test_start_drzi_on_pres_wait(self):
        # Regrese v0.7.2–v1.0.0: kód doby hájení byl mrtvý (za `return`),
        # takže switch po potvrzeném Startu hned spadl na off.
        c = _FakeCoordinator("wait")
        s = _switch(c)
        asyncio.run(s.async_turn_on())
        self.assertEqual(c.sent, [(1, "Start", sw_mod.DEFAULT_AUTHORIZE_CURRENT)])
        self.assertTrue(s.is_on)

    def test_po_vyprseni_hajeni_rozhoduje_telemetrie(self):
        c = _FakeCoordinator("wait")
        s = _switch(c)
        asyncio.run(s.async_turn_on())
        with mock.patch.object(sw_mod.time, "monotonic",
                               return_value=sw_mod.time.monotonic() + sw_mod._STARTING_GRACE + 1):
            self.assertFalse(s.is_on)

    def test_stop_rusi_hajeni(self):
        c = _FakeCoordinator("wait")
        s = _switch(c)
        asyncio.run(s.async_turn_on())
        asyncio.run(s.async_turn_off())
        self.assertFalse(s.is_on)

    def test_odmitnuti_nemeni_stav(self):
        c = _FakeCoordinator("finish", accept=False)
        s = _switch(c)
        with self.assertRaises(HomeAssistantError):
            asyncio.run(s.async_turn_on())
        self.assertFalse(s.is_on)

    def test_charging_je_on_bez_ohledu_na_hajeni(self):
        self.assertTrue(_switch(_FakeCoordinator("charging")).is_on)


class LearnHostTest(unittest.TestCase):

    def _coordinator(self, host):
        entry = mock.Mock(data={CONF_HOST: host, "serial": "X"})
        hass = mock.Mock()
        hass.config_entries.async_get_entry.return_value = entry
        c = coord_mod.SchargeCoordinator(hass, "entry1", "X", host=host)
        return c, hass, entry

    def test_nova_ip_se_ulozi(self):
        c, hass, entry = self._coordinator("192.168.78.100")
        c._learn_host(("192.168.78.107", 51234))
        self.assertEqual(c.host, "192.168.78.107")
        hass.config_entries.async_update_entry.assert_called_once_with(
            entry, data={CONF_HOST: "192.168.78.107", "serial": "X"})

    def test_stejna_ip_nic_nezapisuje(self):
        c, hass, _ = self._coordinator("192.168.78.107")
        c._learn_host(("192.168.78.107", 51234))
        hass.config_entries.async_update_entry.assert_not_called()

    def test_nezname_peer_ignoruje(self):
        c, hass, _ = self._coordinator("192.168.78.100")
        c._learn_host("?")
        self.assertEqual(c.host, "192.168.78.100")
        hass.config_entries.async_update_entry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
