"""Pruebas del agente (seccion 17).

Si el servidor no responde, estado.json no avanza. Al volver, se envian las
marcas pendientes. Se usan dobles en lugar de MySQL y de la red.
"""

from datetime import datetime, timezone

import pytest

import agente
import estado
from cliente_api import siguiente_espera


@pytest.fixture(autouse=True)
def estado_temporal(tmp_path, monkeypatch):
    """Cada prueba trabaja con su propio estado.json."""
    monkeypatch.setattr(estado, "ARCHIVO", tmp_path / "estado.json")
    monkeypatch.setattr(agente, "leer", estado.leer)
    monkeypatch.setattr(agente, "guardar", estado.guardar)
    return tmp_path


def utc_ms(anio, mes, dia, hora, minuto=0) -> int:
    momento = datetime(anio, mes, dia, hora, minuto, tzinfo=timezone.utc)
    return int(momento.timestamp() * 1000)


class LectorFalso:
    def __init__(self, marcas):
        self.marcas = marcas
        self.consultas = []

    def leer_desde(self, desde, limite):
        self.consultas.append(desde)
        return [m for m in self.marcas if m["utc_ms"] >= desde][:limite]


class ClienteFalso:
    def __init__(self, responde=True):
        self.responde = responde
        self.enviados = []

    def enviar(self, marcas):
        self.enviados.append(list(marcas))
        if not self.responde:
            return None
        return {
            "recibidas": len(marcas), "nuevas": len(marcas),
            "duplicadas": 0, "sin_empleado": 0,
        }


class ConfigFalsa:
    fecha_inicio = "2026-09-01"
    intervalo = 60
    ventana_horas = 48
    lote_max = 500

    def inicio_utc_ms(self):
        return utc_ms(2026, 9, 1, 0)


def marcas_de_ejemplo():
    return [
        {"person_id": "1024", "utc_ms": utc_ms(2026, 9, 7, 14)},
        {"person_id": "1024", "utc_ms": utc_ms(2026, 9, 7, 18)},
    ]


def test_si_el_servidor_no_responde_el_estado_no_avanza():
    config = ConfigFalsa()
    lector = LectorFalso(marcas_de_ejemplo())
    cliente = ClienteFalso(responde=False)

    assert agente.un_ciclo(config, lector, cliente) is False
    assert estado.leer(config.inicio_utc_ms()) == config.inicio_utc_ms()


def test_al_volver_el_servidor_se_envian_las_marcas_pendientes():
    config = ConfigFalsa()
    lector = LectorFalso(marcas_de_ejemplo())

    caido = ClienteFalso(responde=False)
    agente.un_ciclo(config, lector, caido)

    vivo = ClienteFalso(responde=True)
    assert agente.un_ciclo(config, lector, vivo) is True

    assert len(vivo.enviados[0]) == 2
    assert estado.leer(0) == utc_ms(2026, 9, 7, 18)


def test_el_estado_avanza_hasta_la_marca_mas_reciente():
    config = ConfigFalsa()
    lector = LectorFalso(marcas_de_ejemplo())
    agente.un_ciclo(config, lector, ClienteFalso())
    assert estado.leer(0) == utc_ms(2026, 9, 7, 18)


def test_se_relee_hacia_atras_la_ventana_configurada():
    """SmartPSS puede escribir marcas con horas pasadas al volver de estar cerrado."""
    config = ConfigFalsa()
    lector = LectorFalso(marcas_de_ejemplo())
    agente.un_ciclo(config, lector, ClienteFalso())
    agente.un_ciclo(config, lector, ClienteFalso())

    ultimo = utc_ms(2026, 9, 7, 18)
    esperado = ultimo - config.ventana_horas * 3600 * 1000
    assert lector.consultas[-1] == esperado


def test_un_lote_vacio_se_envia_igual_como_latido():
    config = ConfigFalsa()
    lector = LectorFalso([])
    cliente = ClienteFalso()
    assert agente.un_ciclo(config, lector, cliente) is True
    assert cliente.enviados == [[]]


def test_el_estado_sobrevive_a_un_archivo_corrupto(estado_temporal):
    (estado_temporal / "estado.json").write_text("{esto no es json", encoding="utf-8")
    assert estado.leer(12345) == 12345


def test_la_espera_crece_hasta_cinco_minutos():
    espera = 60
    vistas = []
    for _ in range(8):
        espera = siguiente_espera(espera, 60)
        vistas.append(espera)
    assert vistas[:4] == [120, 240, 300, 300]
    assert max(vistas) == 300


def test_no_se_acepta_un_nombre_de_tabla_peligroso():
    from lector_smartpss import LectorSmartPSS

    with pytest.raises(ValueError):
        LectorSmartPSS("h", 3306, "b", "u", "c", "tabla; DROP TABLE x")
